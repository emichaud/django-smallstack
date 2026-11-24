"""A dashboard's picture (``Dashboard.cover_image``) and the My dashboards page.

Uploads go to a temporary ``MEDIA_ROOT`` so the suite never writes into the
project's media directory.
"""

from __future__ import annotations

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from apps.dashboards.models import Dashboard

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def staff():
    return User.objects.create_user("pic-staff", password="x", is_staff=True)


@pytest.fixture
def member():
    return User.objects.create_user("pic-member", password="x")


def _png(name: str = "team photo.png", size: tuple[int, int] = (32, 18)) -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _board(owner=None, **kw) -> Dashboard:
    d = Dashboard(name=kw.pop("name", "Ops"), slug=kw.pop("slug", "ops"), owner=owner, **kw)
    d.save()
    return d


def _settings_post(**extra) -> dict:
    data = {
        "name": "Ops",
        "slug": "ops",
        "description": "",
        "cover_alt": "",
        "default_period": "",
        "refresh_seconds": "",
        "layout": "[]",
        "visibility": "personal",
    }
    data.update(extra)
    return data


# -- uploading through the settings form -------------------------------------------


def test_the_form_uploads_a_picture_under_a_server_chosen_name(client, member, media):
    client.force_login(member)
    response = client.post(
        "/smallstack/dashboards/boards/new/", _settings_post(cover_image=_png(), cover_alt="The team")
    )
    assert response.status_code == 302
    board = Dashboard.objects.get(slug="ops")
    name = board.cover_image.name
    assert name.startswith("dashboards/covers/") and name.endswith(".png")
    assert "team" not in name  # the uploader's filename is discarded
    assert (media / name).exists() and board.cover_alt == "The team"


def test_the_settings_page_shows_a_thumbnail_and_posts_multipart(client, member):
    board = _board(owner=member)
    board.cover_image = _png()
    board.save()
    client.force_login(member)
    html = client.get(f"/smallstack/dashboards/boards/{board.pk}/edit/").content.decode()
    assert 'enctype="multipart/form-data"' in html
    assert "Currently:" not in html  # Django's stock ClearableFileInput text
    assert f'src="{board.cover_image.url}"' in html and 'name="cover_image-clear"' in html


@pytest.mark.parametrize(
    ("upload", "message"),
    [
        (SimpleUploadedFile("x.html", b"<script>alert(1)</script>", content_type="text/html"), "image"),
        (SimpleUploadedFile("x.png", b"not an image", content_type="image/png"), "image"),
    ],
)
def test_a_file_that_isnt_an_image_is_refused(client, member, upload, message):
    client.force_login(member)
    response = client.post("/smallstack/dashboards/boards/new/", _settings_post(cover_image=upload))
    assert response.status_code == 200 and message in response.content.decode().lower()
    assert not Dashboard.objects.exists()


def test_a_picture_over_the_limit_is_refused(client, member, monkeypatch):
    monkeypatch.setattr("apps.dashboards.models.MAX_COVER_BYTES", 10)
    client.force_login(member)
    response = client.post("/smallstack/dashboards/boards/new/", _settings_post(cover_image=_png()))
    assert "too large" in response.content.decode()
    assert not Dashboard.objects.exists()


# -- the old file goes when nothing points at it -----------------------------------


def test_replacing_clearing_and_deleting_remove_the_old_file(client, member, media, django_capture_on_commit_callbacks):
    board = _board(owner=member)
    with django_capture_on_commit_callbacks(execute=True):
        board.cover_image = _png()
        board.save()
    first = board.cover_image.name
    client.force_login(member)

    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/smallstack/dashboards/boards/{board.pk}/edit/", _settings_post(cover_image=_png()))
    board.refresh_from_db()
    second = board.cover_image.name
    assert second != first and not (media / first).exists() and (media / second).exists()

    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/smallstack/dashboards/boards/{board.pk}/edit/", _settings_post(**{"cover_image-clear": "on"}))
    board.refresh_from_db()
    assert not board.cover_image and not (media / second).exists()

    with django_capture_on_commit_callbacks(execute=True):
        board.cover_image = _png()
        board.save()
    third = board.cover_image.name
    with django_capture_on_commit_callbacks(execute=True):
        board.delete()
    assert not (media / third).exists()


def test_saving_other_fields_keeps_the_picture(client, member, media, django_capture_on_commit_callbacks):
    board = _board(owner=member)
    board.cover_image = _png()
    board.save()
    name = board.cover_image.name
    client.force_login(member)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/smallstack/dashboards/boards/{board.pk}/edit/", _settings_post(name="Renamed"))
    board.refresh_from_db()
    assert board.name == "Renamed" and board.cover_image.name == name and (media / name).exists()


# -- where the picture shows --------------------------------------------------------


def test_the_picture_shows_on_the_index_the_list_and_the_dashboard(client, member):
    board = _board(owner=member)
    board.cover_image = _png()
    board.cover_alt = "Server racks"
    board.save()
    plain = _board(owner=member, name="Plain", slug="plain")
    client.force_login(member)
    url = board.cover_image.url

    index = client.get("/smallstack/dashboards/").content.decode()
    assert f'src="{url}"' in index and "board-cover-mono" in index  # the plain one gets the generated cover
    library = client.get("/smallstack/dashboards/boards/").content.decode()
    assert f'src="{url}"' in library
    page = client.get(board.get_absolute_url()).content.decode()
    header = page[page.index('class="dash-title"') : page.index("</h1>")]
    assert f'src="{url}" alt="Server racks"' in header
    plain_page = client.get(plain.get_absolute_url()).content.decode()
    plain_header = plain_page[plain_page.index('class="dash-title"') : plain_page.index("</h1>")]
    assert "board-cover-mono" in plain_header and ">P<" in plain_header.replace(" ", "").replace("\n", "")


# -- REST + MCP ---------------------------------------------------------------------


def test_the_crud_api_returns_the_picture_url_and_a_json_patch_keeps_it(client, member):
    board = _board(owner=member)
    client.force_login(member)
    url = f"/smallstack/api/dashboards/boards/{board.pk}/"
    assert client.get(url).json()["cover_image"] is None
    board.cover_image = _png()
    board.save()
    response = client.patch(url, data=json.dumps({"name": "Renamed"}), content_type="application/json")
    board.refresh_from_db()
    assert response.status_code == 200 and board.name == "Renamed"
    assert response.json()["cover_image"] == board.cover_image.url  # a JSON write never drops the file


PICTURE = "/smallstack/dashboards/api/boards/ops/picture/"


def test_the_picture_route_sets_and_removes_it_with_a_token(member, media, django_capture_on_commit_callbacks):
    from apps.smallstack.models import APIToken

    _board(owner=member)
    _token, raw = APIToken.create_token(user=member, name="pic", access_level="auth")
    api = Client(enforce_csrf_checks=True, HTTP_AUTHORIZATION=f"Bearer {raw}")

    out = api.post(PICTURE, {"image": _png(), "alt": "Racks"}).json()
    board = Dashboard.objects.get(slug="ops")
    assert out == {"ok": True, "cover_image": board.cover_image.url, "cover_alt": "Racks"}
    name = board.cover_image.name

    with django_capture_on_commit_callbacks(execute=True):
        assert api.delete(PICTURE).json() == {"ok": True, "cover_image": None, "cover_alt": ""}
    assert not Dashboard.objects.get(slug="ops").cover_image and not (media / name).exists()


def test_the_picture_route_checks_csrf_for_a_session(member):
    _board(owner=member)
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(member)
    refused = browser.post(PICTURE, {"image": _png()})
    body = refused.json()
    # Refused by the API's session check (eval 45 A-csrf) before the route's own.
    assert refused.status_code == 403 and "CSRF" in (body.get("error") or body["errors"]["__all__"][0])
    assert not Dashboard.objects.get(slug="ops").cover_image

    browser.get("/smallstack/dashboards/mine/")  # sets the csrftoken cookie
    token = browser.cookies["csrftoken"].value
    assert browser.post(PICTURE, {"image": _png()}, HTTP_X_CSRFTOKEN=token).status_code == 200


def test_the_picture_route_refuses_what_it_should(client, member, staff):
    from apps.smallstack.models import APIToken

    _board(owner=member)
    _token, raw = APIToken.create_token(user=member, name="ro", access_level="readonly")
    readonly = Client(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert readonly.post(PICTURE, {"image": _png()}).status_code == 403

    _token, raw = APIToken.create_token(user=staff, name="st", access_level="staff")
    other = Client(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert other.post(PICTURE, {"image": _png()}).status_code == 403  # staff may view, not edit, a personal board

    _token, raw = APIToken.create_token(user=member, name="rw", access_level="auth")
    owner = Client(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert owner.post(PICTURE, {}).status_code == 400
    bad = owner.post(PICTURE, {"image": SimpleUploadedFile("x.png", b"nope", content_type="image/png")})
    assert bad.status_code == 400 and "cover_image" in bad.json()["problems"]
    assert Client().post(PICTURE, {"image": _png()}).status_code == 401


def test_the_mcp_tool_sets_and_removes_the_picture(member, staff):
    import base64

    from apps.dashboards.tests.test_dashboards import _call

    _board(owner=member)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()

    out = _call("dashboard_set_picture", {"dashboard": "ops", "image_base64": encoded, "filename": "a.png"}, member)
    assert out["ok"] and out["cover_image"].startswith("/media/dashboards/covers/")
    assert "error" in _call("dashboard_set_picture", {"dashboard": "ops", "image_base64": encoded}, staff)
    garbled = _call("dashboard_set_picture", {"dashboard": "ops", "image_base64": "%%"}, member)
    assert "not valid base64" in garbled["error"]
    notimage = base64.b64encode(b"hello").decode()
    assert "problems" in _call("dashboard_set_picture", {"dashboard": "ops", "image_base64": notimage}, member)
    assert _call("dashboard_set_picture", {"dashboard": "ops", "remove": True}, member)["cover_image"] is None


def test_mcp_write_tools_leave_file_fields_out(staff):
    from apps.dashboards.views import DashboardCRUDView
    from apps.mcp.factory import _build_form_input_schema

    props = _build_form_input_schema(DashboardCRUDView)["properties"]
    assert "cover_image" not in props  # a JSON argument can't carry a file
    assert "cover_alt" in props and "layout" in props


# -- My dashboards -----------------------------------------------------------------


def test_my_dashboards_lists_only_what_you_own_newest_change_first(client, member, staff):
    older = _board(owner=member, name="Older", slug="older")
    newer = _board(owner=member, name="Newer", slug="newer")
    _board(owner=None, name="Everyone's", slug="shared")
    _board(owner=staff, name="Someone else's", slug="theirs")
    Dashboard.objects.filter(pk=older.pk).update(updated_at=newer.updated_at.replace(year=2020))

    client.force_login(member)
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert html.index("Newer") < html.index("Older")
    assert "Everyone&#x27;s" not in html and "Someone else" not in html
    assert f"/smallstack/dashboards/boards/{newer.pk}/edit/" in html  # Settings
    assert "/smallstack/dashboards/d/newer/digest/" not in html  # no cards, nothing to check


def test_my_dashboards_checks_attention_for_boards_with_cards(client, member):
    board = _board(owner=member, layout=[{"id": "n", "type": "text", "w": 3, "h": 2, "options": {"markdown": "hi"}}])
    client.force_login(member)
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert f'hx-get="/smallstack/dashboards/d/{board.slug}/digest/"' in html and "1 card," in html


def test_my_dashboards_empty_state_points_at_shared_ones(client, member):
    _board(owner=None, name="Everyone's", slug="shared")
    client.force_login(member)
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert "Make a dashboard of your own" in html and "1 dashboard shared by others is on the" in html


def test_a_shared_dashboard_you_made_is_still_yours(client, staff):
    made = _board(owner=None, name="Team board", slug="team")
    made.created_by = staff
    made.save()
    _board(owner=None, name="Someone else's shared", slug="other-shared")  # made by nobody we know
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert "Team board" in html and "Someone else" not in html
    assert 'dash-badge--shared">Shared' in html and f"/smallstack/dashboards/boards/{made.pk}/edit/" in html


def test_staff_creating_a_shared_dashboard_records_who_made_it(client, staff):
    client.force_login(staff)
    client.post("/smallstack/dashboards/boards/new/", _settings_post(visibility="shared"))
    board = Dashboard.objects.get(slug="ops")
    assert board.owner_id is None and board.created_by == staff
    assert "Ops" in client.get("/smallstack/dashboards/mine/").content.decode()


def test_rest_and_mcp_creates_record_who_made_it(client, staff):
    from apps.dashboards.tests.test_dashboards import _call

    client.force_login(staff)
    response = client.post(
        "/smallstack/api/dashboards/boards/",
        data=json.dumps({"name": "Via REST", "slug": "via-rest", "visibility": "shared"}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["created_by"]["id"] == staff.pk
    _call("create_dashboard", {"name": "Via MCP", "slug": "via-mcp", "visibility": "shared"}, staff)
    assert Dashboard.objects.get(slug="via-mcp").created_by == staff


def test_without_edit_rights_a_shared_board_you_made_has_no_settings_link(client, member):
    """A staff member who made a shared board and was later demoted still sees
    it as theirs, but can no longer edit it."""
    board = _board(owner=None, name="Old team board", slug="old-team")
    board.created_by = member
    board.save()
    client.force_login(member)
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert "Old team board" in html and f"/boards/{board.pk}/edit/" not in html


def test_the_backfill_credits_personal_rows_to_their_owner(member):
    import importlib

    from django.apps import apps as global_apps

    personal = _board(owner=member)
    shared = _board(owner=None, name="Shared", slug="shared")
    module = importlib.import_module("apps.dashboards.migrations.0004_created_by")
    module.backfill(global_apps, None)
    personal.refresh_from_db()
    shared.refresh_from_db()
    assert personal.created_by == member and shared.created_by is None


def test_mine_is_empty_for_anonymous_users():
    from django.contrib.auth.models import AnonymousUser

    assert list(Dashboard.objects.mine(AnonymousUser())) == []


def test_my_dashboards_needs_a_login_and_is_in_the_nav(client, member):
    assert Client().get("/smallstack/dashboards/mine/").status_code == 302
    client.force_login(member)
    html = client.get("/smallstack/dashboards/mine/").content.decode()
    assert 'href="/smallstack/dashboards/mine/"' in html and "My dashboards" in html


def test_owned_by_is_empty_for_anonymous_users():
    from django.contrib.auth.models import AnonymousUser

    assert list(Dashboard.objects.owned_by(AnonymousUser())) == []
    assert list(Dashboard.objects.owned_by(None)) == []


def test_layout_json_round_trips_through_the_settings_form(client, member):
    """The picture field must not disturb the existing JSON fields on save."""
    client.force_login(member)
    layout = [{"id": "n", "type": "text", "x": 0, "y": 0, "w": 3, "h": 2, "options": {"markdown": "hi"}}]
    client.post("/smallstack/dashboards/boards/new/", _settings_post(layout=json.dumps(layout)))
    assert Dashboard.objects.get(slug="ops").layout[0]["options"] == {"markdown": "hi"}


# -- the generated cover, and the menu link ----------------------------------------


def test_the_generated_cover_is_stable_and_uses_the_initials():
    from apps.dashboards.templatetags.dashboard_tags import COVER_MOTIFS, board_cover

    site = Dashboard(name="Site health", slug="site-health")
    first, again = board_cover(site), board_cover(site)
    assert first == again and first["monogram"] == "SH" and first["motif"] in COVER_MOTIFS
    assert board_cover(Dashboard(name="ops", slug="ops"))["monogram"] == "O"
    assert board_cover(Dashboard(name="— · —", slug="x"))["monogram"] == "D"  # nothing to abbreviate
    motifs = {board_cover(Dashboard(name=f"Board {i}", slug=f"board-{i}"))["motif"] for i in range(40)}
    assert motifs == set(COVER_MOTIFS)  # neighbours vary


def test_my_dashboards_is_in_the_user_menu(client, member):
    client.force_login(member)
    html = client.get("/smallstack/dashboards/").content.decode()
    menu = html[html.index('id="user-dropdown"') :]
    assert 'href="/smallstack/dashboards/mine/" class="dropdown-item"' in menu
