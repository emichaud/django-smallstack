"""Regression tests for CRUDView related tabs (`_CRUDRelatedTabBase.get()`).

Two upstream bugs, both reported from a downstream project and both reproducible
in framework code alone:

1. `crud_actions` was hardcoded to `[Action.DETAIL]`. `{% crud_table %}` then
   reversed "<url_base>-detail" for the *related* view — a route that only
   exists when that view's `actions` include DETAIL (see `CRUDView.get_urls`).
   Any related tab whose target omits DETAIL raised NoReverseMatch → 500, so
   the tab body never populated. Several bundled views omit DETAIL today
   (usermanager, heartbeat endpoints, the scheduler run view), so this was
   latent upstream rather than theoretical.

2. `crud_config` stayed the PARENT's config. `{% crud_table %}` reads
   `row_link_url()`, `row_actions()` and `column_widths` off it, so child rows
   were rendered through parent hooks — a parent that redirects its row links
   would silently point a child row at an unrelated record with the same pk.
   This one fails silently, which makes it the more dangerous of the two.

Exactly ONE action is forwarded — row-link intent and nothing more. A tab whose
target routes both DETAIL and UPDATE must not gain an Edit column it never had
(`test_no_action_column_when_related_view_routes_both`).

Accepted side effect, pinned by `test_row_link_falls_back_to_the_edit_url`:
for a related view *without* DETAIL, rows fall back to the edit URL, which makes
`show_actions` true and surfaces an Edit control. That is the same destination
the row itself points at, and the only way to reach the record from the tab.
DELETE is never forwarded, so a related tab cannot become a destructive
surface — `test_delete_is_never_forwarded` pins that.
"""

import types

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings

from apps.smallstack.crud import Action, CRUDView, _CRUDRelatedTabBase
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

ACCESSOR = "api_tokens"  # APIToken.user related_name


def _child(actions, **extra):
    """A CRUDView for APIToken routing exactly `actions`."""
    return type(
        "StubTokenCRUD",
        (CRUDView,),
        {
            "model": APIToken,
            "list_fields": ["name"],
            "url_base": "stub-tokens",
            "public": True,
            "actions": actions,
            **extra,
        },
    )


def _parent(**extra):
    """A CRUDView for User; needs DETAIL so the related-tab route exists."""
    return type(
        "StubUserCRUD",
        (CRUDView,),
        {
            "model": get_user_model(),
            "list_fields": ["username"],
            "url_base": "stub-users",
            "public": True,
            "actions": [Action.LIST, Action.DETAIL],
            **extra,
        },
    )


def _urlconf(*views):
    module = types.ModuleType("stub_related_tab_urls")
    module.urlpatterns = [p for view in views for p in view.get_urls()]
    return module


def _render_tab(parent, child, user):
    """Drive the real related-tab view and return its (unrendered) response."""
    urlconf = _urlconf(parent, child)
    previous = CRUDView._registry.get(APIToken)
    CRUDView._registry[APIToken] = child  # so _get_related_tabs resolves to the stub
    try:
        with override_settings(ROOT_URLCONF=urlconf):
            request = RequestFactory().get("/")
            request.user = user
            view = parent._make_view(_CRUDRelatedTabBase).as_view()
            response = view(request, pk=user.pk, accessor=ACCESSOR)
            response.render()  # reversing happens here — where bug 1 blew up
            return response
    finally:
        if previous is not None:
            CRUDView._registry[APIToken] = previous
        else:
            CRUDView._registry.pop(APIToken, None)


@pytest.fixture
def user_with_token(db):
    user = get_user_model().objects.create_user(username="tabowner", password="x")
    APIToken.create_token(user=user, name="tab-token", token_type="manual", access_level="read")
    return user


# --------------------------------------------------------------------------
# Bug 1 — crud_actions must reflect what the related view actually routes
# --------------------------------------------------------------------------


def test_detail_is_forwarded_when_the_related_view_routes_it(user_with_token):
    child = _child([Action.LIST, Action.DETAIL])
    response = _render_tab(_parent(), child, user_with_token)
    assert response.context_data["crud_actions"] == [Action.DETAIL]


def test_crud_actions_falls_back_to_update_without_detail(user_with_token):
    child = _child([Action.LIST, Action.UPDATE])
    response = _render_tab(_parent(), child, user_with_token)
    assert response.context_data["crud_actions"] == [Action.UPDATE]


def test_crud_actions_empty_when_related_view_routes_neither(user_with_token):
    child = _child([Action.LIST])
    response = _render_tab(_parent(), child, user_with_token)
    assert response.context_data["crud_actions"] == []


def test_delete_is_never_forwarded(user_with_token):
    """A related tab is a read/navigate surface — never a destructive one."""
    child = _child([Action.LIST, Action.DETAIL, Action.UPDATE, Action.DELETE])
    response = _render_tab(_parent(), child, user_with_token)
    actions = response.context_data["crud_actions"]
    assert Action.DELETE not in actions
    assert "/delete" not in response.content.decode()


def test_no_action_column_when_related_view_routes_both(user_with_token):
    """Only row-link intent is forwarded — never a second, action-bearing entry.

    The default CRUDView routes all five actions, so forwarding both DETAIL and
    UPDATE would flip crud_table's `show_actions` and grow an Edit column on
    every related tab in every downstream project — a UI change the tab never
    had while crud_actions was hardcoded to [DETAIL].
    """
    child = _child([Action.LIST, Action.DETAIL, Action.UPDATE, Action.DELETE])
    response = _render_tab(_parent(), child, user_with_token)
    assert response.context_data["crud_actions"] == [Action.DETAIL]
    body = response.content.decode()
    assert "/edit" not in body
    assert "Actions" not in body


def test_related_tab_renders_when_related_view_has_no_detail_route(user_with_token):
    """The reported 500: no DETAIL action => no "-detail" route to reverse."""
    child = _child([Action.LIST, Action.UPDATE])
    response = _render_tab(_parent(), child, user_with_token)
    assert response.status_code == 200
    assert "tab-token" in response.content.decode()


def test_row_link_falls_back_to_the_edit_url(user_with_token):
    """Documents the accepted side effect: rows link to edit when detail is absent."""
    child = _child([Action.LIST, Action.UPDATE])
    response = _render_tab(_parent(), child, user_with_token)
    token_pk = APIToken.objects.get(name="tab-token").pk
    assert f"stub-tokens/{token_pk}/edit" in response.content.decode()


# --------------------------------------------------------------------------
# Bug 2 — crud_config must be the related view, not the parent
# --------------------------------------------------------------------------


def test_crud_config_is_the_related_view_not_the_parent(user_with_token):
    parent, child = _parent(), _child([Action.LIST, Action.DETAIL])
    response = _render_tab(parent, child, user_with_token)
    assert response.context_data["crud_config"] is child
    assert response.context_data["crud_config"] is not parent


def test_parent_row_link_hook_is_not_applied_to_child_rows(user_with_token):
    """The silent bug: a parent hook rewrote child row links to unrelated records."""

    class ParentWithHook:
        @classmethod
        def row_link_url(cls, obj, request):
            return f"/parent-hook/{obj.pk}/"

    parent = _parent(row_link_url=ParentWithHook.row_link_url)
    child = _child([Action.LIST, Action.DETAIL])
    response = _render_tab(parent, child, user_with_token)
    body = response.content.decode()
    assert "/parent-hook/" not in body
    token_pk = APIToken.objects.get(name="tab-token").pk
    assert f"stub-tokens/{token_pk}/" in body
