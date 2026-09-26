"""CRUD template robustness: empty-state rendering + related-tab overrides.

Two upstream issues found by reading the templates rather than by a failure:

1. `object_list_content.html` built its empty-state copy with
   `"No "|add:object_verbose_name_plural|add:"…"`. A filter *argument* that
   fails to resolve raises `VariableDoesNotExist` — unlike `{{ missing }}`,
   which quietly renders `string_if_invalid`. `_CRUDContextMixin` always
   supplies the variable, so nothing broke in-tree, but the partial is also
   included by hand-written list templates (usermanager does), which is exactly
   where a context can lack it.

2. `_CRUDRelatedTabBase` hardcoded its template while every sibling resolves
   through `_get_template_names(suffix)`, so the related-tab partial was the one
   CRUD surface a project could not override per model or per app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.template import engines
from django.template.loader import select_template
from django.test import override_settings

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

LIST_CONTENT = "smallstack/crud/object_list_content.html"


class _Cfg(CRUDView):
    model = APIToken
    list_fields = ["name"]
    url_base = "tmpl-tokens"
    actions = [Action.LIST]


def _render(context: dict) -> str:
    from django.template.loader import render_to_string

    return render_to_string(LIST_CONTENT, context)


# --------------------------------------------------------------------------
# 1. Empty state must not depend on a filter-argument variable
# --------------------------------------------------------------------------


def test_empty_state_renders_without_the_verbose_name_variable():
    """The regression: this used to raise VariableDoesNotExist.

    Copy now comes from the shared `crud/includes/empty_state.html` — this
    partial used to carry a fifth divergent version, so the same condition read
    "No matches" here and "Nothing matches these filters" on every other CRUD
    list (F-52). The noun fallback is still this partial's job.
    """
    html = _render({"object_list": []})
    assert "There are no records yet." in html


def test_empty_state_search_variant_renders_without_the_variable():
    html = _render({"object_list": [], "toolbar_search_query": "zzz"})
    assert "Nothing matches these filters." in html


def test_empty_state_still_uses_the_model_noun_when_present():
    """The fallback must not mask the real noun when the context supplies it."""
    html = _render({"object_list": [], "object_verbose_name_plural": "API tokens"})
    assert "There are no api tokens yet." in html
    assert "no records" not in html


def test_empty_state_copy_is_identical_to_every_other_crud_list():
    """The convergence claim, asserted rather than trusted.

    Both branches must render the shared include's exact sentences, so this
    partial cannot drift from object_list / object_list_partial / the displays.
    """
    from django.template.loader import render_to_string

    for ctx, extra in (
        ({"has_active_filters": True}, {"toolbar_search_query": "zzz"}),
        ({"has_active_filters": False}, {}),
    ):
        canonical = render_to_string(
            "smallstack/crud/includes/empty_state.html",
            {"object_verbose_name_plural": "records", **ctx},
        ).strip()
        mine = _render({"object_list": [], **extra})
        # The shared include's visible sentence must appear verbatim.
        sentence = " ".join(canonical.split())
        sentence = sentence[sentence.index(">") + 1 : sentence.rindex("<")].strip()
        assert " ".join(sentence.split()) in " ".join(mine.split()), (
            f"copy drifted from the shared include: {sentence!r}"
        )


def test_no_template_tag_spans_multiple_lines():
    """Sweep: a `{% %}` tag broken across lines is never parsed.

    Django's tokenizer uses `{%.*?%}` with no DOTALL, so a wrapped tag is not a
    tag — it is emitted as literal template source into the rendered page. Four
    empty states shipped that way (both CRUD list states, the dashboard, and the
    MCP tools admin), because `empty_state.html`'s own usage example was written
    wrapped and every caller copied it.

    This is a whole-tree sweep rather than a per-file test: the failure is
    invisible in review (the template looks fine) and only shows as raw markup
    on a page nobody looks at until it's empty.
    """
    import re

    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"\{%[^%]*?\n.*?%\}", re.S)
    skip = ("staticfiles", "htmlcov", ".venv", "node_modules")

    offenders = []
    for path in root.rglob("*.html"):
        if any(part in str(path) for part in skip):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            # A wrapped tag inside {% comment %} is inert prose, not a tag.
            before = text[: match.start()]
            if before.count("{% comment %}") > before.count("{% endcomment %}"):
                continue
            line = before.count("\n") + 1
            offenders.append(f"{path.relative_to(root)}:{line}")

    assert not offenders, "template tags split across lines (never parsed): " + ", ".join(offenders)


def test_filter_argument_variables_raise_when_unresolved():
    """Pins *why* the guard is needed, so the fallback isn't cargo-culted away.

    A missing variable in `{{ }}` renders empty; the same variable used as a
    filter argument raises. That asymmetry is the whole bug.
    """
    dj = engines["django"]
    assert dj.from_string("[{{ missing }}]").render({}) == "[]"
    with pytest.raises(Exception) as exc:
        dj.from_string('{{ "No "|add:missing }}').render({})
    assert "missing" in str(exc.value)


# --------------------------------------------------------------------------
# 2. Related-tab template is overridable like every other CRUD surface
# --------------------------------------------------------------------------


def test_related_tab_offers_the_same_override_chain_as_siblings():
    from apps.smallstack.crud import _CRUDRelatedTabBase

    view = _Cfg._make_view(_CRUDRelatedTabBase)()
    names = view.get_template_names()
    # app-level override, then the shipped default as the final fallback
    assert "smallstack/crud/apitoken_related_tab.html" in names
    assert names[-1] == "smallstack/crud/includes/related_tab_content.html"


def test_related_tab_still_resolves_to_the_shipped_partial_by_default():
    """No override present → identical behavior to the hardcoded path."""
    from apps.smallstack.crud import _CRUDRelatedTabBase

    view = _Cfg._make_view(_CRUDRelatedTabBase)()
    chosen = select_template(view.get_template_names())
    assert chosen.template.name == "smallstack/crud/includes/related_tab_content.html"


def test_an_app_level_override_wins(tmp_path):
    """End-to-end: dropping the conventional template in overrides the partial."""
    from apps.smallstack.crud import _CRUDRelatedTabBase

    override = tmp_path / "smallstack" / "crud" / "apitoken_related_tab.html"
    override.parent.mkdir(parents=True)
    override.write_text("OVERRIDDEN-RELATED-TAB", encoding="utf-8")

    from django.conf import settings

    templates = [dict(settings.TEMPLATES[0])]
    templates[0]["DIRS"] = [str(tmp_path), *templates[0].get("DIRS", [])]
    with override_settings(TEMPLATES=templates):
        from django.template import engines as _engines

        _engines._engines = {}  # drop cached engine so new DIRS take effect
        view = _Cfg._make_view(_CRUDRelatedTabBase)()
        chosen = select_template(view.get_template_names())
        assert Path(chosen.template.origin.name).read_text() == "OVERRIDDEN-RELATED-TAB"
    from django.template import engines as _engines2

    _engines2._engines = {}  # restore for subsequent tests
