"""Reusable CRUD library for SmallStack.

Generates Django generic CBVs + URL patterns from a single config class.

Usage:
    from apps.smallstack.crud import CRUDView, Action
    from apps.smallstack.mixins import StaffRequiredMixin

    class UserCRUDView(CRUDView):
        model = User
        fields = ["username", "email", "first_name", "last_name"]
        list_fields = ["username", "email"]
        url_base = "manage/users"
        paginate_by = 25
        mixins = [StaffRequiredMixin]

    # In urls.py:
    urlpatterns = [
        *UserCRUDView.get_urls(),
    ]
"""

import enum

from django import forms
from django.urls import path, reverse
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)


class Action(enum.Enum):
    LIST = "list"
    CREATE = "create"
    DETAIL = "detail"
    UPDATE = "update"
    DELETE = "delete"


# ---------------------------------------------------------------------------
# Internal base view classes
# ---------------------------------------------------------------------------


class _CRUDContextMixin:
    """Injects CRUD metadata into template context for all generated views."""

    crud_config = None  # Set by CRUDView._make_view()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cfg = self.crud_config
        url_base = cfg._get_url_base()
        meta = cfg.model._meta
        context.update(
            {
                "object_verbose_name": str(meta.verbose_name).capitalize(),
                "object_verbose_name_plural": str(meta.verbose_name_plural).capitalize(),
                "url_base": url_base,
                "list_fields": cfg._get_list_fields(),
                "detail_fields": cfg._get_detail_fields(),
                "link_field": cfg._get_link_field(),
                "crud_actions": cfg.actions,
                "field_formatters": cfg.field_formatters,
            }
        )
        if Action.CREATE in cfg.actions:
            context["create_view_url"] = reverse(f"{url_base}-create")
        if Action.LIST in cfg.actions:
            context["list_view_url"] = reverse(f"{url_base}-list")
            context["list_view_url_name"] = f"{url_base}-list"
        return context


class _CRUDListBase(_CRUDContextMixin, ListView):
    def get_template_names(self):
        return self.crud_config._get_template_names("list")

    def get_queryset(self):
        return self.crud_config._get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cfg = self.crud_config

        # django-tables2 integration: if table_class is set, build and configure it
        if cfg.table_class:
            from django_tables2 import RequestConfig

            table = cfg.table_class(self.get_queryset())
            paginate = {"per_page": cfg.paginate_by} if cfg.paginate_by else False
            RequestConfig(self.request, paginate=paginate).configure(table)
            context["table"] = table
            context["use_tables2"] = True
        else:
            # Enhance page_obj with SmallStack pagination display helpers
            page_obj = context.get("page_obj")
            if page_obj:
                page_obj.showing_start = page_obj.start_index()
                page_obj.showing_end = page_obj.end_index()
                page_obj.total_count = page_obj.paginator.count
                page_obj.page_range_display = page_obj.paginator.get_elided_page_range(
                    page_obj.number, on_each_side=2, on_ends=1
                )
        return context


class _CRUDDetailBase(_CRUDContextMixin, DetailView):
    def get_template_names(self):
        return self.crud_config._get_template_names("detail")

    def get_queryset(self):
        return self.crud_config._get_queryset()


class _CRUDCreateBase(_CRUDContextMixin, CreateView):
    def get_template_names(self):
        return self.crud_config._get_template_names("form")

    def get_form_class(self):
        return self.crud_config.form_class or self.crud_config._make_form_class()

    def get_success_url(self):
        url_base = self.crud_config._get_url_base()
        return reverse(f"{url_base}-list")


class _CRUDUpdateBase(_CRUDContextMixin, UpdateView):
    def get_template_names(self):
        return self.crud_config._get_template_names("form")

    def get_queryset(self):
        return self.crud_config._get_queryset()

    def get_form_class(self):
        return self.crud_config.form_class or self.crud_config._make_form_class()

    def get_success_url(self):
        url_base = self.crud_config._get_url_base()
        return reverse(f"{url_base}-detail", kwargs={"pk": self.object.pk})


class _CRUDDeleteBase(_CRUDContextMixin, DeleteView):
    def get_template_names(self):
        return self.crud_config._get_template_names("confirm_delete")

    def get_queryset(self):
        return self.crud_config._get_queryset()

    def get_success_url(self):
        url_base = self.crud_config._get_url_base()
        return reverse(f"{url_base}-list")


# ---------------------------------------------------------------------------
# CRUDView configuration class
# ---------------------------------------------------------------------------


class CRUDView:
    """Configuration class that generates CRUD views and URL patterns.

    Attributes:
        model:            Django model class (required)
        fields:           Form fields for create/update (required)
        list_fields:      Columns shown in list table (defaults to fields)
        detail_fields:    Fields shown in detail view (defaults to fields)
        link_field:       Which column links to detail (defaults to first list_field)
        url_base:         URL prefix, e.g. "manage/users" (defaults to model_name)
        paginate_by:      Items per page (None = no pagination)
        mixins:           Auth mixins applied to all generated views
        actions:          Which CRUD actions to generate (default: all 5)
        form_class:       Custom ModelForm (auto-generated if None)
        queryset:         Custom queryset (model.objects.all() if None)
        field_formatters: {field_name: lambda value, obj: str} display formatters
        table_class:      Optional django-tables2 Table class for sortable list view
    """

    model = None
    fields = None
    list_fields = None
    detail_fields = None
    link_field = None
    url_base = None
    paginate_by = None
    mixins = []
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    form_class = None
    queryset = None
    field_formatters = {}
    table_class = None  # Optional django-tables2 Table class for enhanced list view

    @classmethod
    def _get_url_base(cls):
        if cls.url_base:
            return cls.url_base
        return cls.model._meta.model_name

    @classmethod
    def _get_list_fields(cls):
        return cls.list_fields or cls.fields

    @classmethod
    def _get_detail_fields(cls):
        return cls.detail_fields or cls.fields

    @classmethod
    def _get_link_field(cls):
        if cls.link_field:
            return cls.link_field
        list_fields = cls._get_list_fields()
        return list_fields[0] if list_fields else None

    @classmethod
    def _get_queryset(cls):
        if cls.queryset is not None:
            return cls.queryset.all()
        return cls.model.objects.all()

    @classmethod
    def _get_template_names(cls, suffix):
        """Return template list: app-specific override first, then default."""
        app_label = cls.model._meta.app_label
        model_name = cls.model._meta.model_name
        return [
            f"{app_label}/{model_name}_{suffix}.html",
            f"smallstack/crud/object_{suffix}.html",
        ]

    @classmethod
    def _make_form_class(cls):
        """Auto-generate a ModelForm with vTextField styling."""
        _model = cls.model
        _fields = cls.fields

        class AutoCRUDForm(forms.ModelForm):
            class Meta:
                model = _model
                fields = _fields

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                for field in self.fields.values():
                    widget = field.widget
                    if isinstance(
                        widget,
                        (
                            forms.TextInput,
                            forms.EmailInput,
                            forms.URLInput,
                            forms.NumberInput,
                            forms.PasswordInput,
                            forms.Textarea,
                        ),
                    ):
                        widget.attrs.setdefault("class", "vTextField")

        return AutoCRUDForm

    @classmethod
    def _make_view(cls, base_class):
        """Create a view class with mixins applied."""
        name = f"{cls.model.__name__}{base_class.__name__.lstrip('_')}"
        bases = tuple(cls.mixins) + (base_class,)
        # When using django-tables2, it handles pagination itself —
        # skip Django's built-in paginate_by to avoid double-paginating.
        paginate_by = None if (base_class is _CRUDListBase and cls.table_class) else cls.paginate_by
        return type(
            name,
            bases,
            {
                "model": cls.model,
                "paginate_by": paginate_by,
                "crud_config": cls,
            },
        )

    @classmethod
    def get_urls(cls):
        """Generate URL patterns for configured actions."""
        url_base = cls._get_url_base()
        urls = []

        if Action.LIST in cls.actions:
            view = cls._make_view(_CRUDListBase)
            urls.append(path(f"{url_base}/", view.as_view(), name=f"{url_base}-list"))

        if Action.CREATE in cls.actions:
            view = cls._make_view(_CRUDCreateBase)
            urls.append(path(f"{url_base}/new/", view.as_view(), name=f"{url_base}-create"))

        if Action.DETAIL in cls.actions:
            view = cls._make_view(_CRUDDetailBase)
            urls.append(path(f"{url_base}/<pk>/", view.as_view(), name=f"{url_base}-detail"))

        if Action.UPDATE in cls.actions:
            view = cls._make_view(_CRUDUpdateBase)
            urls.append(path(f"{url_base}/<pk>/edit/", view.as_view(), name=f"{url_base}-update"))

        if Action.DELETE in cls.actions:
            view = cls._make_view(_CRUDDeleteBase)
            urls.append(path(f"{url_base}/<pk>/delete/", view.as_view(), name=f"{url_base}-delete"))

        return urls
