"""The saved-view form: a checkbox list of the calendars this user may see.

The ``datasets`` column is JSON, which a generated ModelForm would render as a
textarea of raw JSON. Replacing it with a ``MultipleChoiceField`` whose choices
are the *viewer's* visible calendars does two things at once: the form shows
real labels, and a submitted key the user may not see fails validation ("not a
valid choice") instead of being stored — the same narrowing-is-validation
trick the blog console forms rely on.
"""

from __future__ import annotations

from typing import Any

from django import forms

from .core import list_calendars
from .models import SavedCalendarView


class SavedCalendarViewForm(forms.ModelForm):
    datasets = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "calendar-view-choices"}),
        help_text="Pick the calendars this view shows together.",
    )

    class Meta:
        model = SavedCalendarView
        fields = ["name", "datasets", "is_default"]
        widgets = {"name": forms.TextInput(attrs={"class": "vTextField"})}

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        field = self.fields["datasets"]
        assert isinstance(field, forms.MultipleChoiceField)
        field.choices = [(c["key"], c["label"]) for c in list_calendars(user)]
        # An instance's stored keys arrive as a JSON list; the choice widget
        # wants exactly that, so no coercion — but ``initial`` from the create
        # page's ``?datasets=a,b`` prefill arrives as a string.
        initial = self.initial.get("datasets")
        if isinstance(initial, str):
            self.initial["datasets"] = [k for k in initial.split(",") if k]

    def clean_datasets(self) -> list[str]:
        return [str(k) for k in self.cleaned_data.get("datasets") or []]

    def save(self, commit: bool = True) -> SavedCalendarView:
        """Stamp the signed-in owner on a create. Done here, not in
        ``on_form_valid``, because that hook fires *after* the insert and the
        owner column is NOT NULL — and because the form is the one object every
        surface (HTML, REST, MCP) builds with the user in hand."""
        obj = super().save(commit=False)
        if obj.owner_id is None and self.user is not None and getattr(self.user, "is_authenticated", False):
            obj.owner = self.user
        if commit:
            obj.save()
            self.save_m2m()
        return obj
