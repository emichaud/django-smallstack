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
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()

# Repo root: apps/smallstack/test_template_hygiene.py → ../../
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "staticfiles",
    "htmlcov",
    "site-packages",
    "__pycache__",
}


def _project_templates() -> list[Path]:
    found = []
    for path in _REPO_ROOT.rglob("*.html"):
        if _SKIP_DIRS & set(path.parts):
            continue
        found.append(path)
    return found


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
