"""Reusable view mixins for SmallStack."""

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin that restricts access to staff users.

    If the user is authenticated but not staff, raises 403 instead of
    redirecting to the login page (which is confusing when already logged in).
    """

    def test_func(self) -> bool:
        return self.request.user.is_staff

    def handle_no_permission(self) -> HttpResponse:
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()


def staff_required(
    view_func: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    """Function-view counterpart to :class:`StaffRequiredMixin`.

    Returns a 403 for **any** non-staff caller — including anonymous users —
    rather than redirecting to login. These endpoints are typically htmx/XHR
    or POST handlers where a login redirect is useless to the caller, so a
    flat 403 is the correct response.
    """

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not request.user.is_staff:
            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)

    return _wrapped
