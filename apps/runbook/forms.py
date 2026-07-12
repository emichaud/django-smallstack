"""Forms for Runbook."""

from __future__ import annotations

from typing import Any

from django import forms

from . import service
from .models import Document, DocumentImage, Runbook, Section


def _apply_text_class(form: forms.BaseForm) -> None:
    """Add vTextField CSS class to all text inputs and textareas."""
    for field in form.fields.values():
        if isinstance(field.widget, (forms.TextInput, forms.Textarea)):
            field.widget.attrs.setdefault("class", "vTextField")


class RunbookForm(forms.ModelForm):
    class Meta:
        model = Runbook
        fields = ["name", "description", "icon", "is_public"]
        labels = {"is_public": "Publish (make public)"}
        help_texts = {
            "is_public": "Public runbooks are readable by everyone; private ones are visible "
            "only to you and staff. Leave off to keep it private.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "What this runbook covers (optional)"}),
            # Rendered inside a custom icon picker (see runbook_form.html); keep it a
            # narrow text input so a custom emoji can still be typed.
            "icon": forms.TextInput(attrs={
                "class": "vTextField icon-input", "placeholder": "📘", "maxlength": 12, "autocomplete": "off",
            }),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _apply_text_class(self)


class RunbookCreateForm(RunbookForm):
    """New-runbook form with an optional 'start from template' selector."""

    template = forms.ModelChoiceField(
        queryset=Runbook.objects.filter(is_template=True).order_by("name"),
        required=False,
        empty_label="— blank runbook —",
        help_text="Optional — clone a template's sections and documents into the new runbook.",
    )

    field_order = ["name", "template", "description", "icon", "is_public"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # ``viewer`` scopes the template picker to templates this user may see.
        viewer = kwargs.pop("viewer", None)
        super().__init__(*args, **kwargs)
        templates = Runbook.objects.filter(is_template=True).order_by("name")
        if viewer is not None:
            from . import permissions
            templates = permissions.viewable_runbooks(viewer, templates)
        self.fields["template"].queryset = templates
        self.fields["template"].label_from_instance = lambda rb: f"{rb.icon} {rb.name}".strip()


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ["name", "description", "icon", "order"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _apply_text_class(self)


class DocumentForm(forms.ModelForm):
    """Create/update a document's metadata; ``file`` seeds the first version.

    ``file`` is an explicit (non-model) field now that content lives on
    DocumentVersion — the view uses it to create the initial version.
    """

    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": ".md"}))

    class Meta:
        model = Document
        fields = ["title", "section", "description"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.runbook: Runbook | None = kwargs.pop("runbook", None)
        super().__init__(*args, **kwargs)
        if self.runbook:
            self.fields["section"].queryset = Section.objects.filter(runbook=self.runbook)
        # On update, the file is optional (metadata-only edits shouldn't require re-upload).
        if self.instance and self.instance.pk:
            self.fields["file"].required = False
        _apply_text_class(self)


class DocumentCreateFromScratchForm(forms.ModelForm):
    """Create a new markdown document (no file upload).

    An optional ``template`` picker folds the "new from template" flow into this
    one form: leave it blank for a fresh page, or pick a template page to seed the
    content (mirrors ``RunbookCreateForm``'s runbook-level template selector).
    """

    template = forms.ModelChoiceField(
        queryset=Document.objects.none(),
        required=False,
        empty_label="— blank page —",
        help_text="Optional — start from a template page's content.",
    )

    field_order = ["title", "template", "section", "description"]

    class Meta:
        model = Document
        fields = ["title", "section", "description"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.runbook: Runbook | None = kwargs.pop("runbook", None)
        viewer = kwargs.pop("viewer", None)
        super().__init__(*args, **kwargs)
        if self.runbook:
            self.fields["section"].queryset = Section.objects.filter(runbook=self.runbook)
        self.fields["template"].queryset = service.list_template_documents(viewer=viewer)
        self.fields["template"].label_from_instance = (
            lambda d: f"{d.runbook.name} · {d.title}" if d.runbook_id else d.title
        )
        _apply_text_class(self)


class DocumentImageForm(forms.ModelForm):
    """Validate an uploaded image asset (Pillow checks it is a real image)."""

    class Meta:
        model = DocumentImage
        fields = ["image", "alt"]


class NewVersionForm(forms.Form):
    """Upload a new version of an existing document (content lives on versions)."""

    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": ".md"}))
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _apply_text_class(self)
