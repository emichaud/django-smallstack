"""Notification views — the inbox, click-through mark-read, and mark-all-read.

LoginRequired, deliberately NOT staff-only: producers (e.g. approvals) may
notify non-staff users, and their inbox must work.
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from . import services
from .models import Notification


class InboxView(LoginRequiredMixin, ListView):
    """The user's own notifications, unread first within reverse-chron."""

    template_name = "notifications/inbox.html"
    context_object_name = "notifications"
    paginate_by = 25

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related("actor")


def open_notification(request: HttpRequest, pk: int) -> HttpResponse:
    """Click-through: mark THIS notification read, then follow its url.

    Recipient-scoped 404 (never leak another user's rows). The stored url is an
    internal path by contract; anything absolute or scheme-relative falls back
    to the inbox rather than becoming an open redirect.
    """
    if not request.user.is_authenticated:
        return redirect("login")
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    services.mark_read(request.user, ids=[notification.pk])
    url = notification.url
    if url.startswith("/") and not url.startswith("//"):
        return redirect(url)
    return redirect("notifications:inbox")


@require_POST
def mark_all_read(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return HttpResponse(status=403)
    services.mark_read(request.user)
    return redirect("notifications:inbox")
