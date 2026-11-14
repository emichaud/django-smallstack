"""Secure-by-default CRUDView auth (F6).

An unset ``mixins`` requires login; ``public = True`` (or an explicit
``mixins = []``) opts into anonymous access; an explicit ``mixins`` list always
wins. A public view that still exposes write actions is warned about.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin


def _view(**attrs):
    """A throwaway CRUDView subclass (not registered as the User view — the
    registry is first-wins, so the real usermanager view keeps its slot)."""
    return type("_TmpView", (CRUDView,), {"model": get_user_model(), "url_base": "tmp/v", **attrs})


def test_unset_mixins_requires_login():
    assert _view()._resolved_mixins() == [LoginRequiredMixin]


def test_public_flag_is_anonymous():
    assert _view(public=True)._resolved_mixins() == []


def test_explicit_empty_mixins_is_anonymous():
    assert _view(mixins=[])._resolved_mixins() == []


def test_explicit_mixins_always_win():
    assert _view(mixins=[StaffRequiredMixin])._resolved_mixins() == [StaffRequiredMixin]


def test_public_flag_ignored_when_mixins_explicit():
    # An explicit list wins even if `public=True` is also (contradictorily) set.
    assert _view(public=True, mixins=[StaffRequiredMixin])._resolved_mixins() == [StaffRequiredMixin]


def test_generated_view_inherits_loginrequired_by_default():
    from apps.smallstack.crud import _CRUDListBase

    view_cls = _view()._make_view(_CRUDListBase)
    assert LoginRequiredMixin in view_cls.__mro__


def test_public_with_write_actions_warns():
    v = _view(public=True, enable_api=True, actions=[Action.LIST, Action.CREATE])
    with pytest.warns(UserWarning, match="anonymous writes"):
        from apps.smallstack.api import build_api_urls

        build_api_urls(v)


def test_public_readonly_does_not_warn(recwarn):
    v = _view(public=True, enable_api=True, actions=[Action.LIST, Action.DETAIL])
    from apps.smallstack.api import build_api_urls

    build_api_urls(v)
    assert not any("anonymous writes" in str(w.message) for w in recwarn.list)
