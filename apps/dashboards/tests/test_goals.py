"""Goals: numbers judged against targets, in sections, for a meeting.

The rules (``normalize_sections``), the judging (``judge`` and the words for a
rule and a miss), a list evaluated for one viewer, and the surfaces built on
it: the meeting page, the goals card, a playlist slide, "Add to goals", the
editor's form, REST and MCP — plus what follows a rename or a delete.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.activity.models import RequestLog
from apps.dashboards.boards import render_cell
from apps.dashboards.components import describe_types
from apps.dashboards.goals import evaluate_goals, gap_text, judge, normalize_sections, rule_text, suggest_target
from apps.dashboards.models import Component, Dashboard, GoalList, Metric, Playlist, Report, detach_metric
from apps.dashboards.playlists import playlist_slides
from apps.dashboards.tests.support import own

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
SEEDED = {"field": "path", "op": "in", "value": ["/a", "/b", "/c"]}


@pytest.fixture
def staff(client):
    user = User.objects.create_user("gl-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def member():
    return User.objects.create_user("gl-member", password="x")


@pytest.fixture
def metrics():
    for path, ms in (("/a", 10), ("/b", 90), ("/c", 50)):
        RequestLog.objects.create(path=path, method="GET", status_code=200, response_time_ms=ms)
    # Only the seeded rows: the request log also records the test client's own requests.
    count = Metric(key="gl_count", name="Requests", dataset=DS, period_field="timestamp", filter_tree=SEEDED)
    count.save()
    avg = Metric(
        key="gl_avg",
        name="Response time",
        dataset=DS,
        agg="avg",
        measure="response_time_ms",
        unit="ms",
        filter_tree=SEEDED,
        thresholds=[
            {"op": "<=", "value": 40, "state": "success"},
            {"op": "<=", "value": 80, "state": "warning"},
            {"op": ">", "value": 80, "state": "danger"},
        ],
    )
    avg.save()
    return count, avg


def _list(sections, owner=None, **kw) -> GoalList:
    g = GoalList(
        name=kw.pop("name", "Ops review"), slug=kw.pop("slug", "ops-review"), owner=owner, sections=sections, **kw
    )
    g.save()
    return g


def _meeting(metrics) -> GoalList:
    """Two sections: on target, at risk, missed — and a single-stat card on target."""
    Component(name="Latency card", type="metric", metric="gl_avg", options={"style": {"format": "decimal"}}).save()
    return _list(
        [
            {
                "title": "Traffic",
                "goals": [
                    {"metric": "gl_count", "target": {"op": ">=", "value": 3}},
                    {"metric": "gl_count", "label": "Stretch traffic", "target": {"op": ">=", "value": 10}},
                ],
            },
            {
                "title": "Speed",
                "goals": [
                    {
                        "metric": "gl_avg",
                        "target": {"op": "<=", "value": 40},
                        "warn": {"op": "<=", "value": 60},
                        "note": "Platform team",
                    },
                    {"component": "latency_card", "target": {"op": "<", "value": 100}},
                ],
            },
        ]
    )


# -- the rules ---------------------------------------------------------------------


def test_goals_get_ids_and_a_bare_list_becomes_one_section(metrics):
    sections, problems = normalize_sections(
        [{"metric": "gl_count", "target": {"op": ">=", "value": 3}, "label": "", "note": None}], owner_id=None
    )
    assert problems == []
    assert sections == [
        {"title": "", "goals": [{"id": "g1", "metric": "gl_count", "target": {"op": ">=", "value": 3}}]}
    ]


@pytest.mark.parametrize(
    ("goal", "problem"),
    [
        ({"metric": "ghost", "target": {"op": ">=", "value": 1}}, "no metric with key 'ghost'"),
        ({"target": {"op": ">=", "value": 1}}, "name a 'metric' or a 'component'"),
        ({"metric": "gl_count", "component": "x", "target": {"op": ">=", "value": 1}}, "one of them"),
        ({"metric": "gl_count"}, "target: an object with 'op' and 'value'"),
        ({"metric": "gl_count", "target": {"op": "~", "value": 1}}, "target.op"),
        ({"metric": "gl_count", "target": {"op": ">=", "value": "lots"}}, "target.value: a number"),
        ({"metric": "gl_count", "target": {"op": "between", "value": [9, 1]}}, "low must not be above high"),
        ({"metric": "gl_count", "target": {"op": ">=", "value": 1}, "warn": {"op": ">="}}, "warn.value"),
        ({"metric": "gl_count", "target": {"op": ">=", "value": 1}, "period": "fortnight"}, "not a known period"),
        ({"metric": "gl_count", "target": {"op": ">=", "value": 1}, "colour": "red"}, "unexpected key(s)"),
    ],
)
def test_bad_goals_are_refused(metrics, goal, problem):
    _sections, problems = normalize_sections([{"title": "S", "goals": [goal]}], owner_id=None)
    assert any(problem in p for p in problems), problems


def test_a_shared_list_cant_carry_personal_metrics_and_only_one_number_cards_qualify(metrics, member):
    Metric(key="mine", name="Mine", dataset=DS, owner=member).save()
    with pytest.raises(ValidationError, match="is a personal metric"):
        _list([{"title": "", "goals": [{"metric": "mine", "target": {"op": ">=", "value": 1}}]}])
    assert (
        _list([{"title": "", "goals": [{"metric": "mine", "target": {"op": ">=", "value": 1}}]}], owner=member).owner
        == member
    )
    Component(name="By method", type="metric_group", **own("gl_count"), options={"dimension": "method"}).save()
    _s, problems = normalize_sections(
        [{"title": "", "goals": [{"component": "by_method", "target": {"op": ">=", "value": 1}}]}], owner_id=None
    )
    assert "isn't a one-number card" in problems[0]
    # One number, but filtered by the card itself: a goal judges a metric, so it's saved as one first.
    Component(name="Own stat", type="metric", **own("gl_count"), options={}).save()
    _s, problems = normalize_sections(
        [{"title": "", "goals": [{"component": "own_stat", "target": {"op": ">=", "value": 1}}]}], owner_id=None
    )
    assert "filters a dataset of its own" in problems[0] and "save its filter as a metric first" in problems[0]


# -- judging ---------------------------------------------------------------------


def test_judging_a_value():
    target, warn = {"op": ">=", "value": 95}, {"op": ">=", "value": 90}
    assert [judge(v, target, warn) for v in (97, 92, 80, None, "n/a")] == ["pass", "warn", "fail", "none", "none"]
    assert judge(92, target) == "fail"  # no at-risk line: anything short is missed
    assert judge(5, {"op": "between", "value": [1, 10]}) == "pass"


def test_rules_and_misses_read_in_the_values_format():
    assert rule_text({"op": ">=", "value": 95}, "percent") == "≥ 95.0%"
    assert rule_text({"op": "between", "value": [100, 200]}, "number", "ms") == "100–200 ms"
    assert gap_text(88, {"op": ">=", "value": 95}, "percent") == "7.0% short"
    assert gap_text(130, {"op": "<=", "value": 100}, "number", "ms") == "30 ms over"
    assert gap_text(97, {"op": ">=", "value": 95}) == ""


def test_a_target_is_suggested_from_the_metrics_colour_rules(metrics):
    assert suggest_target(metrics[1]) == {"target": {"op": "<=", "value": 40}, "warn": {"op": "<=", "value": 80}}
    assert suggest_target(metrics[0]) == {}


# -- a list, evaluated --------------------------------------------------------------


def test_a_goal_list_is_judged_per_goal_per_section_and_overall(rf_request, metrics):
    data = evaluate_goals(_meeting(metrics), rf_request)
    traffic, speed = data["sections"]
    assert [r["status"] for r in traffic["rows"]] == ["pass", "fail"]
    assert traffic["rows"][1]["gap_text"] == "7 short" and traffic["rows"][1]["label"] == "Stretch traffic"
    latency, card = speed["rows"]
    assert (latency["status"], latency["display"], latency["unit"], latency["note"]) == (
        "warn",
        "50",
        "ms",
        "Platform team",
    )
    assert (latency["target_text"], latency["warn_text"]) == ("≤ 40 ms", "≤ 60 ms")
    # A card goal takes the card's name and number format.
    assert (card["label"], card["display"], card["status"]) == ("Latency card", "50.00", "pass")
    summary = data["summary"]
    assert (summary["pass"], summary["warn"], summary["fail"], summary["headline"]) == (2, 1, 1, "2 of 4 on target")
    assert [r["label"] for r in data["attention"]] == ["Stretch traffic", "Response time"]
    assert traffic["summary"]["headline"] == "1 of 2 on target"


def test_a_goal_on_a_deleted_metric_shows_why(rf_request, metrics):
    goal_list = _meeting(metrics)
    Metric.objects.filter(key="gl_count").delete()  # under the model's feet
    row = evaluate_goals(goal_list, rf_request)["rows"][0]
    assert row["status"] == "none" and "no longer exists" in row["error"]


@pytest.fixture
def rf_request(staff):
    request = RequestFactory().get("/")
    request.user = staff
    return request


# -- the meeting page ----------------------------------------------------------------


def test_the_meeting_page(client, staff, metrics):
    _meeting(metrics)
    html = client.get("/smallstack/dashboards/g/ops-review/").content.decode()
    assert '<span class="gl-big">2</span> <span class="gl-of">of 4</span>' in html
    assert ">Traffic</h2>" in html and ">Speed</h2>" in html
    for word in ("On target", "At risk", "Missed", "7 short", "Platform team", "Needs attention"):
        assert word in html, word
    assert 'href="#goal-g2"' in html and 'id="goal-g2"' in html  # attention links jump to the row
    assert 'hx-get="/smallstack/dashboards/m/gl_count/rows/' in html  # values drill into their rows
    assert "Edit goals" in html and "?present=1" in html


def test_presenting_drops_the_chrome(client, staff, metrics):
    _meeting(metrics)
    html = client.get("/smallstack/dashboards/g/ops-review/?present=1").content.decode()
    assert "gl-present" in html and "Exit presenting" in html and "page-header-bleed" not in html


def test_a_personal_list_is_its_owners(client, member, metrics):
    _list([], owner=member, slug="theirs")
    other = User.objects.create_user("gl-other", password="x")
    client.force_login(other)
    assert client.get("/smallstack/dashboards/g/theirs/").status_code == 404


# -- the goals card -----------------------------------------------------------------


def test_the_goals_card_shows_the_first_goals_or_the_misses_first(rf_request, metrics):
    _meeting(metrics)
    board = Dashboard(
        name="Ops",
        slug="ops",
        layout=[
            {"id": "a", "type": "goals", "options": {"goal_list": "ops-review", "limit": 2}},
            {"id": "b", "type": "goals", "options": {"goal_list": "ops-review", "limit": 2, "order": "attention"}},
        ],
    )
    board.save()
    first = render_cell(board, board.cell("a"), rf_request, None)
    assert "2 of 4 on target" in first and "2 more goals" in first
    assert first.index("Requests") < first.index("Stretch traffic") and "Response time" not in first
    misses = render_cell(board, board.cell("b"), rf_request, None)
    assert misses.index("Stretch traffic") < misses.index("Response time") and "Latency card" not in misses
    with pytest.raises(ValidationError, match="goal_list"):
        Dashboard(name="Bad", slug="bad", layout=[{"type": "goals", "options": {"goal_list": "ghost"}}]).save()


def test_the_card_offers_your_goal_lists(staff, metrics):
    _meeting(metrics)
    spec = {t["type"]: t for t in describe_types(staff)}["goals"]["options"][0]
    assert spec["choices"] == [["ops-review", "Ops review"]]
    assert {t["type"]: t for t in describe_types()}["goals"]["options"][0]["choices"] == []
    assert {t["type"]: t for t in describe_types()}["metric"]["single_value"] is True


def test_the_dashboard_editor_offers_your_goal_lists(client, staff, metrics):
    _meeting(metrics)
    Dashboard(name="Ops", slug="ops").save()
    html = client.get("/smallstack/dashboards/d/ops/").content.decode()
    editor = json.loads(html.split('id="dash-editor-data" type="application/json">', 1)[1].split("</script>", 1)[0])
    spec = {t["type"]: t for t in editor["types"]}["goals"]["options"][0]
    assert spec["choices"] == [["ops-review", "Ops review"]]


# -- playlists ---------------------------------------------------------------------


def test_a_goal_list_is_a_playlist_slide(client, staff, metrics):
    _meeting(metrics)
    Dashboard(name="Ops", slug="ops").save()
    playlist = Playlist(name="Wall", slug="wall", items=[{"dashboard": "ops"}, {"goals": "ops-review", "seconds": 60}])
    playlist.save()
    slides = playlist_slides(playlist, staff)
    assert [(s["kind"], s["slug"], s["seconds"]) for s in slides] == [
        ("dashboard", "ops", 30),
        ("goals", "ops-review", 60),
    ]
    slide = client.get("/smallstack/dashboards/p/wall/slides/2/").content.decode()
    assert "gl-board" in slide and 'gl-of">of 4' in slide and 'id="goal-' not in slide
    api = client.get("/smallstack/dashboards/api/playlists/wall/slides/").json()
    assert api["slides"][1]["kind"] == "goals"


def test_playlists_follow_a_renamed_or_deleted_goal_list(metrics, member):
    goal_list = _meeting(metrics)
    Playlist(name="Wall", slug="wall", items=[{"goals": "ops-review"}]).save()
    goal_list.slug = "weekly"
    goal_list.save()
    assert Playlist.objects.get().items == [{"goals": "weekly"}]
    goal_list.delete()
    assert Playlist.objects.get().items == []
    _list([], owner=member, slug="theirs")
    with pytest.raises(ValidationError, match="personal goal list"):
        Playlist(name="Shared", slug="shared", items=[{"goals": "theirs"}]).save()


# -- adding a goal from a metric or a card ----------------------------------------------


def test_add_to_goals_prefills_from_the_colour_rules_and_appends(client, staff, metrics):
    goal_list = _meeting(metrics)
    form = client.get("/smallstack/dashboards/goals/add/?metric=gl_avg", HTTP_HX_REQUEST="true").content.decode()
    assert 'name="value" id="id_value" class="vTextField" value="40"' in form
    assert '<option value="&lt;=" selected>' in form and 'data-sections="Traffic|Speed"' in form
    done = client.post(
        "/smallstack/dashboards/goals/add/",
        {"metric": "gl_avg", "goal_list": "ops-review", "section": "speed", "op": "<=", "value": "45", "warn_op": ""},
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert "Added <strong>Response time</strong>" in done
    goal_list.refresh_from_db()
    assert goal_list.sections[1]["goals"][-1] == {"id": "g5", "metric": "gl_avg", "target": {"op": "<=", "value": 45}}
    # A new section title starts a section; a card goes in by its key.
    client.post(
        "/smallstack/dashboards/goals/add/",
        {
            "component": "latency_card",
            "goal_list": "ops-review",
            "section": "Latency",
            "op": "between",
            "value": "1",
            "value2": "99",
        },
    )
    goal_list.refresh_from_db()
    assert goal_list.sections[-1] == {
        "title": "Latency",
        "goals": [{"id": "g6", "component": "latency_card", "target": {"op": "between", "value": [1, 99]}}],
    }


def test_you_can_only_add_to_a_list_you_may_edit(client, member, metrics):
    goal_list = _meeting(metrics)  # shared: staff edit it
    client.force_login(member)
    page = client.get("/smallstack/dashboards/goals/add/?metric=gl_count").content.decode()
    assert "You don't have a goal list you can add to yet" in page
    _list([], owner=member, name="Mine", slug="mine")
    response = client.post(
        "/smallstack/dashboards/goals/add/", {"metric": "gl_count", "goal_list": "ops-review", "op": ">=", "value": "1"}
    )
    assert "Select a valid choice" in response.content.decode()
    goal_list.refresh_from_db()
    assert len(goal_list.goals()) == 4


# -- the editor, the list, REST, MCP -----------------------------------------------------


def test_the_editor_saves_sections(client, staff, metrics):
    sections = [{"title": "Traffic", "goals": [{"metric": "gl_count", "target": {"op": ">=", "value": 3}}]}]
    response = client.post(
        "/smallstack/dashboards/goals/new/",
        {
            "name": "Weekly",
            "slug": "weekly",
            "description": "",
            "default_period": "last_7",
            "visibility": "shared",
            "sections": json.dumps(sections),
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    saved = GoalList.objects.get(slug="weekly")
    assert response.url == "/smallstack/dashboards/g/weekly/"  # back to the list you were arranging
    assert saved.sections[0]["goals"][0]["id"] == "g1" and saved.created_by == staff and saved.owner is None
    page = client.get(f"/smallstack/dashboards/goals/{saved.pk}/edit/").content.decode()
    data = json.loads(page.split('id="glf-data" type="application/json">', 1)[1].split("</script>", 1)[0])
    avg = next(m for m in data["metrics"] if m["key"] == "gl_avg")
    assert avg["suggest"]["target"] == {"op": "<=", "value": 40} and data["ops"][0][0] == ">="
    bad = client.post(
        f"/smallstack/dashboards/goals/{saved.pk}/edit/",
        {
            "name": "Weekly",
            "slug": "weekly",
            "sections": json.dumps([{"title": "", "goals": [{"metric": "gl_count"}]}]),
        },
    )
    assert "target: an object" in bad.content.decode()


def test_the_goal_lists_list_is_a_sortable_resizable_table(client, staff, metrics):
    _meeting(metrics)
    _list([], name="alpha", slug="alpha")
    html = client.get("/smallstack/dashboards/goals/?ordering=name").content.decode()
    assert (
        'data-table-key="dashboards/goals:' in html and 'hx-get="/smallstack/dashboards/g/ops-review/digest/"' in html
    )
    assert html.index(">alpha<") < html.index(">Ops review<")
    digest = client.get("/smallstack/dashboards/g/ops-review/digest/").content.decode()
    assert "2 of 4 on target, 1 missed, 1 at risk" in digest


def test_rest_and_mcp(client, staff, metrics):
    from apps.dashboards.tests.test_dashboards import _call

    _meeting(metrics)
    api = client.get("/smallstack/dashboards/api/goals/ops-review/values/").json()
    assert api["summary"]["headline"] == "2 of 4 on target"
    assert api["sections"][1]["goals"][0] == {
        **api["sections"][1]["goals"][0],
        "metric": "gl_avg",
        "status": "warn",
        "target": {"op": "<=", "value": 40},
        "target_text": "≤ 40 ms",
    }
    assert _call("goal_list_values", {"goal_list": "ops-review", "period": "all"}, staff)["summary"]["pass"] == 2
    added = _call(
        "goal_list_add_goal",
        {"goal_list": "ops-review", "section": "Traffic", "metric": "gl_count", "target": {"op": ">=", "value": 1}},
        staff,
    )
    assert added["ok"] and added["goal"]["id"] == "g5"
    assert "problems" in _call(
        "goal_list_add_goal", {"goal_list": "ops-review", "metric": "ghost", "target": {"op": ">=", "value": 1}}, staff
    )


# -- what follows a delete -----------------------------------------------------------


def test_goals_cards_follow_a_renamed_or_deleted_list(metrics):
    goal_list = _meeting(metrics)
    cell = {"id": "a", "type": "goals", "options": {"goal_list": "ops-review"}}
    board = Dashboard(name="Ops", slug="ops", layout=[cell])
    board.save()
    goal_list.slug = "weekly"
    goal_list.save()
    board.refresh_from_db()
    assert board.layout[0]["options"]["goal_list"] == "weekly"
    goal_list.delete()
    board.refresh_from_db()
    assert board.layout == []
    board.save()  # nothing left to refuse


def test_the_at_risk_suggestion_stops_at_the_danger_rule():
    metric = Metric(
        thresholds=[
            {"op": ">=", "value": 800, "state": "danger"},
            {"op": ">=", "value": 300, "state": "warning"},
            {"op": "<", "value": 300, "state": "success"},
        ]
    )
    suggested = suggest_target(metric)
    assert suggested == {"target": {"op": "<", "value": 300}, "warn": {"op": "<", "value": 800}}
    assert judge(900, suggested["target"], suggested["warn"]) == "fail"  # never merely "at risk"
    assert judge(500, suggested["target"], suggested["warn"]) == "warn"


def test_a_dashboards_values_include_its_goals_card(rf_request, metrics):
    from apps.dashboards.boards import board_values

    _meeting(metrics)
    board = Dashboard(
        name="Ops", slug="ops", layout=[{"id": "a", "type": "goals", "options": {"goal_list": "ops-review"}}]
    )
    board.save()
    assert board_values(board, rf_request, None)[0]["goals"]["summary"]["headline"] == "2 of 4 on target"


def test_deleting_a_metric_takes_its_goals_and_a_deleted_card_hands_over_to_its_metric(staff, metrics):
    goal_list = _meeting(metrics)
    Component.objects.get(key="latency_card").delete()
    goal_list.refresh_from_db()
    assert goal_list.sections[1]["goals"][1] == {
        "id": "g4",
        "metric": "gl_avg",
        "label": "Latency card",
        "target": {"op": "<", "value": 100},
    }
    _cards, rows = detach_metric(Metric.objects.get(key="gl_count"), staff)
    goal_list.refresh_from_db()
    assert rows == 2 and goal_list.sections[0]["goals"] == []


# -- My dashboards, as a table -----------------------------------------------------------


def test_my_dashboards_as_a_sortable_resizable_table(client, staff):
    for name, cells in (("bravo", 1), ("Alpha", 3), ("charlie", 0)):
        layout = [{"type": "text", "options": {"markdown": "x"}, "x": 0, "y": i * 4} for i in range(cells)]
        d = Dashboard(name=name, slug=name.lower(), layout=layout, owner=staff)
        d.created_by = staff
        d.save()

    def order(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/mine/?view=table&{query}").content.decode()
        return sorted(("Alpha", "bravo", "charlie"), key=lambda n: page.index(f'class="lib-name">{n}<'))

    html = client.get("/smallstack/dashboards/mine/?view=table").content.decode()
    assert 'data-table-key="dashboards/mine:' in html and html.count('class="col-resizer"') == 6
    assert 'hx-select="#my-page"' in html
    assert order("ordering=name") == ["Alpha", "bravo", "charlie"]  # ignoring case
    assert order("ordering=-name") == ["charlie", "bravo", "Alpha"]
    assert order("ordering=cards") == ["charlie", "bravo", "Alpha"]
    assert order("ordering=-cards") == ["Alpha", "bravo", "charlie"]
    cards = client.get("/smallstack/dashboards/mine/").content.decode()
    assert 'class="my-boards"' in cards and "crud-table" not in cards


# -- the Goals area in the menu --------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "parent", "child"),
    [
        ("/smallstack/goals/", "Goals", None),
        ("/smallstack/dashboards/metrics/", "Goals", "Metrics"),
        ("/smallstack/dashboards/m/gl_count/", "Goals", "Metrics"),
        ("/smallstack/dashboards/g/ops-review/", "Goals", "Goal lists"),
        ("/smallstack/dashboards/reports/", "Goals", "Reports"),
        ("/smallstack/dashboards/components/", "Dashboards", "Components"),
        ("/smallstack/dashboards/p/wall/", "Dashboards", "Playlists"),
    ],
)
def test_the_menu_highlights_the_right_area(staff, metrics, path, parent, child):
    from apps.smallstack.navigation import nav

    _meeting(metrics)
    request = RequestFactory().get(path)
    request.user = staff
    main = next(sec["items"] for sec in nav.get_nav_items(request) if sec["section"] == "main")
    items = {i["label"]: i for i in main}
    group = items[parent]
    lit = [c["label"] for c in group["children"] if c["active"]]
    if child is None:
        assert group["active"] or lit == ["Overview"]
    else:
        assert lit == [child] and group["has_active_child"]
    other = items["Dashboards" if parent == "Goals" else "Goals"]
    assert not other["active"] and not other["has_active_child"]


def test_the_goals_overview(client, staff, metrics):
    _meeting(metrics)
    html = client.get("/smallstack/goals/").content.decode()
    assert ">Goal lists</h2>" in html and 'hx-get="/smallstack/dashboards/g/ops-review/digest/"' in html
    assert 'id="ix-metric-section"' in html and "Response time" in html
    assert "?present=1" in html and "New goal list" in html
    dash = client.get("/smallstack/dashboards/").content.decode()
    assert 'id="ix-metric-section"' not in dash and 'id="ix-comp-title"' in dash and "Latency card" in dash


# -- sorting and resizing the meeting view ------------------------------------------------


def test_the_meeting_view_sorts_within_sections_and_resizes(client, staff, metrics):
    _meeting(metrics)

    def order(query: str) -> list[str]:
        page = client.get(f"/smallstack/dashboards/g/ops-review/?{query}").content.decode()
        tables = page[page.index('class="gl-section"') :]  # past the summary's attention list
        names = ["Requests", "Stretch traffic", "Response time", "Latency card"]
        return sorted(names, key=lambda n: tables.index(f">{n}</a>"))

    html = client.get("/smallstack/dashboards/g/ops-review/").content.decode()
    assert 'class="gl-table crud-table" data-table-key="dashboards/goals-board:goal,status,value,target' in html
    assert html.count('class="col-resizer"') >= 8 and 'hx-select="#gl-page"' in html
    assert "Back to the list's order" not in html
    # Rows move within their section; Traffic stays above Speed.
    assert order("order=-goal") == ["Stretch traffic", "Requests", "Response time", "Latency card"]
    assert order("order=status") == ["Stretch traffic", "Requests", "Response time", "Latency card"]  # missed first
    assert order("order=-value") == ["Requests", "Stretch traffic", "Response time", "Latency card"]  # 3 = 3; 50 = 50
    sorted_page = client.get("/smallstack/dashboards/g/ops-review/?order=status&period=mtd").content.decode()
    assert "Back to the list's order" in sorted_page and "order=status" in sorted_page.split('id="gl-page"')[1][:3000]
    assert order("order=bogus") == ["Requests", "Stretch traffic", "Response time", "Latency card"]


def test_slides_and_cards_have_no_sorting(client, staff, metrics):
    _meeting(metrics)
    Playlist(name="Wall", slug="wall", items=[{"goals": "ops-review"}]).save()
    slide = client.get("/smallstack/dashboards/p/wall/slides/1/").content.decode()
    assert "gl-table" in slide and "col-resizer" not in slide and "dm-sort" not in slide


# -- the Goals overview's tables ----------------------------------------------------------


def test_the_goals_overview_tables_sort_on_their_own_and_resize(client, staff, metrics):
    _meeting(metrics)
    _list([], name="alpha", slug="alpha")
    Report(name="Zed", slug="zed", items=["gl_count"]).save()
    Report(name="apple", slug="apple", items=["gl_avg"], periods=["mtd", "pmtd"]).save()

    def page(query: str = "") -> str:
        return client.get(f"/smallstack/goals/?{query}").content.decode()

    html = page()
    for key in (
        "lists:name,goals,now,updated_at",
        "metrics:name,source,used,value",
        "reports:name,movement,updated_at",
    ):
        assert f'data-table-key="goals/overview-{key}"' in html, key
    assert html.count('class="col-resizer"') == 11
    assert html.count('hx-select="#gx-page"') >= 9  # every sort swaps the body, so all links stay current

    def between(text: str, start: str, end: str) -> str:
        return text[text.index(start) : text.index(end)]

    lists = between(page("lists=name"), 'id="ix-goals-section"', 'id="ix-metric-section"')
    assert lists.index(">alpha<") < lists.index(">Ops review<")  # ignoring case
    lists = between(page("lists=-goals"), 'id="ix-goals-section"', 'id="ix-metric-section"')
    assert lists.index(">Ops review<") < lists.index(">alpha<")  # 4 goals, then none
    reports = page("reports=name")[page("reports=name").index('id="ix-report-section"') :]
    assert reports.index(">apple<") < reports.index(">Zed<")
    metric_rows = between(page("metrics=-value"), 'id="ix-metric-section"', 'id="ix-report-section"')
    assert metric_rows.index(">Response time<") < metric_rows.index(">Requests<")  # 50, then 3
    metric_rows = between(page("metrics=value"), 'id="ix-metric-section"', 'id="ix-report-section"')
    assert metric_rows.index(">Requests<") < metric_rows.index(">Response time<")
    # One table's sort keeps the others', and the period.
    both = page("lists=name&period=mtd")
    assert "lists=name" in between(both, 'id="ix-metric-section"', 'id="ix-report-section"')
    assert "period=mtd" in both[both.index('id="ix-report-section"') :]
    assert page("lists=bogus&metrics=bogus&reports=bogus")  # an unknown sort falls back to the default
