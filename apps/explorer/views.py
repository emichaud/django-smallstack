"""Explorer views."""

import datetime

from django.utils import timezone
from django.views.generic import TemplateView
from django_tables2 import RequestConfig

from apps.smallstack.mixins import StaffRequiredMixin

from .mixins import ExplorerAppMixin, ExplorerGroupMixin, ExplorerModelMixin
from .registry import explorer_registry
from .tables import ExplorerModelTable


class ExplorerIndexView(StaffRequiredMixin, TemplateView):
    template_name = "explorer/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        flat = [info.with_counts() for info in explorer_registry.get_models()]
        context["models"] = flat
        context["models_az"] = sorted(flat, key=lambda m: m.verbose_name_plural.lower())

        # django-tables2 for sortable list view with paging
        table = ExplorerModelTable(flat)
        RequestConfig(self.request, paginate={"per_page": 25}).configure(table)
        context["table"] = table
        return context


# ---------------------------------------------------------------------------
# Composability examples — show developers how to embed Explorer into pages
# ---------------------------------------------------------------------------


class ExplorerGroupPageView(ExplorerGroupMixin, StaffRequiredMixin, TemplateView):
    """Example: a page showing all models from a single group."""

    template_name = "explorer/examples/group_page.html"


class ExplorerAppPageView(ExplorerAppMixin, StaffRequiredMixin, TemplateView):
    """Example: a page showing all models from a single Django app."""

    template_name = "explorer/examples/app_page.html"


class ExplorerSingleModelPageView(ExplorerModelMixin, StaffRequiredMixin, TemplateView):
    """Example: a standalone CRUD list page for one model."""

    template_name = "explorer/examples/single_model_page.html"


class ExplorerHeartbeatPageView(ExplorerModelMixin, StaffRequiredMixin, TemplateView):
    """Example: composable page mixing Explorer CRUD with custom visuals."""

    template_name = "explorer/examples/heartbeat_page.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
    paginate_by = 7

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Build 7-day chart data from HeartbeatDaily
        today = timezone.localdate()
        days = []
        try:
            from apps.heartbeat.models import HeartbeatDaily

            for i in range(6, -1, -1):
                day = today - datetime.timedelta(days=i)
                try:
                    daily = HeartbeatDaily.objects.get(date=day)
                    days.append({
                        "label": day.strftime("%a"),
                        "date": day.isoformat(),
                        "ok": daily.ok_count,
                        "fail": daily.fail_count,
                    })
                except HeartbeatDaily.DoesNotExist:
                    days.append({
                        "label": day.strftime("%a"),
                        "date": day.isoformat(),
                        "ok": 0,
                        "fail": 0,
                    })
        except ImportError:
            pass

        context["chart_days"] = days

        # Paginate the CRUD table
        from django.core.paginator import Paginator

        qs = context.get("object_list")
        if qs is not None:
            paginator = Paginator(qs, self.paginate_by)
            page_number = self.request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)
            context["object_list"] = page_obj.object_list
            context["page_obj"] = page_obj
            context["paginator"] = paginator
            context["page_range"] = paginator.get_elided_page_range(
                page_obj.number, on_each_side=2, on_ends=1
            )

        return context
