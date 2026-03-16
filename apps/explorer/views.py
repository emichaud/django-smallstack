"""Explorer views."""

from django.views.generic import TemplateView
from django_tables2 import RequestConfig

from apps.smallstack.mixins import StaffRequiredMixin

from .mixins import ExplorerAppMixin, ExplorerGroupMixin, ExplorerModelMixin
from .registry import explorer
from .tables import ExplorerModelTable


class ExplorerIndexView(StaffRequiredMixin, TemplateView):
    template_name = "explorer/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        flat = [info.with_counts() for info in explorer.get_models()]
        context["models"] = flat
        context["models_az"] = sorted(flat, key=lambda m: m.verbose_name_plural.lower())

        # Sidebar data: groups and apps
        grouped = explorer.get_grouped_models()
        context["all_groups"] = sorted(grouped.keys())
        apps = {}
        for info in explorer.get_models():
            if info.app_label not in apps:
                apps[info.app_label] = info.app_label.replace("_", " ").title()
        context["all_apps"] = sorted(apps.items())  # list of (app_label, verbose_name)

        # Active sidebar selection from query params
        context["active_group"] = self.request.GET.get("group", "")
        context["active_app"] = self.request.GET.get("app", "")
        context["sidebar_mode"] = self.request.GET.get("by", "group")

        # Filter models if a group or app is selected
        active_group = context["active_group"]
        active_app = context["active_app"]
        if active_group:
            flat = [m for m in flat if m.group == active_group]
        elif active_app:
            flat = [m for m in flat if m.app_label == active_app]
        context["filtered_models"] = sorted(flat, key=lambda m: m.verbose_name_plural.lower())
        context["total_records"] = sum(m.count for m in context["filtered_models"])

        return context


class ExplorerClassicIndexView(StaffRequiredMixin, TemplateView):
    """Example: the original Explorer index with grid/list toggle and grouping."""

    template_name = "explorer/examples/classic_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        flat = [info.with_counts() for info in explorer.get_models()]
        context["models"] = flat
        context["models_az"] = sorted(flat, key=lambda m: m.verbose_name_plural.lower())

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
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

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


class ExplorerHeartbeatPageView(ExplorerModelMixin, StaffRequiredMixin, TemplateView):
    """Example: composable page mixing Explorer CRUD with custom visuals."""

    template_name = "explorer/examples/heartbeat_page.html"
    explorer_app_label = "heartbeat"
    explorer_model_name = "heartbeat"
    paginate_by = 7

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            from apps.heartbeat.models import HeartbeatDaily

            context["chart_days"] = HeartbeatDaily.get_daily_summary(days=7)
        except ImportError:
            context["chart_days"] = []

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
