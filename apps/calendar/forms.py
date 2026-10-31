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

from .core import assign_series, iter_calendars, visible_calendars
from .models import Event, SavedCalendarView


class CalendarKeysField(forms.MultipleChoiceField):
    """A multiple-choice field that also accepts one key or a comma-separated
    string — what an agent typing into a chat is likely to send — and
    normalises it to the list the choice validation expects."""

    def to_python(self, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        result: list[str] = super().to_python(value)
        return result


class SavedCalendarViewForm(forms.ModelForm):
    datasets = CalendarKeysField(
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
        cals = visible_calendars(user) if user is not None else list(iter_calendars())
        series = assign_series(cals)
        field.choices = [(c.key, c.label) for c in cals]
        # For the HTML form: each choice with its description and the same
        # series colour the calendar page gives that calendar.
        self.calendar_choices = [
            {"key": c.key, "label": c.label, "description": c.description, "series": series.get(c.key, 0)}
            for c in cals
        ]
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


class EventForm(forms.ModelForm):
    """The Events calendar's entry form. ``created_by`` is stamped from the
    request, never a form field — a field would let one user file an entry as
    somebody else."""

    class Meta:
        model = Event
        fields = [
            "title",
            "start_date",
            "end_date",
            "all_day",
            "start_time",
            "end_time",
            "category",
            "location",
            "url",
            "description",
            "visibility",
            "cancelled",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "vTextField"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "category": forms.TextInput(attrs={"class": "vTextField"}),
            "location": forms.TextInput(attrs={"class": "vTextField"}),
            "url": forms.URLInput(attrs={"class": "vTextField"}),
            "description": forms.Textarea(attrs={"rows": 4, "class": "vTextField"}),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user

    def save(self, commit: bool = True) -> Event:
        obj = super().save(commit=False)
        if obj.created_by_id is None and self.user is not None and getattr(self.user, "is_authenticated", False):
            obj.created_by = self.user
        if commit:
            obj.save()
            self.save_m2m()
        return obj

