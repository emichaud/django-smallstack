"""Template tags — kind-card resolution order and the downstream embed."""

from __future__ import annotations

import pytest
from django.template import Context, Template

from apps.approvals import services
from apps.approvals.registry import ApprovalKind, register_kind, unregister
from apps.approvals.templatetags.approvals_tags import _kind_templates

pytestmark = pytest.mark.django_db


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


def _render(source: str, **ctx) -> str:
    return Template("{% load approvals_tags %}" + source).render(Context(ctx))


# --- resolution order --------------------------------------------------------


def test_kind_template_resolution_order(requester, sample_kind):
    req = _file(requester)
    # no explicit context_template → key-derived name, then default
    assert _kind_templates(req) == [
        "approvals/kinds/test-sample.html",
        "approvals/kinds/default.html",
    ]

    register_kind(
        ApprovalKind(key="test.explicit", context_template="myapp/custom_card.html")
    )
    try:
        explicit = _file(requester, kind="test.explicit")
        assert _kind_templates(explicit)[0] == "myapp/custom_card.html"
    finally:
        unregister("test.explicit")


def test_context_card_renders_default_with_pretty_json(requester, sample_kind):
    req = _file(requester, context={"events": 9})
    html = _render("{% approval_context req %}", req=req)
    assert "&quot;events&quot;: 9" in html or '"events": 9' in html


def test_downstream_kind_card_override_wins(requester, sample_kind, settings, tmp_path):
    """A ``approvals/kinds/<key>.html`` in a project template dir shadows the
    default card — the documented downstream customization path."""
    (tmp_path / "approvals" / "kinds").mkdir(parents=True)
    (tmp_path / "approvals" / "kinds" / "test-sample.html").write_text(
        "CARD-MARKER {{ context.events }} of {{ req.title }}"
    )
    settings.TEMPLATES = [
        {**settings.TEMPLATES[0], "DIRS": [str(tmp_path), *settings.TEMPLATES[0]["DIRS"]]}
    ]
    req = _file(requester, context={"events": 4})
    html = _render("{% approval_context req %}", req=req)
    assert "CARD-MARKER 4 of Do the thing" in html


# --- the embed ---------------------------------------------------------------


def test_approval_card_shows_actions_only_when_eligible(requester, staff, bystander, sample_kind, rf):
    req = _file(requester)

    def render_for(user):
        request = rf.get("/")
        request.user = user
        return _render("{% approval_card req %}", req=req, request=request)

    assert 'name="decision"' in render_for(staff)
    assert 'name="decision"' not in render_for(bystander)
    assert req.title in render_for(bystander)  # card still renders read-only


def test_eligibility_simple_tags(requester, staff, sample_kind):
    req = _file(requester)
    out = _render(
        "{% approval_can_decide user req as d %}{{ d }}|"
        "{% approval_can_cancel user req as c %}{{ c }}",
        user=staff, req=req,
    )
    assert out == "True|True"
