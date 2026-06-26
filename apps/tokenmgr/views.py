"""Views for the Token Manager.

Self-service permissions:

- Authenticated user: lists / views / revokes their OWN tokens, mints
  readonly tokens for themselves.
- Staff: same as above, plus mints staff-level tokens, plus sees and
  manages all tokens.
- Superuser: same as staff, plus mints auth-level tokens.

The CRUDView's `get_list_queryset` enforces the row-level scoping; the
custom views (create / reveal / revoke / stats) enforce ownership via
the `is_owner_or_staff` helper.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.models import APIToken

from .forms import TokenCreateForm
from .mixins import is_owner_or_staff
from .stats import get_overview_stats, get_usage_stats

REVEAL_SESSION_KEY = "_tokenmgr_reveal_key"


# ---------------------------------------------------------------------------
# CRUDView for list + detail
# ---------------------------------------------------------------------------


class TokenCRUDView(CRUDView):
    model = APIToken
    actions = [Action.LIST, Action.DETAIL]
    # mixins is empty — we authenticate by hand in get_list_queryset / the
    # custom view classes so the LoginRequiredMixin can wrap everything
    # without forcing staff like the upstream package did.
    url_base = "tokens"
    namespace = "tokenmgr"
    list_fields = [
        "name",
        "prefix",
        "user",
        "token_type",
        "access_level",
        "is_active",
        "request_count",
        "last_used_at",
        "created_at",
    ]
    detail_fields = [
        "name",
        "description",
        "prefix",
        "user",
        "token_type",
        "access_level",
        "is_active",
        "expires_at",
        "revoked_at",
        "request_count",
        "last_used_at",
        "created_at",
    ]
    search_fields = ["name", "prefix"]
    filter_fields = ["is_active", "user", "token_type", "access_level"]

    # Opted into the unified search index by default. Same search_fields
    # already drive the list-page search box; opting in lights up the
    # global /smallstack/search/ page, the topbar omnibar, and an MCP
    # `search_api_tokens` tool Claude can call.
    enable_search = True
    search_display = "name"
    search_subtitle = "prefix"
    paginate_by = 20
    link_field = "name"

    @classmethod
    def _get_template_names(cls, suffix):
        if suffix == "list":
            return ["tokenmgr/crud/apitoken_list.html"]
        if suffix == "list_content":
            # Toolbar HTMX (search / filter changes) returns just this
            # fragment — replaces #crud-list-content innerHTML without
            # re-rendering the page header, stat cards, or toolbar.
            return ["tokenmgr/crud/apitoken_list_content.html"]
        if suffix == "list_partial":
            # Fallback when an HTMX request doesn't target the list-
            # content div. Re-render the whole page block.
            return ["tokenmgr/crud/apitoken_list.html"]
        if suffix == "detail":
            return ["tokenmgr/crud/apitoken_detail.html"]
        return super()._get_template_names(suffix)

    @classmethod
    def get_list_queryset(cls, qs, request):
        """Filter to the requester's tokens when they're not staff.

        Defaults to active-only on landings without an `is_active` query
        param. Explicit choices in the toolbar — `?is_active=` (empty,
        i.e. "All"), `?is_active=true`, `?is_active=false` — bypass the
        default and let `_apply_list_filters` handle the filter itself.
        """
        qs = qs.select_related("user")
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return qs.none()
        if not request.user.is_staff:
            qs = qs.filter(user=request.user)
        # Hide revoked tokens by default. Users opt into them via the
        # Is Active dropdown ("All" or "No").
        if "is_active" not in request.GET:
            qs = qs.filter(is_active=True)
        return qs

    @classmethod
    def _make_view(cls, base_class):
        view_class = super()._make_view(base_class)
        from apps.smallstack.crud import _CRUDDetailBase, _CRUDListBase

        # Inject auth + per-view extras around the generated CRUDView class.
        original_dispatch = view_class.dispatch

        def dispatch(self, request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.decorators import login_required

                return login_required(view_class.as_view())(request, *args, **kwargs)
            return original_dispatch(self, request, *args, **kwargs)

        view_class.dispatch = dispatch

        if base_class is _CRUDListBase:
            original_get_context = view_class.get_context_data

            def get_context_data(self, **kwargs):
                context = original_get_context(self, **kwargs)
                context["overview_stats"] = get_overview_stats(self.request.user)
                # Mirror the queryset default: when is_active is absent
                # from the GET params, pre-select "Yes" in the dropdown
                # so the UI matches what the user is actually seeing.
                if "is_active" not in self.request.GET:
                    for f in context.get("toolbar_filters", []):
                        if f.get("name") == "is_active":
                            f["current_value"] = "true"
                            break
                return context

            view_class.get_context_data = get_context_data

        elif base_class is _CRUDDetailBase:
            original_get_context = view_class.get_context_data
            original_get_object = view_class.get_object

            def get_object(self, *args, **kwargs):
                obj = original_get_object(self, *args, **kwargs)
                # Even though get_list_queryset scopes the list, the detail
                # url accepts a direct pk — re-enforce ownership here.
                if not is_owner_or_staff(self.request.user, obj):
                    raise PermissionDenied
                return obj

            def get_context_data(self, **kwargs):
                context = original_get_context(self, **kwargs)
                context["token_stats"] = get_usage_stats(self.object, hours=24)
                context["selected_hours"] = 24
                return context

            view_class.get_object = get_object
            view_class.get_context_data = get_context_data

        return view_class


# ---------------------------------------------------------------------------
# Custom views
# ---------------------------------------------------------------------------


class TokenCreateView(LoginRequiredMixin, FormView):
    template_name = "tokenmgr/token_create.html"
    form_class = TokenCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        token, raw_key = APIToken.create_token(
            user=form.cleaned_data["user"],
            name=form.cleaned_data["name"],
            description=form.cleaned_data.get("description", ""),
            expires_at=form.cleaned_data.get("expires_at"),
            token_type="manual",
            access_level=form.cleaned_data["access_level"],
        )
        # One-shot reveal — stashed in session so a refresh of the reveal
        # page can't re-expose the key.
        self.request.session[REVEAL_SESSION_KEY] = raw_key
        return redirect(reverse("tokenmgr:token-reveal", kwargs={"pk": token.pk}))


class TokenRevealView(LoginRequiredMixin, TemplateView):
    template_name = "tokenmgr/token_reveal.html"

    def get(self, request, pk):
        token = get_object_or_404(APIToken, pk=pk)
        if not is_owner_or_staff(request.user, token):
            raise PermissionDenied
        raw_key = request.session.pop(REVEAL_SESSION_KEY, None)
        if not raw_key:
            messages.warning(
                request,
                "Token key is no longer available. The raw key is only shown once at creation.",
            )
            return redirect(reverse("tokenmgr:tokens-list"))
        return self.render_to_response(self.get_context_data(token=token, raw_key=raw_key))


class TokenRevokeView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        token = get_object_or_404(APIToken, pk=pk)
        if not is_owner_or_staff(request.user, token):
            raise PermissionDenied
        if token.is_active:
            token.revoke()
            messages.success(request, f'Token "{token.name}" has been revoked.')
        else:
            messages.info(request, f'Token "{token.name}" was already inactive.')
        return redirect(reverse("tokenmgr:tokens-list"))


class TokenStatsView(LoginRequiredMixin, TemplateView):
    template_name = "tokenmgr/includes/stats_cards.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        token = get_object_or_404(APIToken, pk=self.kwargs["pk"])
        if not is_owner_or_staff(self.request.user, token):
            raise PermissionDenied
        try:
            hours = int(self.request.GET.get("hours", 24))
        except (TypeError, ValueError):
            hours = 24
        hours = max(1, min(hours, 24 * 30))
        context["token"] = token
        context["stats"] = get_usage_stats(token, hours=hours)
        context["selected_hours"] = hours
        return context


def _token_list_row(token, meta) -> str:
    """A clickable token row for the stat modal: avatar · name · meta · chevron."""
    return format_html(
        '<a class="stat-list-row" href="{}">'
        '<span class="stat-list-avatar" aria-hidden="true">{}</span>'
        '<span class="stat-list-name">{}</span>'
        '<span class="stat-list-meta">{}</span>'
        '<span class="stat-list-chevron" aria-hidden="true">→</span>'
        "</a>",
        reverse("tokenmgr:tokens-detail", kwargs={"pk": token.pk}),
        (token.name[:2] or "?").upper(),
        token.name,
        meta,
    )


@login_required
def token_stat_detail(request, stat_type: str) -> HttpResponse:
    """HTMX endpoint returning HTML for the token stat-card drill-down modals.

    Respects self-service scoping: non-staff callers only ever see their own
    tokens (same rule as the overview counts).
    """
    user = request.user
    is_staff = bool(getattr(user, "is_staff", False))
    qs = APIToken.objects.select_related("user").order_by("-created_at")
    if not is_staff:
        qs = qs.filter(user=user)

    def _meta(token) -> str:
        # Staff see the owner; an owner viewing their own tokens sees the
        # access level + key prefix instead (owner would be redundant).
        if is_staff and token.user:
            return str(token.user)
        return f"{token.access_level or 'staff'} · {token.prefix}…"

    rows: list = []
    empty_msg = "Nothing to show."

    if stat_type == "total":
        rows = [_token_list_row(t, _meta(t)) for t in qs]
        empty_msg = "No tokens yet."
    elif stat_type == "active":
        rows = [_token_list_row(t, _meta(t)) for t in qs.filter(is_active=True)]
        empty_msg = "No active tokens."
    elif stat_type == "revoked":
        rows = [_token_list_row(t, _meta(t)) for t in qs.filter(is_active=False)]
        empty_msg = "No revoked tokens."
    elif stat_type == "volume":
        empty_msg = "No API requests in the last 24 hours."
        try:
            from apps.activity.models import RequestLog

            cutoff = timezone.now() - timezone.timedelta(hours=24)
            counts = dict(
                RequestLog.objects.filter(api_token__in=qs, timestamp__gte=cutoff)
                .values_list("api_token")
                .annotate(c=Count("id"))
            )
            tokens_by_id = {t.pk: t for t in qs}
            rows = [
                format_html(
                    '<a class="stat-list-row" href="{}">'
                    '<span class="stat-list-avatar" aria-hidden="true">{}</span>'
                    '<span class="stat-list-name">{}</span>'
                    '<span class="stat-list-count">{}</span>'
                    '<span class="stat-list-chevron" aria-hidden="true">→</span>'
                    "</a>",
                    reverse("tokenmgr:tokens-detail", kwargs={"pk": tid}),
                    (tokens_by_id[tid].name[:2] or "?").upper(),
                    tokens_by_id[tid].name,
                    cnt,
                )
                for tid, cnt in sorted(counts.items(), key=lambda kv: -kv[1])
                if tid in tokens_by_id
            ]
        except Exception:  # noqa: BLE001 — activity app optional / any query failure → empty
            rows = []

    if rows:
        body = format_html('<div class="stat-list">{}</div>', format_html_join("", "{}", ((r,) for r in rows)))
    else:
        body = format_html('<p class="stat-list-empty">{}</p>', empty_msg)
    return HttpResponse(body)
