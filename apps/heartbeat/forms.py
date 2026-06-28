"""Forms for the heartbeat app."""

from django import forms

from .models import MaintenanceWindow, MonitoredEndpoint, MonitoredSurface


class MonitoredEndpointForm(forms.ModelForm):
    """CRUD form for a user-created endpoint monitor.

    Two modes (see the custom ``monitoredendpoint_form.html``):

    - **smallstack** — a shortcut: the user enters a SmallStack site's base URL and
      the monitor is configured to ``GET <url>/health/`` expecting 200. Slug is
      auto-generated from the name; the per-device fields stay at their defaults.
    - **custom** — the full field set for an arbitrary device.

    ``service``/``method`` render as segmented button groups (RadioSelect), and the
    model ``clean()`` stays as the SSRF/service backstop. Service choices resolve at
    instantiation so newly registered services appear without a code change.
    """

    MODE_CHOICES = [("smallstack", "SmallStack site"), ("custom", "Custom device")]

    mode = forms.ChoiceField(
        choices=MODE_CHOICES, widget=forms.RadioSelect, initial="smallstack", required=False
    )

    class Meta:
        model = MonitoredEndpoint
        # No ``service`` field: user-created endpoints are external HTTP probes and
        # always land in the "External Monitors" tier (the model default "custom").
        # The internal "Site Monitors" tier is populated by the source picker, not by
        # hand-typing a URL.
        fields = [
            "name",
            "slug",
            "url",
            "method",
            "expected_status",
            "timeout_seconds",
            "enabled",
            "public",
        ]
        widgets = {"method": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False  # auto-generated from the name when blank
        # Editing an existing endpoint always uses the full ("custom") form.
        if self.instance and self.instance.pk:
            self.fields["mode"].initial = "custom"

    def _unique_slug(self, name: str) -> str:
        """A slugified, collision-free slug derived from ``name``."""
        from django.utils.text import slugify

        base = slugify(name) or "endpoint"
        slug = base
        qs = MonitoredEndpoint.objects.all()
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        i = 2
        while qs.filter(slug=slug).exists():
            slug, i = f"{base}-{i}", i + 1
        return slug

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode") or ("custom" if self.instance and self.instance.pk else "smallstack")

        if mode == "smallstack":
            # The URL field holds the site's base URL; monitor /health/ on it.
            base = (cleaned.get("url") or "").strip().rstrip("/")
            if base:
                cleaned["url"] = base + "/health/"
            cleaned["method"] = "GET"
            cleaned["expected_status"] = 200
            cleaned["enabled"] = True

        # service isn't a form field — new endpoints take the model default "custom"
        # (External Monitors); edits keep their existing tag.
        if not cleaned.get("slug") and cleaned.get("name"):
            cleaned["slug"] = self._unique_slug(cleaned["name"])
        # Modified cleaned_data flows into the instance via ModelForm._post_clean.
        return cleaned


class MonitoredSurfaceForm(forms.ModelForm):
    """Picker form for a Site Monitor — choose one currently-exposed surface.

    The ``surface`` choice is populated *live* from
    :func:`apps.heartbeat.surfaces.get_exposed_surfaces` (grouped into API-endpoint
    and MCP-tool optgroups), so you can only pick something that's actually exposed.
    ``kind`` / ``target`` and an auto slug are derived in ``clean()`` from the
    chosen ``"<kind>:<target>"`` value; ``name`` defaults to the surface label.
    """

    surface = forms.ChoiceField(
        label="Surface",
        help_text="An API endpoint or MCP tool this project exposes.",
    )

    class Meta:
        model = MonitoredSurface
        fields = ["name", "enabled", "public"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .surfaces import KIND_LABELS, get_exposed_surfaces, get_surface

        self.fields["name"].required = False  # defaults to the surface label
        self.fields["name"].help_text = "Optional — defaults to the surface name."

        # Build grouped choices from what's exposed right now.
        grouped: dict[str, list] = {}
        for surface in get_exposed_surfaces():
            grouped.setdefault(surface.kind, []).append((surface.value, surface.label))
        choices: list = []
        for kind, label in KIND_LABELS.items():
            if grouped.get(kind):
                choices.append((label, grouped[kind]))

        # Editing: pin the saved surface as the selected value. If it's been
        # deregistered (orphaned), still show it — marked — so the row stays editable.
        if self.instance and self.instance.pk:
            value = f"{self.instance.kind}:{self.instance.target}"
            self.fields["surface"].initial = value
            if get_surface(self.instance.kind, self.instance.target) is None:
                choices.insert(0, ("Orphaned", [(value, f"{self.instance.target} (no longer exposed)")]))
        self.fields["surface"].choices = choices

    def clean(self):
        cleaned = super().clean()
        from .surfaces import get_surface

        selection = cleaned.get("surface") or ""
        kind, _, target = selection.partition(":")
        if not kind or not target:
            self.add_error("surface", "Choose a surface to monitor.")
            return cleaned
        self.instance.kind = kind
        self.instance.target = target

        # Default the display name to the surface label.
        if not cleaned.get("name"):
            surface = get_surface(kind, target)
            cleaned["name"] = surface.label if surface else target
        self.instance.slug = self._unique_slug(cleaned["name"])
        return cleaned

    def _unique_slug(self, name: str) -> str:
        """A slugified, collision-free slug derived from ``name``."""
        from django.utils.text import slugify

        base = slugify(name) or "surface"
        slug = base
        qs = MonitoredSurface.objects.all()
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        i = 2
        while qs.filter(slug=slug).exists():
            slug, i = f"{base}-{i}", i + 1
        return slug


class SLAForm(forms.Form):
    """Form for resetting the SLA epoch and configuring targets."""

    started_at = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                "type": "datetime-local",
                "class": "vTextField",
            }
        ),
        help_text="Start tracking uptime from this date/time.",
    )
    service_target = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        initial=99.9,
        widget=forms.NumberInput(
            attrs={
                "class": "vTextField",
                "step": "0.01",
            }
        ),
        help_text="Internal goal (e.g. 99.9%)",
    )
    service_minimum = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        initial=99.5,
        widget=forms.NumberInput(
            attrs={
                "class": "vTextField",
                "step": "0.01",
            }
        ),
        help_text="Public threshold (e.g. 99.5%)",
    )
    note = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "vTextField",
                "placeholder": "e.g. After server migration",
            }
        ),
        help_text="Optional note for this reset.",
    )


class MaintenanceWindowForm(forms.ModelForm):
    """Form for creating/editing maintenance windows."""

    class Meta:
        model = MaintenanceWindow
        fields = ["title", "start", "end", "note", "exclude_from_sla"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "vTextField"}),
            "start": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "vTextField"}),
            "end": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "vTextField"}),
            "note": forms.Textarea(attrs={"class": "vTextField", "rows": 3}),
            "exclude_from_sla": forms.CheckboxInput(),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        if start and end and end <= start:
            raise forms.ValidationError("End time must be after start time.")
        return cleaned
