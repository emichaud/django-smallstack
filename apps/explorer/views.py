"""Explorer views."""

from django.urls import reverse
from django.views.generic import TemplateView
from django_tables2 import RequestConfig

from apps.smallstack.mixins import StaffRequiredMixin

from .registry import explorer_registry
from .tables import ExplorerModelTable


class ExplorerIndexView(StaffRequiredMixin, TemplateView):
    template_name = "explorer/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grouped = {}
        flat = []
        for group, infos in explorer_registry.get_grouped_models().items():
            grouped[group] = []
            for info in infos:
                entry = {
                    **info,
                    "count": info["model_class"].objects.count(),
                    "list_url": reverse(f"{info['url_base']}-list"),
                }
                grouped[group].append(entry)
                flat.append(entry)
        context["grouped_models"] = grouped
        context["models"] = flat

        # django-tables2 sortable table
        table = ExplorerModelTable(flat)
        RequestConfig(self.request, paginate=False).configure(table)
        context["table"] = table
        return context
