"""Views for the Runbook app."""

from __future__ import annotations

from typing import Any, Optional

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView
from django.views.generic.edit import FormView

from . import permissions, service, subscriptions
from .forms import (
    DocumentCreateFromScratchForm,
    DocumentForm,
    DocumentImageForm,
    NewVersionForm,
    RunbookCreateForm,
    RunbookForm,
    SectionForm,
)
from .mixins import StaffRequiredMixin  # noqa: F401  (kept for staff-only endpoints if any)
from .models import Document, DocumentImage, DocumentVersion, Runbook, Section, strip_frontmatter
from .utils import parse_slides, parse_steps, render_document, render_markdown

# -- Dashboard ----------------------------------------------------------------


class RunbookDashboardView(LoginRequiredMixin, TemplateView):
    """Staff-only dashboard listing all runbooks."""

    template_name = "runbook/dashboard.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        docs = permissions.viewable_documents(user, _current_docs())
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)

        annotated = permissions.viewable_runbooks(user, Runbook.objects.annotate(
            section_count=Count("sections", distinct=True),
            doc_count=Count(
                "sections__documents",
                filter=Q(sections__documents__is_archived=False),
                distinct=True,
            ),
        ))
        runbooks = annotated.filter(is_template=False)
        templates = annotated.filter(is_template=True)

        # Partition non-template runbooks so the dashboard can show "My Runbooks"
        # separately from public/system ones (see dashboard.html).
        uid = getattr(user, "id", None)
        my_runbooks = runbooks.filter(owner_id=uid) if uid else runbooks.none()
        other_runbooks = runbooks.exclude(owner_id=uid) if uid else runbooks

        context.update({
            "total_docs": docs.count(),
            "total_sections": Section.objects.filter(runbook__in=runbooks.values("pk")).count(),
            "total_runbooks": runbooks.count(),
            "recent_uploads": docs.filter(created_at__gte=seven_days_ago).count(),
            "total_images": DocumentImage.objects.filter(document__in=docs.values("pk")).count(),
            "recent_docs": docs.select_related("section", "section__runbook", "created_by")[:10],
            "runbooks": runbooks,
            "my_runbooks": my_runbooks,
            "other_runbooks": other_runbooks,
            "templates": templates,
            "view": "list" if self.request.GET.get("view") == "list" else "cards",
        })
        return context


# -- Runbook CRUD -------------------------------------------------------------

# Curated emoji set for the runbook icon picker (users may also type their own).
ICON_CHOICES = [
    "📘", "📗", "📕", "📙", "📚", "📖", "📝", "🗒️", "📋", "✅",
    "🚀", "🛠️", "⚙️", "🔧", "🧰", "🖥️", "💻", "🗄️", "📦", "🔐",
    "🔑", "🛡️", "🚨", "📡", "🌐", "🔌", "🧭", "🧪", "🐛", "📊",
    "📈", "🗂️", "📁", "🏷️", "⭐", "🔥", "💡", "🎯", "🏗️", "🧑‍💻",
]


class RunbookCreateView(LoginRequiredMixin, CreateView):
    model = Runbook
    form_class = RunbookCreateForm
    template_name = "runbook/runbook_form.html"
    extra_context = {"icon_choices": ICON_CHOICES}

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["viewer"] = self.request.user  # scope the template picker
        return kwargs

    def form_valid(self, form: RunbookCreateForm) -> HttpResponse:
        template = form.cleaned_data.get("template")
        if template:
            _require_view(self.request.user, template)
            # Clone the template into a fresh (non-template) runbook owned by the
            # creator, then apply any description/icon the user typed.
            runbook = service.clone_runbook(
                template,
                new_name=form.cleaned_data["name"],
                as_template=False,
                copy_locked=False,
                actor=self.request.user,
                owner=self.request.user,
            )
            runbook.is_public = bool(form.cleaned_data.get("is_public"))
            overrides = [f for f in ("description", "icon") if form.cleaned_data.get(f)]
            for field in overrides:
                setattr(runbook, field, form.cleaned_data[field])
            runbook.save(update_fields=[*overrides, "is_public", "updated_at"])
            messages.success(
                self.request, f'Runbook "{runbook.name}" created from template "{template.name}".'
            )
            return redirect(runbook.get_absolute_url())
        # A fresh (non-template) runbook is owned by its creator.
        form.instance.owner = self.request.user
        return super().form_valid(form)

    def get_success_url(self) -> str:
        messages.success(self.request, f'Runbook "{self.object.name}" created.')
        return self.object.get_absolute_url()


class RunbookUpdateView(LoginRequiredMixin, UpdateView):
    model = Runbook
    form_class = RunbookForm
    template_name = "runbook/runbook_form.html"
    extra_context = {"icon_choices": ICON_CHOICES}

    def get_object(self, queryset: Optional[QuerySet[Runbook]] = None) -> Runbook:
        runbook = super().get_object(queryset)
        _require_edit(self.request.user, runbook)
        return runbook

    def get_success_url(self) -> str:
        messages.success(self.request, f'Runbook "{self.object.name}" updated.')
        return self.object.get_absolute_url()


class RunbookDeleteView(LoginRequiredMixin, View):
    """Delete a runbook — with a confirmation that surfaces its documents and
    lets you choose their fate: detach (keep as standalone) or cascade (delete)."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        runbook = get_object_or_404(Runbook, slug=slug)
        _require_edit(request.user, runbook)
        return render(request, "runbook/runbook_delete_confirm.html", {
            "runbook": runbook,
            "doc_count": Document.objects.filter(runbook=runbook).count(),
            "section_count": runbook.sections.count(),
        })

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        runbook = get_object_or_404(Runbook, slug=slug)
        _require_edit(request.user, runbook)
        name = runbook.name
        docs = Document.objects.filter(runbook=runbook)
        count = docs.count()

        if request.POST.get("mode") == "cascade":
            docs.delete()  # cascades versions + images
            runbook.delete()
            messages.success(request, f'Runbook "{name}" and {count} document(s) deleted.')
        else:  # detach (default) — documents become standalone (key is namespace-scoped)
            docs.update(key=None)
            runbook.delete()  # SET_NULL detaches the (now keyless) documents
            messages.success(request, f'Runbook "{name}" deleted; {count} document(s) kept as standalone.')
        return redirect("runbook:dashboard")


class RunbookMakeTemplateView(LoginRequiredMixin, View):
    """Clone a runbook into a reusable template (the original is left untouched)."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        runbook = get_object_or_404(Runbook, slug=slug, is_template=False)
        _require_edit(request.user, runbook)
        return render(request, "runbook/runbook_make_template_confirm.html", {
            "runbook": runbook,
            "doc_count": Document.objects.filter(runbook=runbook, is_archived=False).count(),
            "section_count": runbook.sections.count(),
        })

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        runbook = get_object_or_404(Runbook, slug=slug, is_template=False)
        _require_edit(request.user, runbook)
        template = service.clone_runbook(
            runbook,
            new_name=request.POST.get("name") or f"{runbook.name} Template",
            as_template=True,
            copy_locked=False,
            actor=request.user,
            owner=request.user,
        )
        messages.success(request, f'Template "{template.name}" created from "{runbook.name}".')
        return redirect(template.get_absolute_url())


class RunbookFromTemplateView(LoginRequiredMixin, View):
    """Instantiate a fresh runbook from a template (sections + starter docs)."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        template = get_object_or_404(Runbook, slug=slug, is_template=True)
        _require_view(request.user, template)
        return render(request, "runbook/runbook_from_template.html", {"template": template})

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        template = get_object_or_404(Runbook, slug=slug, is_template=True)
        _require_view(request.user, template)
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Please give the new runbook a name.")
            return redirect("runbook:runbook_from_template", slug=slug)
        runbook = service.clone_runbook(
            template,
            new_name=name,
            new_slug=(request.POST.get("slug") or "").strip() or None,
            as_template=False,
            copy_locked=False,
            actor=request.user,
            owner=request.user,
        )
        messages.success(request, f'Runbook "{runbook.name}" created from template "{template.name}".')
        return redirect(runbook.get_absolute_url())


class RunbookPublishToggleView(LoginRequiredMixin, View):
    """Toggle a runbook's public/private (publish) state — owner or staff only."""

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        runbook = get_object_or_404(Runbook, slug=slug)
        _require_edit(request.user, runbook)
        runbook.is_public = not runbook.is_public
        runbook.save(update_fields=["is_public", "updated_at"])
        state = "published (public)" if runbook.is_public else "made private"
        messages.success(request, f'Runbook "{runbook.name}" {state}.')
        return redirect(runbook.get_absolute_url())


class RunbookDetailView(LoginRequiredMixin, DetailView):
    """Table of contents view for a single runbook."""

    model = Runbook
    template_name = "runbook/runbook_detail.html"
    context_object_name = "runbook"

    def get_object(self, queryset: Optional[QuerySet[Runbook]] = None) -> Runbook:
        runbook = super().get_object(queryset)
        _require_view(self.request.user, runbook)
        return runbook

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sections = self.object.sections.prefetch_related(
            "documents"
        ).annotate(
            doc_count=Count("documents", filter=Q(documents__is_archived=False))
        ).order_by("order", "name")

        # Pages attached to the runbook but not to any section — shown in an
        # "Ungrouped" block so they aren't lost (a runbook can hold section-less pages).
        ungrouped = Document.objects.filter(
            runbook=self.object, section__isnull=True, is_archived=False
        ).order_by("title")

        context["sections"] = sections
        context["ungrouped_docs"] = ungrouped
        context["total_docs"] = sum(s.doc_count for s in sections) + ungrouped.count()
        context["template_docs"] = service.list_template_documents(viewer=self.request.user)
        context["can_edit"] = permissions.can_edit(self.request.user, self.object)
        return context


class RunbookReadView(LoginRequiredMixin, DetailView):
    """Render an entire runbook — all sections and current documents — as one
    continuous, linkable page. Each section and document gets an anchor id so
    other parts of the system can deep-link (e.g. ``…/read/#doc-42``)."""

    model = Runbook
    template_name = "runbook/runbook_read.html"
    context_object_name = "runbook"

    def get_object(self, queryset: Optional[QuerySet[Runbook]] = None) -> Runbook:
        runbook = super().get_object(queryset)
        _require_view(self.request.user, runbook)
        return runbook

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        rendered_sections = _render_runbook_sections(self.object)
        context["rendered_sections"] = rendered_sections
        context["total_docs"] = sum(len(s["documents"]) for s in rendered_sections)
        return context


def _render_runbook_sections(runbook: Runbook) -> list[dict[str, Any]]:
    """Build the [{section, documents:[{doc, html}]}] structure for a runbook,
    skipping empty sections. Shared by the full read view and the preview."""
    rendered_sections = []
    sections = runbook.sections.prefetch_related("documents").order_by("order", "name")
    for section in sections:
        docs = section.documents.filter(is_archived=False).order_by("title")
        rendered_docs = [{"doc": d, "html": render_document(d)["html"]} for d in docs]
        if rendered_docs:
            rendered_sections.append({"section": section, "documents": rendered_docs})
    return rendered_sections


class RunbookPreviewView(LoginRequiredMixin, View):
    """HTML fragment: a rendered preview of a runbook's content, loaded into the
    dashboard preview modal (htmx)."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        runbook = get_object_or_404(Runbook, slug=slug)
        _require_view(request.user, runbook)
        return render(request, "runbook/includes/runbook_preview.html", {
            "runbook": runbook,
            "rendered_sections": _render_runbook_sections(runbook),
        })


# -- Section CRUD -------------------------------------------------------------


class SectionCreateView(LoginRequiredMixin, CreateView):
    model = Section
    form_class = SectionForm
    template_name = "runbook/section_form.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.runbook = get_object_or_404(Runbook, slug=kwargs["slug"])
        if request.user.is_authenticated:
            _require_edit(request.user, self.runbook)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["runbook"] = self.runbook
        return context

    def form_valid(self, form: SectionForm) -> HttpResponse:
        form.instance.runbook = self.runbook
        return super().form_valid(form)

    def get_success_url(self) -> str:
        messages.success(self.request, f'Section "{self.object.name}" created.')
        return self.object.get_absolute_url()


class SectionUpdateView(LoginRequiredMixin, UpdateView):
    model = Section
    form_class = SectionForm
    template_name = "runbook/section_form.html"

    def get_object(self, queryset: Optional[QuerySet[Section]] = None) -> Section:
        section = super().get_object(queryset)
        _require_edit(self.request.user, section.runbook)
        return section

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["runbook"] = self.object.runbook
        return context

    def get_success_url(self) -> str:
        messages.success(self.request, f'Section "{self.object.name}" updated.')
        return self.object.get_absolute_url()


class SectionDeleteView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        section = get_object_or_404(Section, pk=pk)
        runbook = section.runbook
        _require_edit(request.user, runbook)
        name = section.name
        section.delete()
        messages.success(request, f'Section "{name}" deleted.')
        return redirect(runbook.get_absolute_url())


# -- Document CRUD ------------------------------------------------------------


def _current_docs() -> QuerySet[Document]:
    """Base queryset for live (non-archived) logical documents."""
    return Document.objects.filter(is_archived=False)


def _search_docs(qs: QuerySet[Document], query: str) -> QuerySet[Document]:
    """Filter documents by title, description, or content text."""
    return qs.filter(
        Q(title__icontains=query)
        | Q(description__icontains=query)
        | Q(content_text__icontains=query)
    )


def _editable(user: AbstractBaseUser | AnonymousUser, doc: Document) -> bool:
    """A locked document is read-only except to a superuser."""
    return not doc.locked or getattr(user, "is_superuser", False)


def _lock_redirect(request: HttpRequest, doc: Document) -> HttpResponse:
    """Redirect response + message when a non-superuser touches a locked doc."""
    messages.info(request, "This document is managed (locked). A superuser can unlock it to edit.")
    return redirect(doc.get_absolute_url())


def _require_view(user: Any, obj: Any) -> None:
    """Raise 403 unless ``user`` may view ``obj`` (a Runbook, a Document, or None)."""
    ok = permissions.can_view_doc(user, obj) if isinstance(obj, Document) else permissions.can_view(user, obj)
    if not ok:
        raise PermissionDenied


def _require_edit(user: Any, obj: Any) -> None:
    """Raise 403 unless ``user`` may edit ``obj`` (a Runbook, a Document, or None)."""
    ok = permissions.can_edit_doc(user, obj) if isinstance(obj, Document) else permissions.can_edit(user, obj)
    if not ok:
        raise PermissionDenied


# Sortable columns for the document list: URL key → safe ORM order field.
_DOC_SORT_FIELDS = {
    "title": "title",
    "runbook": "runbook__name",
    "section": "section__name",
    "type": "file_type",
    "version": "version",
    "author": "created_by__username",
    "updated": "updated_at",
}
_DOC_DEFAULT_SORT = "-updated"
# Table columns rendered as sortable headers: (url key, label, alignment).
_DOC_COLUMNS = [
    ("title", "Title", "left"),
    ("runbook", "Runbook", "left"),
    ("section", "Section", "left"),
    ("type", "Type", "center"),
    ("version", "Version", "right"),
    ("author", "Author", "left"),
    ("updated", "Updated", "left"),
]


class DocumentListView(LoginRequiredMixin, ListView):
    model = Document
    template_name = "runbook/document_list.html"
    context_object_name = "documents"
    paginate_by = 15

    def _sort(self) -> str:
        """The active sort token (e.g. "title" / "-updated"), validated to a known field."""
        sort = self.request.GET.get("sort", _DOC_DEFAULT_SORT)
        return sort if sort.lstrip("-") in _DOC_SORT_FIELDS else _DOC_DEFAULT_SORT

    def get_queryset(self) -> QuerySet[Document]:
        # Template-runbook docs are exemplars, not part of the working set — hide
        # them from the cross-runbook document list (they stay searchable).
        qs = (
            _current_docs()
            .exclude(runbook__is_template=True)
            .select_related("runbook", "section", "section__runbook", "created_by")
        )
        qs = permissions.viewable_documents(self.request.user, qs)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = _search_docs(qs, q)

        section = self.request.GET.get("section", "")
        if section:
            qs = qs.filter(section__slug=section)

        file_type = self.request.GET.get("type", "")
        if file_type:
            qs = qs.filter(file_type=file_type)

        sort = self._sort()
        field = _DOC_SORT_FIELDS[sort.lstrip("-")]
        order = f"-{field}" if sort.startswith("-") else field
        return qs.order_by(order)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["sections"] = Section.objects.select_related("runbook").all()
        context["search_query"] = self.request.GET.get("q", "")
        context["active_section"] = self.request.GET.get("section", "")
        context["active_type"] = self.request.GET.get("type", "")
        context["current_sort"] = self._sort()
        context["columns"] = _DOC_COLUMNS
        # Current filters as a querystring (minus page/sort) for building sort + page links.
        params = self.request.GET.copy()
        params.pop("page", None)
        params.pop("sort", None)
        context["filter_qs"] = params.urlencode()
        return context


class DocumentCreateView(LoginRequiredMixin, CreateView):
    model = Document
    form_class = DocumentForm
    template_name = "runbook/document_form.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.runbook = get_object_or_404(Runbook, slug=kwargs["slug"])
        if request.user.is_authenticated:
            _require_edit(request.user, self.runbook)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["runbook"] = self.runbook
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["runbook"] = self.runbook
        return context

    def form_valid(self, form: DocumentForm) -> HttpResponse:
        body = form.cleaned_data["file"].read().decode("utf-8", errors="replace")
        self.object = service.create_document(
            self.runbook,
            body=body,
            title=form.cleaned_data["title"],
            section=form.cleaned_data.get("section"),
            description=form.cleaned_data.get("description", ""),
            is_generated=False,
            via="web",
            actor=self.request.user,
        )
        messages.success(self.request, f'Document "{self.object.title}" uploaded.')
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        return self.object.get_absolute_url()


class DocumentCreateFromScratchView(LoginRequiredMixin, CreateView):
    """Create a new markdown document from scratch (no file upload)."""

    model = Document
    form_class = DocumentCreateFromScratchForm
    template_name = "runbook/document_form.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.runbook = get_object_or_404(Runbook, slug=kwargs["slug"])
        if request.user.is_authenticated:
            _require_edit(request.user, self.runbook)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["runbook"] = self.runbook
        kwargs["viewer"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["runbook"] = self.runbook
        context["from_scratch"] = True
        return context

    def form_valid(self, form: DocumentCreateFromScratchForm) -> HttpResponse:
        title = form.cleaned_data["title"]
        section = form.cleaned_data.get("section")
        description = form.cleaned_data.get("description", "")
        template = form.cleaned_data.get("template")
        if template is not None:
            # Optional template picker: seed the page from the template's content.
            doc = service.create_from_template(
                self.runbook, title=title, template=template, section=section,
                description=description, actor=self.request.user,
            )
            messages.success(self.request, f'Document "{doc.title}" created from template "{template.title}".')
        else:
            doc = service.create_document(
                self.runbook,
                body=f"# {title}\n\n",
                title=title,
                section=section,
                description=description,
                is_generated=False,
                via="web",
                actor=self.request.user,
            )
            messages.success(self.request, f'Document "{doc.title}" created.')
        return redirect("runbook:document_edit_content", pk=doc.pk)


class DocumentMakeTemplateView(LoginRequiredMixin, View):
    """Toggle a page's template status (staff)."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        doc = get_object_or_404(Document, pk=pk)
        _require_edit(request.user, doc)
        doc.is_template = not doc.is_template
        doc.save(update_fields=["is_template", "updated_at"])
        if doc.is_template:
            messages.success(request, f'"{doc.title}" is now a template — offered in the New Page dialog.')
        else:
            messages.success(request, f'"{doc.title}" is no longer a template.')
        return redirect(doc.get_absolute_url())


class DocumentUpdateView(LoginRequiredMixin, UpdateView):
    model = Document
    form_class = DocumentForm
    template_name = "runbook/document_form.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        doc = get_object_or_404(Document, pk=kwargs["pk"])
        if request.user.is_authenticated:
            _require_edit(request.user, doc)
            if not _editable(request.user, doc):
                return _lock_redirect(request, doc)
        return super().dispatch(request, *args, **kwargs)

    def _runbook(self) -> Optional[Runbook]:
        return self.object.runbook or (self.object.section.runbook if self.object.section_id else None)

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["runbook"] = self._runbook()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["runbook"] = self._runbook()
        return context

    def form_valid(self, form: DocumentForm) -> HttpResponse:
        self.object = form.save()
        # A file uploaded during a metadata edit becomes a new version.
        uploaded = form.cleaned_data.get("file")
        if uploaded:
            body = uploaded.read().decode("utf-8", errors="replace")
            service.write_version(self.object, body=body, mode="new_version", actor=self.request.user, via="web")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        messages.success(self.request, f'Document "{self.object.title}" updated.')
        return self.object.get_absolute_url()


class DocumentDeleteView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        doc = get_object_or_404(Document, pk=pk)
        _require_edit(request.user, doc)
        if not _editable(request.user, doc):
            return _lock_redirect(request, doc)
        title = doc.title
        doc.delete()
        messages.success(request, f'Document "{title}" deleted.')
        return redirect("runbook:document_list")


# -- Document Detail & Rendering ----------------------------------------------


class DocumentDetailView(LoginRequiredMixin, DetailView):
    """Render document content based on file_type."""

    model = Document
    template_name = "runbook/document_detail.html"
    context_object_name = "document"

    def get_object(self, queryset: Optional[QuerySet[Document]] = None) -> Document:
        obj = super().get_object(queryset)
        _require_view(self.request.user, obj)
        return obj

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["rendered"] = render_document(self.object)
        # Image pool hangs off the logical document, shared by every version.
        context["images"] = self.object.images.all()
        context["is_subscribed"] = subscriptions.is_subscribed(self.request.user, self.object)
        # Editable only if you own it (or are staff) AND it isn't locked to you.
        context["can_edit"] = permissions.can_edit_doc(self.request.user, self.object) and _editable(
            self.request.user, self.object
        )
        context["can_manage_lock"] = self.request.user.is_superuser
        return context


class DocumentLockView(LoginRequiredMixin, View):
    """Superuser-only: toggle a document's locked (managed / read-only) state."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        if not request.user.is_superuser:
            raise PermissionDenied
        doc = get_object_or_404(Document, pk=pk)
        doc.locked = not doc.locked
        doc.save(update_fields=["locked", "updated_at"])
        messages.success(request, f'Document {"locked" if doc.locked else "unlocked"}.')
        return redirect(doc.get_absolute_url())


class DocumentSubscribeView(LoginRequiredMixin, View):
    """Toggle the current user's subscription to a document's updates."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        doc = get_object_or_404(Document, pk=pk)
        _require_view(request.user, doc)
        if subscriptions.is_subscribed(request.user, doc):
            subscriptions.unsubscribe(request.user, doc)
            messages.info(request, f'Unsubscribed from "{doc.title}".')
        else:
            subscriptions.subscribe(request.user, doc)
            messages.success(request, f'Subscribed to "{doc.title}" — you\'ll be emailed on updates.')
        return redirect(doc.get_absolute_url())


class DocumentSlideView(LoginRequiredMixin, DetailView):
    """Slide deck presentation for markdown documents."""

    model = Document
    template_name = "runbook/document_slides.html"
    context_object_name = "document"

    def get_object(self, queryset: Optional[QuerySet] = None) -> Document:
        obj = super().get_object(queryset)
        _require_view(self.request.user, obj)
        if not obj.is_markdown:
            raise Http404("Slide view is only available for Markdown documents.")
        return obj

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        doc = self.object
        raw = doc.file.read().decode("utf-8")
        doc.file.seek(0)
        context["slides"] = parse_slides(strip_frontmatter(raw))
        return context


class DocumentStepView(LoginRequiredMixin, DetailView):
    """Step/process timeline view for markdown documents."""

    model = Document
    template_name = "runbook/document_steps.html"
    context_object_name = "document"

    def get_object(self, queryset: Optional[QuerySet] = None) -> Document:
        obj = super().get_object(queryset)
        _require_view(self.request.user, obj)
        if not obj.is_markdown:
            raise Http404("Step view is only available for Markdown documents.")
        return obj

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        doc = self.object
        raw = doc.file.read().decode("utf-8")
        doc.file.seek(0)
        context["steps"] = parse_steps(strip_frontmatter(raw))
        return context


# -- Versioning ---------------------------------------------------------------


class DocumentVersionsView(LoginRequiredMixin, DetailView):
    """Show the version history of a document."""

    model = Document
    template_name = "runbook/document_versions.html"
    context_object_name = "document"

    def get_object(self, queryset: Optional[QuerySet[Document]] = None) -> Document:
        obj = super().get_object(queryset)
        _require_view(self.request.user, obj)
        return obj

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["version_chain"] = self.object.versions.select_related("created_by").all()
        return context


class NewVersionView(LoginRequiredMixin, FormView):
    """Upload a new version of an existing document."""

    form_class = NewVersionForm
    template_name = "runbook/new_version_form.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.parent_doc = get_object_or_404(Document, pk=kwargs["pk"])
        if request.user.is_authenticated:
            _require_edit(request.user, self.parent_doc)
            if not _editable(request.user, self.parent_doc):
                return _lock_redirect(request, self.parent_doc)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["parent_doc"] = self.parent_doc
        return context

    def form_valid(self, form: NewVersionForm) -> HttpResponse:
        body = form.cleaned_data["file"].read().decode("utf-8", errors="replace")
        doc = service.write_version(
            self.parent_doc,
            body=body,
            mode="new_version",
            description=form.cleaned_data.get("description", ""),
            actor=self.request.user,
            via="web",
        )
        messages.success(self.request, f'Version {doc.version} of "{doc.title}" uploaded.')
        return redirect(doc.get_absolute_url())


class RestoreVersionView(LoginRequiredMixin, View):
    """Restore an old version by creating a new version from it."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        old = get_object_or_404(DocumentVersion, pk=pk)
        _require_edit(request.user, old.document)
        if not _editable(request.user, old.document):
            return _lock_redirect(request, old.document)
        old.file.open("rb")
        body = old.file.read().decode("utf-8", errors="replace")
        old.file.close()
        doc = service.write_version(
            old.document,
            body=body,
            mode="new_version",
            description=f"Restored from version {old.version}",
            actor=request.user,
            via="web",
        )
        messages.success(request, f'Restored version {old.version} as new version {doc.version}.')
        return redirect(doc.get_absolute_url())


# -- In-Place Content Editing -------------------------------------------------


class DocumentEditContentView(LoginRequiredMixin, View):
    """Edit markdown file content in-place via a textarea."""

    def _get_markdown_doc(self, pk: int) -> Document:
        doc = get_object_or_404(Document, pk=pk)
        if not doc.is_markdown:
            raise Http404("Content editing is only available for Markdown documents.")
        return doc

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        doc = self._get_markdown_doc(pk)
        _require_edit(request.user, doc)
        if not _editable(request.user, doc):
            return _lock_redirect(request, doc)
        raw = doc.file.read().decode("utf-8")
        doc.file.seek(0)
        return render(request, "runbook/document_edit_content.html", {
            "document": doc,
            "content": raw,
        })

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        doc = self._get_markdown_doc(pk)
        _require_edit(request.user, doc)
        if not _editable(request.user, doc):
            return _lock_redirect(request, doc)
        content = request.POST.get("content", "")
        actor = request.user if request.user.is_authenticated else None

        # "Save as new version" cuts a version instead of overwriting in place —
        # but only when the content actually changed (no empty version churn).
        if request.POST.get("save_as_version"):
            if content == service.read_head(doc):
                messages.info(request, "No changes detected — version not created.")
                return redirect(doc.get_absolute_url())
            service.write_version(
                doc, body=content, mode="new_version", description="Edited content", actor=actor, via="web"
            )
            messages.success(request, f'Saved as version {doc.version} of "{doc.title}".')
            return redirect(doc.get_absolute_url())

        # Default: overwrite the current version in place.
        service.write_version(doc, body=content, mode="overwrite", actor=actor, via="web")
        messages.success(request, f'Content of "{doc.title}" saved.')
        return redirect(doc.get_absolute_url())


class MarkdownPreviewView(LoginRequiredMixin, View):
    """htmx endpoint: render markdown content to HTML fragment."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        doc = get_object_or_404(Document, pk=pk)
        _require_view(request.user, doc)
        content = request.POST.get("content", "")
        rendered = render_markdown(strip_frontmatter(content))
        return HttpResponse(f'<div class="runbook-content">{rendered["html"]}</div>')


# -- File Serving -------------------------------------------------------------


class ServeFileView(LoginRequiredMixin, View):
    """Serve the uploaded file (for downloads)."""

    def get(self, request: HttpRequest, pk: int) -> FileResponse:
        doc = get_object_or_404(Document, pk=pk)
        _require_view(request.user, doc)
        download = request.GET.get("download")
        as_attachment = download is not None
        filename = f"{doc.slug}.{doc.file_type}" if as_attachment else None
        return FileResponse(
            doc.file.open("rb"),
            content_type="text/markdown",
            as_attachment=as_attachment,
            filename=filename,
        )


class ServeVersionView(LoginRequiredMixin, View):
    """Serve a specific document version's file (used by the versions table)."""

    def get(self, request: HttpRequest, pk: int) -> FileResponse:
        version = get_object_or_404(DocumentVersion, pk=pk)
        _require_view(request.user, version.document)
        download = request.GET.get("download")
        as_attachment = download is not None
        filename = f"{version.document.slug}-v{version.version}.{version.file_type}" if as_attachment else None
        return FileResponse(
            version.file.open("rb"),
            content_type="text/markdown",
            as_attachment=as_attachment,
            filename=filename,
        )


# -- Document Images ----------------------------------------------------------


class DocumentImageUploadView(LoginRequiredMixin, View):
    """Upload an image for a document; return JSON with the markdown to insert.

    Used by both the "Insert image" file picker and clipboard paste. The image
    attaches to the logical document so every version shares one pool. Returns
    ``{id, url, markdown}``; the URL points at the access-checked ``serve_image``
    view, never the public MEDIA path.
    """

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        doc = get_object_or_404(Document, pk=pk)
        if not permissions.can_edit_doc(request.user, doc):
            return JsonResponse({"error": "You do not have permission to edit this document."}, status=403)
        if not _editable(request.user, doc):
            return JsonResponse({"error": "Document is locked."}, status=403)
        form = DocumentImageForm(request.POST, request.FILES)
        if not form.is_valid():
            errors = form.errors.get("image") or form.errors.as_text()
            return JsonResponse({"error": str(errors)}, status=400)

        ref = service.attach_image(
            document=doc,
            file=form.cleaned_data["image"],
            alt=form.cleaned_data.get("alt", ""),
            actor=request.user if request.user.is_authenticated else None,
        )
        return JsonResponse({"id": ref.id, "url": ref.url, "markdown": ref.markdown})


class ServeImageView(LoginRequiredMixin, View):
    """Serve an image asset through access control (never via public MEDIA)."""

    def get(self, request: HttpRequest, pk: int) -> FileResponse:
        image = get_object_or_404(DocumentImage, pk=pk)
        _require_view(request.user, image.document)
        return FileResponse(image.image.open("rb"))


# -- Bulk Download ------------------------------------------------------------


class DownloadZipView(LoginRequiredMixin, View):
    """Download documents as a ZIP with runbook/section folder structure.

    ``?runbook=<slug>`` downloads a single runbook (omit for all).
    Each runbook folder gets an ``index.html`` table of contents.
    """

    def get(self, request: HttpRequest) -> FileResponse:
        import io
        import os
        import zipfile
        from collections import defaultdict

        runbook_slug = request.GET.get("runbook", "").strip()

        # Group by the document's own runbook FK — not section__runbook — so
        # section-less ("loose") docs attached straight to a runbook are included
        # (they're first-class in list_documents, the dashboard, and search).
        docs = permissions.viewable_documents(request.user, _current_docs()).select_related(
            "section", "section__runbook", "runbook"
        ).order_by("runbook__name", "section__order", "section__name", "title")

        if runbook_slug:
            runbook = get_object_or_404(Runbook, slug=runbook_slug)
            _require_view(request.user, runbook)
            docs = docs.filter(runbook=runbook)
            zip_name = f"{runbook.slug}.zip"
            single_runbook = True
        else:
            zip_name = "runbooks.zip"
            single_runbook = False

        # Structure: {runbook: {section: [(rel_path, doc)]}}
        runbook_map: dict = defaultdict(lambda: defaultdict(list))
        written_images: set[str] = set()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for doc in docs:
                parts: list[str] = []
                rb = doc.runbook  # direct FK: set for both sectioned and loose docs
                sec = doc.section

                if not single_runbook and rb:
                    parts.append(rb.slug)
                if sec:
                    parts.append(sec.slug)
                filename = os.path.basename(doc.file.name)
                dir_parts = list(parts)  # folder the markdown lives in
                parts.append(filename)
                path = "/".join(parts)

                # Read the markdown, rewrite any linked-image URLs to bundled
                # relative paths, and collect those images so the export is
                # self-contained (offline-viewable).
                doc.file.open("rb")
                content = doc.file.read().decode("utf-8", errors="replace")
                doc.file.close()
                content, images = _collect_doc_images(doc, content, dir_parts)
                zf.writestr(path, content)

                for img_zip_path, img in images:
                    if img_zip_path in written_images:
                        continue
                    written_images.add(img_zip_path)
                    img.image.open("rb")
                    zf.writestr(img_zip_path, img.image.read())
                    img.image.close()

                rel_path = f"{sec.slug}/{filename}" if sec else filename
                runbook_map[rb][sec].append((rel_path, doc))

            for rb, sections in runbook_map.items():
                index_html = _build_zip_index(rb, sections, single_runbook)
                prefix = "" if single_runbook or rb is None else f"{rb.slug}/"
                zf.writestr(f"{prefix}index.html", index_html)

        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=zip_name, content_type="application/zip")


def _collect_doc_images(doc: Document, content: str, dir_parts: list[str]) -> tuple[str, list]:
    """Rewrite linked-image URLs in ``content`` to bundled relative paths and
    return ``(rewritten_content, [(zip_path, DocumentImage), ...])``.

    Only images actually referenced by the document's markdown are included.
    Images are bundled into an ``images/`` folder beside the markdown file, so
    the relative reference from the doc is ``images/<id><ext>``.
    """
    import os

    images: list = []
    for img in doc.images.all():
        serve_url = reverse("runbook:serve_image", kwargs={"pk": img.pk})
        if serve_url not in content:
            continue
        ext = os.path.splitext(img.image.name)[1] or ".png"
        rel_ref = f"images/{img.pk}{ext}"
        content = content.replace(serve_url, rel_ref)
        zip_path = "/".join(dir_parts + [rel_ref]) if dir_parts else rel_ref
        images.append((zip_path, img))
    return content, images


def _build_zip_index(runbook: Runbook | None, sections: dict, single_runbook: bool) -> str:
    """Build a standalone HTML table of contents page for a ZIP export."""
    title = runbook.name if runbook else "Runbook"
    desc = runbook.description if runbook and runbook.description else ""

    sections_html: list[str] = []
    for section, doc_list in sections.items():
        sec_name = section.name if section else "Unsorted"
        items: list[str] = []
        for rel_path, doc in doc_list:
            badge = f'<span style="color:#888;font-size:0.8em;margin-left:6px;">.{doc.file_type}</span>'
            desc_line = ""
            if doc.description:
                desc_line = f'<div style="color:#888;font-size:0.85em;">{doc.description}</div>'
            items.append(
                f'<li style="margin-bottom:8px;">'
                f'<a href="{rel_path}">{doc.title}</a>{badge}'
                f'{desc_line}</li>'
            )
        sections_html.append(
            f'<h2 style="font-size:1.1em;margin:1.5em 0 0.5em;border-bottom:1px solid #ddd;'
            f'padding-bottom:4px;">{sec_name}</h2>'
            f'<ul style="list-style:none;padding:0;">{"".join(items)}</ul>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Table of Contents</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 720px; margin: 2em auto; padding: 0 1em; color: #222; }}
  a {{ color: #5b4a9e; }}
  h1 {{ margin-bottom: 0.25em; }}
  .subtitle {{ color: #666; margin-bottom: 1.5em; }}
</style>
</head>
<body>
<h1>{title}</h1>
{f'<p class="subtitle">{desc}</p>' if desc else ''}
{"".join(sections_html)}
</body>
</html>"""


# -- Dashboard Stat Detail ----------------------------------------------------


class DashboardStatDetailView(LoginRequiredMixin, View):
    """htmx endpoint: return HTML table for stat card drill-down modals."""

    def get(self, request: HttpRequest, stat_type: str) -> HttpResponse:
        columns, rows, empty = _get_stat_table(stat_type, request.user)
        return HttpResponse(_render_stat_table(columns, rows, empty))


def _stat_link(url: str, text: str) -> str:
    return f'<a href="{escape(url)}">{escape(text)}</a>'


def _rb_name(doc: Document) -> str:
    return escape(doc.runbook.name) if doc.runbook_id else "—"


def _sec_name(doc: Document) -> str:
    return escape(doc.section.name) if doc.section_id else "—"


def _get_stat_table(
    stat_type: str, user: Any = None,
) -> tuple[list[tuple[str, str]], list[list[str]], str]:
    """Return ``(columns, rows, empty_message)`` for a stat drill-down.

    ``columns`` is a list of ``(header, align)``; each row is a list of
    pre-rendered HTML cells (first cell links to the detail page). Scoped to
    what ``user`` may view.
    """
    docs = permissions.viewable_documents(user, _current_docs()).select_related("runbook", "section")

    if stat_type == "runbooks":
        runbooks = permissions.viewable_runbooks(user, Runbook.objects.filter(is_template=False)).annotate(
            section_count=Count("sections", distinct=True),
            doc_count=Count(
                "sections__documents",
                filter=Q(sections__documents__is_archived=False),
                distinct=True,
            ),
        ).order_by("name")
        columns = [("Runbook", "left"), ("Sections", "right"), ("Documents", "right")]
        rows = [
            [_stat_link(rb.get_absolute_url(), rb.name), str(rb.section_count), str(rb.doc_count)]
            for rb in runbooks
        ]
        return columns, rows, "No runbooks yet."

    if stat_type == "documents":
        items = docs.order_by("-created_at")[:30]
        columns = [
            ("Document", "left"), ("Runbook", "left"), ("Section", "left"),
            ("Type", "center"), ("Version", "right"),
        ]
        rows = [
            [
                _stat_link(doc.get_absolute_url(), doc.title),
                _rb_name(doc), _sec_name(doc), f".{escape(doc.file_type)}", f"v{doc.version}",
            ]
            for doc in items
        ]
        return columns, rows, "No documents yet."

    if stat_type == "recent":
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        items = docs.filter(created_at__gte=seven_days_ago).order_by("-created_at")
        columns = [("Document", "left"), ("Runbook", "left"), ("Section", "left"), ("Added", "right")]
        rows = [
            [
                _stat_link(doc.get_absolute_url(), doc.title),
                _rb_name(doc), _sec_name(doc), doc.created_at.strftime("%b %d, %Y"),
            ]
            for doc in items
        ]
        return columns, rows, "No uploads in the last 7 days."

    if stat_type == "images":
        with_images = (
            permissions.viewable_documents(user, Document.objects.filter(images__isnull=False))
            .select_related("runbook")
            .annotate(n=Count("images", distinct=True))
            .order_by("-n", "title")
        )
        columns = [("Document", "left"), ("Runbook", "left"), ("Images", "right")]
        rows = [
            [
                _stat_link(doc.get_absolute_url(), doc.title),
                _rb_name(doc), f"{doc.n} image" + ("" if doc.n == 1 else "s"),
            ]
            for doc in with_images
        ]
        return columns, rows, "No images attached yet."

    return [], [], ""


def _render_stat_table(columns: list, rows: list, empty_message: str = "") -> str:
    """Render a stat drill-down as an auto-layout ``.table-plain`` fragment.

    First cell of each row is prominent (the link); the rest are muted metadata.
    """
    # The modal's sticky <th> needs an OPAQUE background or scrolling rows show
    # through it. Inline !important beats the transparent-header rules that
    # .table-plain / .main-content apply, matching the panel's header band colour.
    hbg = "background:color-mix(in srgb, var(--primary) 15%, var(--body-bg)) !important;"
    head = "".join(
        f'<th style="text-align:{align};{hbg}cursor:pointer;user-select:none;" '
        f'title="Sort by {escape(header)}">{escape(header)}<span class="rb-sort-arrow"></span></th>'
        for header, align in columns
    )
    parts = [f'<table class="table-plain rb-sortable"><thead><tr>{head}</tr></thead><tbody>']
    if rows:
        aligns = [align for _, align in columns]
        for cells in rows:
            tds = ""
            for i, cell in enumerate(cells):
                # First cell is the prominent link; the rest are muted, nowrap metadata.
                extra = "" if i == 0 else "color:var(--body-quiet-color);white-space:nowrap;"
                tds += f'<td style="text-align:{aligns[i]};font-size:0.85rem;{extra}">{cell}</td>'
            parts.append(f"<tr>{tds}</tr>")
    else:
        parts.append(
            f'<tr><td colspan="{len(columns)}" '
            f'style="text-align:center;padding:24px;color:var(--body-quiet-color);">{escape(empty_message)}</td></tr>'
        )
    parts.append("</tbody></table>")
    return "".join(parts)


# -- Search -------------------------------------------------------------------


class SearchView(LoginRequiredMixin, TemplateView):
    """Full-text search across documents."""

    template_name = "runbook/search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        context["search_query"] = q

        if q:
            scoped = permissions.viewable_documents(self.request.user, _current_docs())
            context["results"] = _search_docs(
                scoped, q
            ).select_related("section", "section__runbook", "created_by")[:50]
        else:
            context["results"] = []

        return context


class SearchResultsView(LoginRequiredMixin, View):
    """htmx endpoint: return search results as HTML fragment."""

    def get(self, request: HttpRequest) -> HttpResponse:
        q = request.GET.get("q", "").strip()
        if not q:
            return HttpResponse("")

        scoped = permissions.viewable_documents(request.user, _current_docs())
        results = _search_docs(
            scoped, q
        ).select_related("section", "section__runbook")[:20]

        return render(request, "runbook/includes/search_results.html", {
            "results": results,
            "search_query": q,
        })
