"""``CRUDView.view_mixins`` and the HTML forms' ``user=`` kwarg.

``view_mixins`` is the supported way to customise one generated view: an
ordinary mixin placed after the auth mixins and before the generated base, so
it overrides and ``super()``s into the framework's behaviour. And the HTML
create/edit views now hand ``user=`` to a form that accepts it, the rule REST,
MCP and ``sc`` already followed through ``form_bridge.build_form``.
"""

from __future__ import annotations

from typing import Any

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.test import RequestFactory

from apps.smallstack.crud import (
    Action,
    CRUDView,
    _CRUDCreateBase,
    _CRUDDeleteBase,
    _CRUDListBase,
    _CRUDUpdateBase,
)


def _view(**attrs: Any) -> type[CRUDView]:
    return type("_TmpView", (CRUDView,), {"model": get_user_model(), "url_base": "tmp/vm", **attrs})


class _Marker:
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["marked"] = True
        return context


def test_mixin_lands_between_auth_and_the_generated_base() -> None:
    view = _view(view_mixins={Action.DELETE: [_Marker]})._make_view(_CRUDDeleteBase)
    mro = view.__mro__
    assert mro.index(LoginRequiredMixin) < mro.index(_Marker) < mro.index(_CRUDDeleteBase)


def test_mixin_applies_only_to_its_action() -> None:
    cfg = _view(view_mixins={Action.DELETE: [_Marker]})
    assert _Marker in cfg._make_view(_CRUDDeleteBase).__mro__
    for base in (_CRUDListBase, _CRUDCreateBase, _CRUDUpdateBase):
        assert _Marker not in cfg._make_view(base).__mro__


def test_no_view_mixins_by_default() -> None:
    view = _view()._make_view(_CRUDDeleteBase)
    assert view.__bases__ == (LoginRequiredMixin, _CRUDDeleteBase)


class _UserForm(forms.ModelForm):
    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        self.given_user = user
        super().__init__(*args, **kwargs)

    class Meta:
        model = get_user_model()
        fields = ["first_name"]


class _PlainForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name"]


@pytest.mark.django_db
@pytest.mark.parametrize(("form_class", "expects_user"), [(_UserForm, True), (_PlainForm, False)])
def test_html_create_form_gets_the_user_when_it_accepts_one(form_class: type, expects_user: bool) -> None:
    user = get_user_model().objects.create_user("vm-form", password="x")
    request = RequestFactory().get("/tmp/vm/new/")
    request.user = user
    view = _view(form_class=form_class)._make_view(_CRUDCreateBase)()
    view.setup(request)
    view.object = None
    kwargs = view.get_form_kwargs()
    assert ("user" in kwargs) is expects_user
    if expects_user:
        assert kwargs["user"] == user
        assert view.get_form().given_user == user
