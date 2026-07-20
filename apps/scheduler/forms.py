"""ScheduledJobForm — validates the cadence fields and previews upcoming runs."""

from __future__ import annotations

from datetime import datetime

from django import forms
from django.utils import timezone

from apps.profile.models import TIMEZONE_CHOICES

from . import schedules
from .models import ScheduledJob


class ScheduledJobForm(forms.ModelForm):
    class Meta:
        model = ScheduledJob
        fields = [
            "name",
            "description",
            "task_path",
            "kwargs",
            "queue_name",
            "schedule_type",
            "interval_spec",
            "anchor_at",
            "cron_expression",
            "run_at",
            "timezone",
            "enabled",
            "allow_overlap",
            "catch_up",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "kwargs": forms.Textarea(attrs={"rows": 3, "class": "vTextField", "spellcheck": "false"}),
            "interval_spec": forms.TextInput(attrs={"placeholder": "5m, 2h, 1d, 90d, 1mo, 1y"}),
            "cron_expression": forms.TextInput(attrs={"placeholder": "0 6 * * *"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # Native datetime-local pickers (calendar + clock) for the two datetime
        # fields, with a matching parse format so they round-trip.
        dt_fmt = "%Y-%m-%dT%H:%M"
        for name in ("run_at", "anchor_at"):
            self.fields[name].widget = forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format=dt_fmt
            )
            self.fields[name].input_formats = [dt_fmt, "%Y-%m-%dT%H:%M:%S"]
        # Timezone: reuse the project's grouped, scrollable region select, but
        # add UTC (common for schedulers, absent from the profile list) and keep
        # whatever the instance already has selectable even if it's custom.
        tz_choices = list(TIMEZONE_CHOICES)
        tz_choices.insert(1, ("UTC", "UTC"))
        flat = set()
        for _label, opts in tz_choices:
            if isinstance(opts, (list, tuple)):
                flat.update(v for v, _ in opts)
            else:
                flat.add(_label)
        current_tz = self.initial.get("timezone") or getattr(self.instance, "timezone", "") or ""
        if current_tz and current_tz not in flat:
            tz_choices.append((current_tz, current_tz))
        self.fields["timezone"].widget = forms.Select(choices=tz_choices)
        # Friendlier copy for the two developer-facing fields.
        self.fields["task_path"].label = "Task to run"
        self.fields["task_path"].help_text = (
            "Dotted import path of the @task function to enqueue, e.g. "
            "apps.tasks.tasks.send_email_task (find these in apps/<app>/tasks.py)."
        )
        self.fields["kwargs"].help_text = (
            'JSON keyword arguments handed to the task when it runs — e.g. '
            '{"limit": 100, "dry_run": true}. Leave as {} for none.'
        )
        # The job definition is owned by code (@scheduled). Lock it read-only;
        # the operator only overrides the cadence + enabled + overlap/catch-up.
        for fname in ("name", "task_path", "kwargs", "queue_name", "description"):
            self.fields[fname].disabled = True

    _CADENCE = ("schedule_type", "interval_spec", "cron_expression", "run_at", "anchor_at", "timezone")

    def save(self, commit: bool = True) -> ScheduledJob:
        obj = super().save(commit=False)
        # A manual cadence change becomes a sticky override that code sync honors.
        if obj.pk and not obj.schedule_overridden:
            prev = ScheduledJob.objects.filter(pk=obj.pk).first()
            if prev and any(getattr(prev, f) != getattr(obj, f) for f in self._CADENCE):
                obj.schedule_overridden = True
        if commit:
            obj.save()
        return obj

    def clean(self) -> dict:
        """Run the model's cadence validation and surface it on the right field."""
        cleaned = super().clean()
        # Build a throwaway instance to reuse the model's coherence checks.
        instance = ScheduledJob(**{k: cleaned.get(k) for k in self.Meta.fields if k in cleaned})
        try:
            instance.clean()
        except forms.ValidationError as exc:
            # Re-raise per-field so errors land next to the offending input.
            self.add_error(None, exc)
        return cleaned

    def preview_runs(self, n: int = 5) -> list[datetime]:
        """Return the next ``n`` fire times for the current cleaned cadence.

        Used by the template to show operators what they just configured.
        Returns [] if the form isn't valid enough to compute.
        """
        if not self.is_valid():
            return []
        instance = ScheduledJob(**{k: self.cleaned_data.get(k) for k in self.Meta.fields})
        out, after = [], timezone.now()
        try:
            for _ in range(n):
                nxt = instance.compute_next_run(after=after)
                if nxt is None:
                    break
                out.append(nxt)
                after = nxt
        except schedules.ScheduleConfigError:
            return []
        return out
