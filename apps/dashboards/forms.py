"""Forms for metrics, dashboards and reports — the one write gate for the
HTML pages, REST and the generated MCP tools alike (CRUDView builds every
surface's form through ``build_form(..., user=)``, so ``user`` is always here).

Ownership is never a form field: a ``visibility`` choice (``personal`` /
``shared``) decides it, stamped from the requesting user. Only staff may
share. Omitting ``visibility`` on an edit keeps the current setting, so a
partial REST/MCP update can never silently flip a shared dashboard to
personal (or back).
"""

from __future__ import annotations

from typing import Any, cast

from django import forms
from django.urls import reverse
from django.utils import timezone

from apps.datasets.dateranges import RELATIVE_PERIODS, is_period

from .metrics import all_aggs_available
from .models import (
    MANUAL_DATASET,
    SOURCE_DATASET,
    SOURCE_RATE,
    Component,
    Dashboard,
    GoalList,
    Metric,
    Playlist,
    Report,
    free_slug,
    metric_key_from_name,
)

VISIBILITY_CHOICES = [("", "Keep as is"), ("personal", "Personal — only me"), ("shared", "Shared — everyone signed in")]

_JSON_ATTRS = {"rows": 6, "class": "vTextField dash-json", "spellcheck": "false"}


def readable_datasets(user: Any) -> list[tuple[str, str]]:
    """``[(key, label)]`` of the datasets *user* may build metrics on."""
    from apps.datasets.registry import all_defs, user_may_read

    # Hand-entered values are reached by a metric's source, not by building on them.
    usable = (d for d in all_defs() if user_may_read(d, user) and d.key != MANUAL_DATASET)
    return sorted(((d.key, d.label) for d in usable), key=lambda kv: kv[1].lower())


class _OwnedForm(forms.ModelForm):
    """Adds the ``visibility`` field and stamps ``owner`` before model validation
    (``clean()`` runs before ``_post_clean()``/``full_clean``, so the model's
    cross-checks — "is this metric visible to the dashboard's owner?" — see
    the owner the row will actually have)."""

    visibility = forms.ChoiceField(choices=VISIBILITY_CHOICES, required=False)
    # REST and MCP had no way to archive (archived_at is read-only and was
    # silently ignored; DELETE removes the row for good). Hidden on the HTML
    # forms, which have their own Archive button; absent or empty changes nothing.
    archived = forms.NullBooleanField(
        required=False,
        widget=forms.HiddenInput,
        help_text="true archives it (out of lists and pickers, still drawn wherever it's used); false restores it. "
        "Leave it out to keep it as it is.",
    )

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        instance = self.instance
        if instance.pk is None:
            cast(forms.ChoiceField, self.fields["visibility"]).choices = VISIBILITY_CHOICES[1:]
            self.initial.setdefault("visibility", "personal")
        else:
            self.initial.setdefault("visibility", "shared" if instance.owner_id is None else "personal")
        if not getattr(user, "is_staff", False):
            self.fields["visibility"].help_text = "Only staff can share."
        if "tags" in self.fields:
            self.fields["tags"].widget = forms.TextInput(
                attrs={"class": "vTextField", "placeholder": "ops, weekly review", "autocomplete": "off"}
            )
        if "slug" in self.fields:
            # An address is made from the name (clean): nobody has to type one.
            self.fields["slug"].required = False

    def clean_slug(self) -> str:
        """The address of a dashboard, report, playlist or goal list.

        New: whatever was sent (an agent or the API may name one), or blank to
        have ``clean`` make it from the name. Existing: it stays put — renaming
        never moves a page, so links, embeds and playlists keep working — and
        only an administrator may change it on purpose (:func:`can_change_address`)."""
        from .models import can_change_address

        slug = (self.cleaned_data.get("slug") or "").strip()
        instance = self.instance
        if instance.pk is None:
            return slug
        if not slug or slug == instance.slug:
            return str(instance.slug)
        if not can_change_address(self.user):
            raise forms.ValidationError(
                "Only an administrator can change an address. It stays the same when the name changes."
            )
        return slug

    def clean_tags(self) -> str:
        from .models import join_tags, split_tags

        return join_tags(split_tags(self.cleaned_data.get("tags")))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        assert cleaned is not None
        user = self.user
        choice = cleaned.get("visibility") or ""
        instance = self.instance
        if "slug" in self.fields and instance.pk is None and not cleaned.get("slug") and "slug" not in self.errors:
            # Made from the name, like a metric's key: site-health, then site-health-2.
            cleaned["slug"] = free_slug(type(instance), cleaned.get("name") or "")
        if user is None or not getattr(user, "is_authenticated", False):
            raise forms.ValidationError("Sign in to save this.")
        if instance.pk is None:
            choice = choice or "personal"
            instance.created_by = user
        if choice == "shared":
            if not getattr(user, "is_staff", False):
                self.add_error("visibility", "Only staff can share.")
            else:
                instance.owner = None
        elif choice == "personal":
            if instance.pk is None or instance.owner_id is None:
                instance.owner = user  # a new row, or staff taking a shared one personal
            # an existing personal row keeps its owner (only that owner can edit it)
        archived = cleaned.get("archived")
        if archived is not None and archived != instance.is_archived:
            instance.archived_at = timezone.now() if archived else None
        return cleaned


class MetricForm(_OwnedForm):
    # A CharField with a per-user Select widget, not a ChoiceField: the API
    # schema / OpenAPI are built without a user, and an empty choice list
    # there would be an invalid ``enum: []``. clean_dataset is the gate.
    dataset = forms.CharField(
        max_length=100, required=False, help_text="The dataset this metric reads (a @dataset key)."
    )
    numerator = forms.CharField(max_length=80, required=False, help_text="A rate's top: the metric being divided.")
    denominator = forms.CharField(
        max_length=80, required=False, help_text="A rate's bottom: the metric it's divided by."
    )

    class Meta:
        model = Metric
        fields = [
            "name",
            "key",
            "description",
            "source",
            "dataset",
            "numerator",
            "denominator",
            "filter_tree",
            "agg",
            "measure",
            "period_field",
            "format",
            "unit",
            "thresholds",
            "tags",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "vTextField"}),
            "key": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "filter_tree": forms.Textarea(attrs=_JSON_ATTRS),
            "measure": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "period_field": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "unit": forms.TextInput(attrs={"class": "vTextField"}),
            "thresholds": forms.Textarea(attrs={**_JSON_ATTRS, "rows": 3}),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, user=user, **kwargs)
        choices = readable_datasets(user)
        current = self.instance.dataset
        if current and current not in dict(choices):
            choices.append((current, f"{current} (unavailable)"))
        self.fields["dataset"].widget = forms.Select(choices=[("", "— pick a dataset —"), *choices])
        # Callers from before there were sources, and PATCHes, leave it out.
        self.fields["source"].required = False
        parts = [
            (m.key, m.name)
            for m in Metric.objects.visible_to(user).active().exclude(source=SOURCE_RATE).exclude(pk=self.instance.pk)
        ]
        self.fields["numerator"].widget = forms.Select(choices=[("", "— pick a metric —"), *parts])
        self.fields["denominator"].widget = forms.Select(choices=[("", "— pick a metric —"), *parts])
        # An empty JSON container is a legitimate value (no filter / no rules).
        self.fields["filter_tree"].required = False
        self.fields["thresholds"].required = False
        # The key is made from the name when left out, and is permanent after:
        # dashboards, reports and {% metric_card %} refer to the metric by it.
        self.fields["key"].required = False

    def clean_key(self) -> str:
        key = (self.cleaned_data.get("key") or "").strip()
        if self.instance.pk:
            if key and key != self.instance.key:
                raise forms.ValidationError(
                    "A metric's key can't change: dashboards, reports and templates refer to it."
                )
            return self.instance.key
        return key

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("key") and cleaned.get("name"):
            cleaned["key"] = metric_key_from_name(cleaned["name"])
        return cleaned

    def clean_filter_tree(self) -> Any:
        return self.cleaned_data.get("filter_tree") or {}

    def clean_thresholds(self) -> Any:
        return self.cleaned_data.get("thresholds") or []

    def clean_source(self) -> str:
        return self.cleaned_data.get("source") or self.instance.source or SOURCE_DATASET

    def clean_dataset(self) -> str:
        from apps.datasets.registry import get_def, user_may_read

        if self.cleaned_data.get("source") != SOURCE_DATASET:
            return ""  # the model sets it: normalise_source
        key = self.cleaned_data.get("dataset") or ""
        dfn = get_def(key)
        if dfn is None or key == MANUAL_DATASET or not user_may_read(dfn, self.user):
            raise forms.ValidationError("Pick a dataset you can read.")
        return key


class CoverInput(forms.ClearableFileInput):
    """The picture as a thumbnail with Replace / Remove, instead of Django's
    "Currently: <url>" text. Field names (``cover_image``,
    ``cover_image-clear``) are unchanged, so cleaned data is identical."""

    template_name = "dashboards/widgets/cover_input.html"


class DashboardForm(_OwnedForm):
    default_period = forms.ChoiceField(required=False)

    class Meta:
        model = Dashboard
        fields = [
            "name",
            "slug",
            "description",
            "cover_image",
            "cover_alt",
            "default_period",
            "refresh_seconds",
            "layout",
            "tags",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "vTextField"}),
            "slug": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "cover_image": CoverInput(attrs={"accept": "image/png,image/jpeg,image/gif,image/webp"}),
            "cover_alt": forms.TextInput(attrs={"class": "vTextField", "placeholder": "Describe the picture"}),
            "layout": forms.Textarea(attrs=_JSON_ATTRS),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, user=user, **kwargs)
        cast(forms.ChoiceField, self.fields["default_period"]).choices = [("", "All time"), *RELATIVE_PERIODS]
        if self.is_bound and "layout" not in self.data:
            # The settings page has no layout field — cards are arranged on the
            # dashboard. Leaving the field out keeps a save from overwriting a
            # layout changed meanwhile. REST and MCP always send one (PATCH
            # merges the stored layout in).
            del self.fields["layout"]
            return
        self.fields["layout"].required = False
        self.fields[
            "layout"
        ].help_text = (
            "Usually edited on the dashboard itself (Edit layout). The JSON is here for agents and power users: "
            'a list of cells on a 12-column grid, {"id", "type", "x", "y", "w", "h", "title"?, "options"?, '
            '"use_period"?} plus one source: dataset + filter_tree + agg/measure + period_field (the card '
            "filters a dataset of its own), metric (a saved metric's key, single-value designs), or component "
            "(a saved card's key). A write replaces the whole list. Types and their options: "
            "GET /smallstack/dashboards/api/components/."
        )

    def clean_default_period(self) -> str:
        return self.cleaned_data.get("default_period") or ""

    def clean_layout(self) -> Any:
        layout = self.cleaned_data.get("layout")
        if layout is None and self.data.get("layout") in (None, "null") and self.instance.layout:
            # PATCH {"layout": null} answered 200 and removed every card.
            raise forms.ValidationError("layout: null would remove every card; send [] to empty the dashboard.")
        return layout or []

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.instance.system_key:
            # A page is built on it (/smallstack/): it stays shared, whatever was posted.
            self.instance.owner = None
            self.errors.pop("visibility", None)
        return cleaned


class DashboardPictureForm(forms.ModelForm):
    """Just the picture: what the REST picture route and the MCP tool bind, so
    an upload is checked exactly as on the settings page (extension, size,
    and Pillow opening it as an image)."""

    class Meta:
        model = Dashboard
        fields = ["cover_image", "cover_alt"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["cover_image"].required = True


class PeriodsField(forms.MultipleChoiceField):
    """The listed periods as checkboxes, plus any generic ``last_<N>`` /
    ``next_<N>`` an agent sends."""

    def valid_value(self, value: Any) -> bool:
        return is_period(value)


class ReportForm(_OwnedForm):
    periods = PeriodsField(
        choices=RELATIVE_PERIODS,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="One column per period. None = a single “All time” column.",
    )

    class Meta:
        model = Report
        fields = ["name", "slug", "description", "items", "periods", "tags"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "vTextField"}),
            "slug": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "items": forms.Textarea(attrs=_JSON_ATTRS),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, user=user, **kwargs)
        self.fields["items"].required = False

    def clean_items(self) -> Any:
        return self.cleaned_data.get("items") or []

    def clean_periods(self) -> list[str]:
        raw = self.cleaned_data.get("periods") or []
        return list(raw)


class PlaylistForm(_OwnedForm):
    class Meta:
        model = Playlist
        fields = ["name", "slug", "description", "items", "seconds", "loop", "auto_start", "tags"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "vTextField"}),
            "slug": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "items": forms.Textarea(attrs=_JSON_ATTRS),
            "seconds": forms.NumberInput(attrs={"class": "vTextField", "min": 5, "max": 3600}),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, user=user, **kwargs)
        self.fields["items"].required = False

    def clean_items(self) -> Any:
        return self.cleaned_data.get("items") or []


class GoalListForm(_OwnedForm):
    """A goal list. ``sections`` is JSON — the goals editor writes it, agents
    send it; ``GoalList.clean`` (``goals.normalize_sections``) is the gate."""

    default_period = forms.ChoiceField(required=False)

    class Meta:
        model = GoalList
        fields = ["name", "slug", "description", "default_period", "sections", "tags"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "vTextField"}),
            "slug": forms.TextInput(attrs={"class": "vTextField", "spellcheck": "false"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "sections": forms.HiddenInput(),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, user=user, **kwargs)
        cast(forms.ChoiceField, self.fields["default_period"]).choices = [("", "All time"), *RELATIVE_PERIODS]
        self.fields["sections"].required = False

    def clean_sections(self) -> Any:
        return self.cleaned_data.get("sections") or []


class AddGoalForm(forms.Form):
    """One goal for a metric or a single-stat card, added to a section of a
    goal list the user may edit — the "Add to goals" dialog."""

    goal_list = forms.ChoiceField(label="Goal list")
    section = forms.CharField(
        max_length=120, required=False, help_text="A section of the list, or a new one. Blank = the end of the list."
    )
    label = forms.CharField(max_length=120, required=False, help_text="Blank = the metric's or card's name.")
    op = forms.ChoiceField(label="Target", choices=[])
    value = forms.FloatField(required=False)
    value2 = forms.FloatField(required=False, label="and")
    warn_op = forms.ChoiceField(label="At risk", required=False, choices=[])
    warn_value = forms.FloatField(required=False)
    warn_value2 = forms.FloatField(required=False, label="and")
    period = forms.ChoiceField(required=False, help_text="Blank = the goal list's period.")
    note = forms.CharField(max_length=280, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    OPS = [
        (">=", "at least (≥)"),
        (">", "more than (>)"),
        ("<=", "at most (≤)"),
        ("<", "less than (<)"),
        ("=", "exactly (=)"),
        ("!=", "not (≠)"),
        ("between", "between"),
    ]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from .goals import goal_list_choices

        for name in ("op", "warn_op", "period"):
            self.fields[name].widget.attrs["class"] = "vTextField"

        self.user = user
        self.lists = goal_list_choices(user)
        cast(forms.ChoiceField, self.fields["goal_list"]).choices = [
            (g["slug"], g["name"] + ("" if g["shared"] else " (personal)")) for g in self.lists
        ]
        cast(forms.ChoiceField, self.fields["op"]).choices = self.OPS
        cast(forms.ChoiceField, self.fields["warn_op"]).choices = [("", "No at-risk line"), *self.OPS]
        cast(forms.ChoiceField, self.fields["period"]).choices = [
            ("", "The list's period"),
            ("all", "All time"),
            *RELATIVE_PERIODS,
        ]

    def _rule(self, op: str, value: Any, value2: Any, field: str) -> dict[str, Any] | None:
        if not op:
            return None
        if value is None:
            self.add_error(field, "Enter a number.")
            return None
        if op == "between":
            if value2 is None:
                self.add_error(f"{field}2", "Enter the upper number.")
                return None
            return {"op": op, "value": [value, value2]}
        return {"op": op, "value": value}

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        assert cleaned is not None
        cleaned["target"] = self._rule(cleaned.get("op") or "", cleaned.get("value"), cleaned.get("value2"), "value")
        cleaned["warn"] = self._rule(
            cleaned.get("warn_op") or "", cleaned.get("warn_value"), cleaned.get("warn_value2"), "warn_value"
        )
        return cleaned

    def chosen_list(self) -> GoalList:
        return GoalList.objects.editable_by(self.user).get(slug=self.cleaned_data["goal_list"])

    def goal(self, source: str, key: str) -> dict[str, Any]:
        data = self.cleaned_data
        goal: dict[str, Any] = {source: key, "target": _whole(data["target"])}
        if data.get("warn"):
            goal["warn"] = _whole(data["warn"])
        for name in ("label", "period", "note"):
            if data.get(name):
                goal[name] = data[name]
        return goal


def _whole(rule: dict[str, Any]) -> dict[str, Any]:
    """A rule's numbers as ints where they are whole (95.0 → 95), so the
    stored JSON reads the way it was typed."""

    def tidy(v: float) -> float | int:
        return int(v) if float(v).is_integer() else v

    value = rule["value"]
    return {"op": rule["op"], "value": [tidy(v) for v in value] if isinstance(value, list) else tidy(value)}


def goal_editor_data(user: Any, owner_id: Any) -> dict[str, Any]:
    """What the goals editor offers: the metrics and one-number cards a list
    owned by *owner_id* may hold (shared ones, and the owner's), with each
    metric's format and a suggested target; the operators; the periods."""
    from django.db.models import Q

    from .components import get_component_type
    from .goals import scales_with_time, suggest_target

    allowed = Q(owner__isnull=True) | Q(owner_id=owner_id) if owner_id else Q(owner__isnull=True)
    metrics = list(Metric.objects.visible_to(user).active().filter(allowed).order_by("name"))
    by_key = {m.key: m for m in metrics}
    cards = []
    for c in Component.objects.visible_to(user).active().filter(allowed).order_by("name"):
        ct = get_component_type(c.type)
        if ct is not None and ct.single_value and c.metric:
            m = by_key.get(c.metric)
            cards.append(
                {
                    "key": c.key,
                    "name": c.name,
                    "metric": c.metric,
                    "shared": c.owner_id is None,
                    "format": ((c.options or {}).get("style") or {}).get("format") or (m.format if m else "number"),
                    "unit": ((c.options or {}).get("style") or {}).get("unit") or (m.unit if m else ""),
                    "scales": scales_with_time(m),
                }
            )
    return {
        "metrics": [
            {
                "key": m.key,
                "name": m.name,
                "shared": m.owner_id is None,
                "format": m.format,
                "unit": m.unit,
                "suggest": suggest_target(m),
                "scales": scales_with_time(m),
            }
            for m in metrics
        ],
        "cards": cards,
        "ops": [[k, label] for k, label in AddGoalForm.OPS],
        "periods": [["all", "All time"], *[[k, str(label)] for k, label in RELATIVE_PERIODS]],
    }


def playlist_dashboard_choices(user: Any) -> list[dict[str, Any]]:
    """The dashboards a playlist editor may pick from: every one *user* can
    open, flagged ``shared`` so the editor can offer only shared ones to a
    shared playlist (``normalize_items`` enforces the same rule)."""
    return [
        {"slug": d.slug, "name": d.name, "shared": d.owner_id is None, "mine": d.owner_id == getattr(user, "pk", None)}
        for d in Dashboard.objects.visible_to(user).active().order_by("name")
        if d.owner_id is None or d.owner_id == getattr(user, "pk", None)
    ]


def playlist_goal_choices(user: Any) -> list[dict[str, Any]]:
    """The goal lists a playlist editor may pick from, flagged like
    :func:`playlist_dashboard_choices`."""
    return [
        {"slug": g.slug, "name": g.name, "shared": g.owner_id is None, "mine": g.owner_id == getattr(user, "pk", None)}
        for g in GoalList.objects.visible_to(user).active().order_by("name")
        if g.owner_id is None or g.owner_id == getattr(user, "pk", None)
    ]


class ComponentForm(_OwnedForm):
    """A saved card. The key is made from the name (``Component.clean``);
    ``options`` is the type's options as JSON — the builder writes it, agents
    send it. The source is a metric (``metric``) or the card's own
    (``dataset`` + ``filter_tree`` + ``agg``/``measure`` + ``period_field``):
    the builder draws the dataset picker, the filter editor and the roll-up
    over these fields, as the metric form does (component-builder.js)."""

    class Meta:
        model = Component
        fields = [
            "name", "description", "type", "metric", "dataset", "filter_tree", "agg", "measure", "period_field",
            "options", "tags",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "vTextField"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "vTextField"}),
            "options": forms.HiddenInput(),
            "filter_tree": forms.HiddenInput(),
            "dataset": forms.Select(attrs={"class": "vTextField", "id": "cb-dataset"}),
            "agg": forms.Select(attrs={"class": "vTextField", "id": "cb-agg"}),
            "measure": forms.HiddenInput(attrs={"id": "cb-measure"}),
            "period_field": forms.HiddenInput(attrs={"id": "cb-period-field"}),
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, user=user, **kwargs)
        from .components import component_types

        types = [(ct.key, ct.label) for ct in component_types() if ct.visible_to is None or ct.visible_to(user)]
        current = self.instance.type
        if current and current not in dict(types):
            types.append((current, f"{current} (unavailable)"))
        self.fields["type"].widget = forms.Select(choices=types)
        for name in ("metric", "options", "dataset", "filter_tree", "agg", "measure", "period_field"):
            self.fields[name].required = False
        datasets = readable_datasets(user)
        current_ds = self.instance.dataset or (self.initial.get("dataset") or "")
        if current_ds and current_ds not in dict(datasets):
            datasets.append((current_ds, f"{current_ds} (unavailable)"))
        self.fields["dataset"].widget.choices = [("", "Choose a dataset…"), *datasets]
        self.fields["agg"].widget.choices = [(k, label) for k, label in all_aggs_available() if k != "latest"]

    def clean_filter_tree(self) -> Any:
        tree = self.cleaned_data.get("filter_tree")
        return tree if isinstance(tree, dict) else {}

    def clean_dataset(self) -> str:
        key = self.cleaned_data.get("dataset") or ""
        if key and key not in dict(readable_datasets(self.user)):
            raise forms.ValidationError("Pick a dataset you can read.")
        return key

    def clean_type(self) -> str:
        from .components import get_component_type

        key = self.cleaned_data.get("type") or ""
        ct = get_component_type(key)
        if ct is None or (ct.visible_to is not None and not ct.visible_to(self.user)):
            raise forms.ValidationError("Pick a card type you can use.")
        return key

    def clean_options(self) -> Any:
        return self.cleaned_data.get("options") or {}


def builder_payload(user: Any, owner_id: Any) -> dict[str, Any]:
    """What the component builder offers *user*: the card types (with the
    dataset capabilities each needs), the datasets *user* may filter (with
    their capabilities), the metrics a card owned by *owner_id* may draw
    (shared ones and the owner's) with their datasets' capabilities and their
    definitions (a chart can start from a metric's filter), and — for staff —
    the published widgets."""
    from apps.datasets.capabilities import REASONS, capabilities
    from apps.datasets.core import get_dataset

    from .components import components_payload

    payload = components_payload(user)
    payload["types"] = [t for t in payload["types"] if not t.get("staff_only") or getattr(user, "is_staff", False)]
    from django.db.models import Q

    caps: dict[str, list[str]] = {}

    def caps_of(key: str) -> list[str]:
        if key not in caps:
            ds = get_dataset(key)
            try:
                caps[key] = sorted(capabilities(ds.schema())) if ds is not None else []
            except Exception:  # noqa: BLE001 — a broken dataset greys its cards out, it doesn't break the page
                caps[key] = []
        return caps[key]

    payload["datasets"] = [
        {"key": key, "label": label, "caps": caps_of(key), "access": _dataset_access(key)}
        for key, label in readable_datasets(user)
    ]
    allowed = Q(owner__isnull=True) | Q(owner_id=owner_id) if owner_id else Q(owner__isnull=True)
    metrics = Metric.objects.visible_to(user).active().filter(allowed)
    out = []
    for m in metrics.order_by("name"):
        caps_of(m.dataset)
        # Hand-entered values and rates have dates but nothing to group by. A
        # date column is only any use to a chart over time when the metric is
        # read over it: the period field, set on the metric's form.
        dataset_caps = caps[m.dataset] if m.source == SOURCE_DATASET else ["date"]
        out.append(
            {
                "key": m.key,
                "name": m.name,
                "dataset": m.dataset,
                "caps": dataset_caps if m.period_field else [c for c in dataset_caps if c != "date"],
                "no_period": "date" in dataset_caps and not m.period_field,
                "edit_url": reverse("dashboards/metrics-update", kwargs={"pk": m.pk}) if m.can_edit(user) else "",
                "shared": m.owner_id is None,
                "thresholds": m.thresholds or [],
                "format": m.format,
                "unit": m.unit,
                # Its definition, for a card that starts from this metric's filter
                # and goes on to filter the dataset itself (a chart).
                "definition": {
                    "dataset": m.dataset,
                    "filter_tree": m.filter_tree or {},
                    "agg": m.agg,
                    "measure": m.measure,
                    "period_field": m.period_field,
                }
                if m.source == SOURCE_DATASET
                else None,
            }
        )
    payload["metrics"] = out
    payload["reasons"] = dict(REASONS)  # why a design is dimmed: "needs a date column"
    payload["aggs"] = [[k, label] for k, label in all_aggs_available() if k != "latest"]
    return payload


def _dataset_access(key: str) -> str:
    """"staff" or "auth": who may read the dataset, for the picker's note."""
    from apps.datasets.registry import get_def

    dfn = get_def(key)
    return str(getattr(dfn, "access", "") or "") if dfn is not None else ""
