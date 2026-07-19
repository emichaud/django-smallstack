"""ScheduledJobForm — validates the cadence fields and previews upcoming runs."""

from __future__ import annotations

from datetime import datetime

from django import forms
from django.utils import timezone

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
            "interval_spec": forms.TextInput(attrs={"placeholder": "5m, 2h, 1d, 90d, 1mo, 1y"}),
            "cron_expression": forms.TextInput(attrs={"placeholder": "0 6 * * *"}),
        }

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
