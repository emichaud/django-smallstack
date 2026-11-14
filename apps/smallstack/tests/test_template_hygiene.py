"""Template-hygiene guards — F-45 (2026-09-25).

Django's ``{# … #}`` is a **single-line** comment: the lexer only strips it when
the whole comment sits on one line, so a multi-line one is emitted verbatim as
body text. Three such comments shipped in a round of fixes and rendered the
author's own explanatory notes to the user — on the approvals decision console
and in *every* CRUDView's empty state.

Nothing caught it: 2,572 unit tests, ruff, mypy, ``manage.py check`` and a
96-assertion integration harness all passed, because none of them assert on
rendered body text. These two tests close that gap from both ends:

* :func:`test_no_template_has_a_multi_line_hash_comment` is the cheap, total
  guard — it reads every template in the tree, so it also covers templates no
  test renders (``smallstack/starter.html``, which is documented as
  "copy this file", had twelve).
* :func:`test_rendered_crud_pages_contain_no_template_tokens` is the end-to-end
  guard, over the pages that actually regressed, for all three token spellings.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.urls import reverse

from apps.smallstack import template_hygiene as hygiene

pytestmark = pytest.mark.django_db

User = get_user_model()

_REPO_ROOT = hygiene.REPO_ROOT
_SKIP_DIRS = hygiene._SKIP_DIRS
_project_templates = hygiene.project_templates


def test_the_hygiene_sweep_actually_sees_the_templates():
    """Negative control: a guard over an empty file list would pass vacuously."""
    templates = _project_templates()
    assert len(templates) > 100, f"only found {len(templates)} templates — sweep is broken"
    names = {p.name for p in templates}
    assert "object_list.html" in names
    assert "starter.html" in names


def test_no_template_has_a_multi_line_hash_comment():
    """``{# … #}`` must open and close on one line or Django renders it verbatim.

    Use ``{% comment %}…{% endcomment %}`` for anything multi-line.
    """
    offenders: list[str] = []
    for path in _project_templates():
        text = path.read_text(errors="replace")
        for match in re.finditer(r"\{#", text):
            close = text.find("#}", match.start())
            line = text[: match.start()].count("\n") + 1
            rel = path.relative_to(_REPO_ROOT)
            if close == -1:
                offenders.append(f"{rel}:{line} — unclosed {{#")
            elif "\n" in text[match.start() : close]:
                snippet = text[match.start() : close + 2].splitlines()[0][:60]
                offenders.append(f"{rel}:{line} — multi-line {{# … #}}: {snippet}…")
    assert not offenders, (
        "Multi-line {# #} comments render as visible page text. Use "
        "{% comment %}…{% endcomment %} instead:\n  " + "\n  ".join(offenders)
    )


def test_the_multi_line_comment_check_would_catch_a_real_one(tmp_path):
    """Prove the detector is not vacuous, using the exact shape that shipped."""
    leaky = "<p>\n    {# one line\n       and a second #}\n    Nothing matches.\n</p>\n"
    rendered = get_template(
        "smallstack/crud/includes/empty_state.html"
    )  # a real include, for the loader
    assert rendered is not None
    # The detector logic, applied to the offending text.
    match = re.search(r"\{#", leaky)
    assert match is not None
    close = leaky.find("#}", match.start())
    assert "\n" in leaky[match.start() : close], "detector would have missed it"


# --- rendered-body guard ----------------------------------------------------

_TOKENS = ("{#", "{%", "{{")


def _assert_clean(resp, label: str) -> None:
    assert resp.status_code == 200, f"{label}: HTTP {resp.status_code}"
    body = resp.content.decode()
    for token in _TOKENS:
        assert token not in body, (
            f"{label}: rendered page leaks template source {token!r} at offset "
            f"{body.find(token)}: {body[body.find(token) : body.find(token) + 140]!r}"
        )


@pytest.fixture
def hygiene_staff():
    return User.objects.create_user("tpl-hygiene-staff", password="p", is_staff=True)


def test_rendered_crud_pages_contain_no_template_tokens(client, hygiene_staff):
    """Both empty-state branches, and a populated list, on real CRUD pages.

    The filtered branch is where the leak lived; the unfiltered branch is the
    one F-44 restored, and the ``?_notification=`` case is the marker the bell
    click-through appends.
    """
    client.force_login(hygiene_staff)
    list_url = reverse("webhooks/receivers-list")
    for label, url in [
        ("empty list, no params", list_url),
        ("no-match search (filtered branch)", f"{list_url}?q=zzzznomatch"),
        ("bell marker only (unfiltered branch)", f"{list_url}?_notification=99"),
        ("pagination only (unfiltered branch)", f"{list_url}?page=1"),
        ("display toggle only (unfiltered branch)", f"{list_url}?ordering=name"),
    ]:
        _assert_clean(client.get(url), label)


def test_rendered_approvals_console_contains_no_template_tokens(client, hygiene_staff):
    """The decision console — the page the leak was most visible on."""
    from apps.approvals import services
    from apps.approvals.registry import ApprovalKind, get_kind, register_kind

    if get_kind("hygiene.kind") is None:
        register_kind(ApprovalKind(key="hygiene.kind", label="Hygiene probe"))
    requester = User.objects.create_user("tpl-hygiene-req", password="p")
    req = services.request_approval(
        kind="hygiene.kind", title="Template hygiene probe", actor=requester
    )
    client.force_login(hygiene_staff)
    # Pending + eligible → the decision panel with the autofocus note field.
    _assert_clean(
        client.get(reverse("approvals/requests-detail", args=[req.pk])),
        "approvals console (pending, decidable)",
    )


# --- F-56: release notes must not silently drift from the code --------------


class TestReleaseNotesCoverSettings:
    """Every SMALLSTACK_* setting is named in CHANGELOG.md or UPGRADING.md.

    F-56 was ~10 behaviour-changing items missing from the release notes —
    including five new settings, a new middleware, and the feature's own "Added"
    entry. Prose can't be fully tested, but "a setting exists and no release note
    ever mentions it" is mechanical, and it is the half that bit us: an operator
    cannot tune or disable what is named nowhere.

    "Findable" means named in the release notes **or** in any skill doc / in-app
    help page — i.e. anywhere an operator actually looks. Add a genuinely internal
    setting to ``_EXEMPT`` with a reason.
    """

    #: Settings deliberately absent from the release notes.
    _EXEMPT: dict[str, str] = {}

    def _setting_names(self) -> set[str]:
        import re
        from pathlib import Path

        from django.conf import settings

        src = (Path(settings.BASE_DIR) / "config" / "settings" / "smallstack.py").read_text()
        # Assignments only — skip the config("...") string literal on the RHS.
        return set(re.findall(r"^(SMALLSTACK_[A-Z0-9_]+)\s*=", src, re.M))

    def test_every_smallstack_setting_is_mentioned_in_the_release_notes(self):
        from pathlib import Path

        from django.conf import settings

        base = Path(settings.BASE_DIR)
        sources = [base / "CHANGELOG.md", base / "UPGRADING.md"]
        sources += sorted((base / "docs" / "skills").rglob("*.md"))
        sources += sorted(base.glob("apps/*/docs/*.md"))
        notes = "".join(p.read_text() for p in sources if p.exists())

        missing = sorted(
            name
            for name in self._setting_names()
            if name not in self._EXEMPT and name not in notes
        )
        assert not missing, (
            "these settings are named in no release note and no settings doc — an "
            "operator cannot find them:\n  " + "\n  ".join(missing)
        )


# -- no inline JavaScript event handlers ---------------------------------------------------------
#
# Behaviour is declared with data- attributes (data-confirm, data-autosubmit,
# data-stat-modal, data-ss-action="registeredName", …) and carried out by the
# delegated listeners in smallstack/js/theme.js. The CSP's script-src has no
# 'unsafe-inline', so an inline handler would be dead code in the browser.

def test_no_template_has_an_inline_event_handler():
    offenders = hygiene.inline_handlers(hygiene.script_templates())
    assert not offenders, "inline event handlers (use a data- attribute; see theme.js):\n" + "\n".join(
        map(str, offenders)
    )


def test_every_data_action_is_registered_by_some_script():
    """``data-ss-action="name"`` only runs a function a script registered on
    ``SmallStack.actions`` — a typo or a forgotten registration would fail
    silently in the browser, so check the names statically."""
    used: dict[str, str] = {}
    for path in _project_templates():
        for name in re.findall(r'data-ss-action="([A-Za-z_]\w*)"', path.read_text(errors="replace")):
            used.setdefault(name, str(path.relative_to(_REPO_ROOT)))
    sources = [p for p in _project_templates()] + [
        p for p in _REPO_ROOT.rglob("*.js") if not (_SKIP_DIRS & set(p.parts)) and not p.name.endswith(".min.js")
    ]
    registered: set[str] = set()
    for path in sources:
        text = path.read_text(errors="replace")
        for block in re.findall(r"SmallStack\.actions\s*=\s*Object\.assign\([^;]*\{([^}]*)\}", text):
            registered.update(re.findall(r"(\w+)\s*:", block))
        registered.update(re.findall(r"SmallStack\.actions\.(\w+)\s*=", text))
    missing = {name: where for name, where in used.items() if name not in registered}
    assert used, "found no data-ss-action at all — the sweep is broken"
    assert not missing, f"data-ss-action names no script registers: {missing}"


def test_template_values_in_data_ss_args_survive_quotes():
    """The convention for template values inside ``data-ss-args`` JSON:
    ``|escapejs``. Its backslash-u output is valid JSON and survives HTML
    attribute decoding — plain autoescape's ``&quot;`` decodes back to a raw
    quote inside the attribute and breaks the JSON."""
    import json
    from html.parser import HTMLParser

    from django.template import Context, Template

    nasty = """O'Brien "the" <b>&amp;</b> </script>"""
    html = Template("""<a data-ss-args='["$this", "{{ name|escapejs }}"]'>x</a>""").render(Context({"name": nasty}))

    class Grab(HTMLParser):
        value = ""

        def handle_starttag(self, tag, attrs):
            self.value = dict(attrs)["data-ss-args"]

    parser = Grab()
    parser.feed(html)
    assert json.loads(parser.value) == ["$this", nasty]


def test_every_template_value_in_data_ss_args_is_escapejs():
    offenders = []
    for path in _project_templates():
        for args in re.findall(r"data-ss-args='([^']*)'", path.read_text(errors="replace")):
            for value in re.findall(r"\{\{(.*?)\}\}", args):
                if "escapejs" not in value:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}: {{{{{value}}}}}")
    assert not offenders, "add |escapejs to template values inside data-ss-args:\n" + "\n".join(offenders)


# -- no inline <script> code ----------------------------------------------------------------------

def test_no_template_has_an_inline_script_block():
    """Every executable script is a static file. Server values reach it as
    data- attributes on its own tag (``document.currentScript.dataset``) or as
    a JSON data block (``json_script`` / ``<script type="application/json">``);
    the CSP's script-src has no 'unsafe-inline', so an inline block is dead."""
    offenders = hygiene.inline_scripts(hygiene.script_templates())
    assert not offenders, "inline <script> blocks (move them to static/; see templates.md):\n" + "\n".join(
        map(str, offenders)
    )


def test_csp_script_src_allows_no_inline_script():
    from django.conf import settings

    script_src = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"]
    if hygiene.inline_script_allowed():
        # The documented stopgap for a project whose own templates still carry inline
        # scripts. The framework's templates are still checked (above); say what's left.
        paths = hygiene.project_templates()
        left = len(hygiene.inline_scripts(paths)) + len(hygiene.inline_handlers(paths))
        pytest.skip(
            f"script-src allows 'unsafe-inline' (the upgrade stopgap); {left} inline scripts and "
            "handlers remain in this project — `manage.py template_hygiene` lists them"
        )
    assert "'unsafe-eval'" not in script_src


def test_every_static_path_in_a_template_exists():
    """Every literal ``{% static '…' %}`` a template references resolves through
    the staticfiles finders — what collectstatic and the dev server use. A
    moved script or stylesheet with a wrong path would otherwise 404 quietly
    (the page still renders, just unstyled or inert)."""
    from django.contrib.staticfiles import finders

    missing = []
    for path in _project_templates():
        for ref in re.findall(r"""\{%\s*static\s+['"]([^'"]+)['"]\s*%\}""", path.read_text(errors="replace")):
            if finders.find(ref) is None:
                missing.append(f"{path.relative_to(_REPO_ROOT)}: {ref}")
    assert not missing, "static files that don't exist:\n" + "\n".join(missing)


def test_no_template_has_an_inline_style_block():
    """Page CSS lives in static/ (``<app>/css/templates/<template>.css`` for what
    used to be a template's <style> block), so it's cached, linted and shared.
    The framework's templates only: ``style-src`` allows inline styles, so a
    project's own <style> blocks break nothing."""
    offenders = hygiene.inline_styles(hygiene.framework_templates())
    assert not offenders, "inline <style> blocks (move them to static/; see templates.md):\n" + "\n".join(
        map(str, offenders)
    )


# -- what the inline-code sweeps cover --------------------------------------------------------------


def test_framework_templates_are_told_from_the_projects_own():
    root = hygiene.REPO_ROOT
    framework = [
        "apps/smallstack/templates/smallstack/base.html",
        "apps/blog/templates/blog/post.html",
        "apps/smallstack/templates/500.html",
        "apps/showcase/templates/showcase/starter.html",
        "templates/email/base_email.html",
    ]
    projects = [
        "apps/website/templates/website/x.html",
        "apps/call_stats/templates/call_stats/report.html",  # a downstream's own app
        "templates/website/home.html",
        "templates/404.html",  # a project's own error page, overriding the default
    ]
    assert all(hygiene.is_framework_template(root / p) for p in framework)
    assert not any(hygiene.is_framework_template(root / p) for p in projects)
    assert len(hygiene.framework_templates()) > 100  # negative control for the narrower sweep


def test_the_script_sweeps_follow_the_policy_in_force(settings):
    """Strict policy: every template, since an inline script anywhere is dead code.
    The 'unsafe-inline' stopgap: the framework's templates only, since a project's
    own inline scripts then run — and the framework must stay clean either way."""
    directives = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]

    def script_src(*sources: str) -> None:
        settings.CONTENT_SECURITY_POLICY = {"DIRECTIVES": {**directives, "script-src": list(sources)}}

    script_src("'self'")
    assert not hygiene.inline_script_allowed()
    assert set(hygiene.script_templates()) == set(hygiene.project_templates())
    script_src("'self'", "'unsafe-inline'")
    assert hygiene.inline_script_allowed()
    assert set(hygiene.script_templates()) == set(hygiene.framework_templates())


def test_the_scanners_find_what_they_should(tmp_path, monkeypatch, settings):
    monkeypatch.setattr(hygiene, "REPO_ROOT", tmp_path)
    page = tmp_path / "templates" / "page.html"
    page.parent.mkdir()
    page.write_text(
        '<script>run()</script>\n'
        '<script nonce="{{ request.csp_nonce }}">kept()</script>\n'
        '<script src="/static/a.js"></script>\n'
        '<script type="application/json">{"a": 1}</script>\n'
        '<button onclick="go()">x</button>\n'
        "<style>p {}</style>\n"
        "{% comment %}<style>q {}</style>{% endcomment %}\n"
    )
    # A nonce'd block is dead code unless script-src carries the nonce.
    assert [o.line for o in hygiene.inline_scripts([page])] == [1, 2]
    from csp.constants import NONCE

    directives = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]
    settings.CONTENT_SECURITY_POLICY = {"DIRECTIVES": {**directives, "script-src": ["'self'", NONCE]}}
    assert [o.line for o in hygiene.inline_scripts([page])] == [1]
    assert [o.line for o in hygiene.inline_handlers([page])] == [5]
    assert [o.line for o in hygiene.inline_styles([page])] == [6]


def test_the_command_lists_offenders_and_fails_its_check(tmp_path, monkeypatch):
    from io import StringIO

    from django.core.management import CommandError, call_command

    monkeypatch.setattr(hygiene, "REPO_ROOT", tmp_path)
    page = tmp_path / "apps" / "call_stats" / "templates" / "call_stats" / "report.html"
    page.parent.mkdir(parents=True)
    page.write_text('<script>run()</script>\n<a onclick="go()">x</a>\n')
    out = StringIO()
    call_command("template_hygiene", stdout=out)
    assert "apps/call_stats/templates/call_stats/report.html:1" in out.getvalue()
    assert "2 inline scripts and handlers in 1 files" in out.getvalue()
    with pytest.raises(CommandError):
        call_command("template_hygiene", "--check", stdout=StringIO())
    call_command("template_hygiene", "--framework", "--check", stdout=StringIO())  # not a framework template
