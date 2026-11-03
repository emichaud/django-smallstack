"""Metrics, dashboards and reports — the stored layer over ``@dataset``.

Six nouns, each one JSON-friendly row an AI agent can write in one call:

- **Metric** — a named, stored filter over a dataset plus an aggregate: "open
  tickets", "p95 latency this month", "MRR". Its ``filter_tree`` is the text a
  builder, an agent or a person writes (see ``apps.datasets.filter_tree``);
  ``evaluate()`` turns it into one value + a state. The reusable unit — the
  same metric appears on any number of dashboards and reports.
- **Component** — a saved card design: a card type (single stat, grouped stat,
  info card, note, or one an app registers — a chart), the metric it draws and
  the type's options. The component builder makes them; dashboards place them
  by key, and an edit reaches every dashboard that shows it.
- **Dashboard** — a grid of cards. ``layout`` is a list of cells
  (``{id, type, x, y, w, h, metric?, title?, options?}``) on a 12-column grid;
  each cell's ``type`` is a registered component (``components.py``).
- **Report** — a table of metrics evaluated over one or more periods
  ("this month vs last month vs YTD"), on screen and as CSV.
- **Playlist** — dashboards (and goal lists) in a sequence, paged by hand or
  rotated on a timer: a presentation, or a wall screen (``playlists.py``).
- **GoalList** — goals in titled sections: a metric or single stat each,
  judged against a target (on target / at risk / missed) — the list an
  operations meeting reads down (``goals.py``).

Ownership (all six): ``owner`` blank = shared (staff edit, everyone signed in
views); set = personal (the owner edits, staff can view). ``can_view`` /
``can_edit`` are the single rule — views, REST and MCP never re-derive it.
A card additionally shows its number only to users the metric's dataset
admits (``DatasetDef.access``), so a shared dashboard can't leak a staff-only
dataset.

Every model validates in ``save()`` (``full_clean``): a stored filter that
doesn't compile, a cell pointing at a missing metric, or a malformed threshold
is refused on every surface — the form, REST, MCP, the shell.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .metrics import AGGS, AGGS_NEEDING_MEASURE, FORMATS, MetricResult, validate_thresholds


class OwnedQuerySet(models.QuerySet):
    def visible_to(self, user: Any) -> "OwnedQuerySet":
        """What *user* may open: shared rows and their own (staff see all)."""
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_staff", False):
            return self.all()
        return self.filter(models.Q(owner__isnull=True) | models.Q(owner=user))

    def owned_by(self, user: Any) -> "OwnedQuerySet":
        """Only *user*'s personal rows — "my dashboards". Staff get no extra
        rows here: a shared row has no owner to be theirs."""
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        return self.filter(owner=user)

    def mine(self, user: Any) -> "OwnedQuerySet":
        """*user*'s rows: their personal ones plus the shared ones they made
        ("my dashboards" — a staff member's shared dashboards are still theirs)."""
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        return self.filter(models.Q(owner=user) | models.Q(owner__isnull=True, created_by=user))

    def editable_by(self, user: Any) -> "OwnedQuerySet":
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_staff", False):
            return self.filter(models.Q(owner__isnull=True) | models.Q(owner=user))
        return self.filter(owner=user)


class OwnedModel(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="Blank = shared (staff edit, everyone signed in views). Set = personal.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Who made it. Unlike owner it survives sharing, so a shared row stays someone's.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        abstract = True

    def can_view(self, user: Any) -> bool:
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return self.owner_id is None or self.owner_id == user.pk or bool(getattr(user, "is_staff", False))

    def can_edit(self, user: Any) -> bool:
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if self.owner_id is not None:
            return bool(self.owner_id == user.pk)
        return bool(getattr(user, "is_staff", False))

    @property
    def is_shared(self) -> bool:
        return self.owner_id is None

    def save(self, *args: Any, **kwargs: Any) -> None:
        # The one gate: an invalid row never reaches the table, whichever
        # surface wrote it (form, REST, MCP, shell, seed command).
        self.full_clean()
        super().save(*args, **kwargs)


def _visible_to_owner(metric_owner_id: Any, container_owner_id: Any) -> bool:
    """A container (dashboard/report) may reference shared metrics, and its own
    owner's personal ones — never another user's personal metric."""
    return metric_owner_id is None or metric_owner_id == container_owner_id


def free_key(model: type[models.Model], name: str, fallback: str) -> str:
    """A ``key`` made from *name* that *model* doesn't use yet:
    ``"Open tickets"`` → ``open_tickets``, then ``open_tickets_2``."""
    from django.utils.text import slugify

    base = slugify(name).replace("-", "_")[:56].strip("_") or fallback
    key, n = base, 2
    while model._default_manager.filter(key=key).exists():
        key = f"{base}_{n}"
        n += 1
    return key


def metric_key_from_name(name: str) -> str:
    """What a metric gets when it's created without a key — from the builder,
    the API or an agent (:func:`free_key`)."""
    return free_key(Metric, name, "metric")


class Metric(OwnedModel):
    key = models.SlugField(
        max_length=80,
        unique=True,
        help_text="Stable handle used by templates ({% metric_card 'key' %}), dashboards, reports and agents.",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="", help_text="What this number means and why it matters.")
    dataset = models.CharField(max_length=100, help_text="The @dataset key this metric reads.")
    filter_tree = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "The stored filter: a nested AND/OR tree, e.g. "
            '{"and": [{"field": "status", "op": "=", "value": "open"}]}. Empty = every row.'
        ),
    )
    agg = models.CharField("aggregation", max_length=12, choices=AGGS, default="count")
    measure = models.CharField(
        max_length=100, blank=True, default="", help_text="Column to aggregate (not needed for Count rows)."
    )
    period_field = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Date column a dashboard or report period narrows. Blank = the period never applies.",
    )
    format = models.CharField(max_length=12, choices=FORMATS, default="number")
    unit = models.CharField(
        max_length=20, blank=True, default="", help_text="Trailing unit (ms, tickets…), or the currency symbol."
    )
    thresholds = models.JSONField(
        default=list,
        blank=True,
        help_text='Ordered state rules, first match wins: [{"op": ">=", "value": 10, "state": "danger"}].',
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "metric"
        verbose_name_plural = "metrics"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("dashboards_metric_detail", kwargs={"key": self.key})

    def clean(self) -> None:
        from apps.datasets.core import get_dataset

        errors: dict[str, list[str]] = {}
        ds = get_dataset(self.dataset) if self.dataset else None
        if ds is None:
            errors.setdefault("dataset", []).append(f"No dataset named {self.dataset!r} is registered.")
        else:
            col_types = dict(ds.columns())
            declared = ds.declared_measures()
            if self.agg in AGGS_NEEDING_MEASURE and not self.measure:
                errors.setdefault("measure", []).append(f"“{self.get_agg_display()}” needs a column to aggregate.")
            if self.measure:
                if self.measure in declared:
                    pass  # a declared ratio defines its own aggregation
                elif self.measure not in col_types:
                    errors.setdefault("measure", []).append(f"{self.measure!r} is not a column of this dataset.")
                elif self.agg in ("sum", "avg") and col_types[self.measure] not in ("integer", "float", "decimal"):
                    errors.setdefault("measure", []).append(f"{self.measure!r} isn't numeric — it can't be summed.")
            problems = ds.validate_filter_tree(self.filter_tree)
            if problems:
                errors.setdefault("filter_tree", []).extend(problems)
            if self.period_field:
                ftypes = ds.filter_column_types()
                if ftypes.get(self.period_field) not in ("date", "datetime"):
                    errors.setdefault("period_field", []).append(
                        f"{self.period_field!r} is not a filterable date column of this dataset."
                    )
        threshold_problems = validate_thresholds(self.thresholds)
        if threshold_problems:
            errors.setdefault("thresholds", []).extend(threshold_problems)
        if errors:
            raise ValidationError(errors)

    def evaluate(self, request: Any, *, period: str | None = None) -> MetricResult:
        from .metrics import evaluate

        return evaluate(self, request, period=period)

    @property
    def measure_label(self) -> str:
        """The measure column's label in prose case ("response time"), or the
        raw name when the dataset isn't available."""
        from apps.datasets.core import get_dataset

        ds = get_dataset(self.dataset) if self.measure else None
        return ds.column_label(self.measure).lower() if ds is not None else self.measure

    @property
    def filter_summary(self) -> str:
        """The filter's one-line reading ("Status = open AND Created: MTD")."""
        from apps.datasets.core import get_dataset
        from apps.datasets.filter_tree import describe_filter_tree

        ds = get_dataset(self.dataset)
        return describe_filter_tree(self.filter_tree, ds.column_labels() if ds else {})


#: ``Dashboard.system_key`` of the dashboard behind the ``/smallstack/`` page.
ADMIN_HOME_KEY = "smallstack"


class DashboardQuerySet(OwnedQuerySet):
    def visible_to(self, user: Any) -> "DashboardQuerySet":
        """As for any owned row, except a system dashboard (``system_key``)
        is staff-only: it shows the widgets apps publish for operators."""
        qs = super().visible_to(user)
        if not getattr(user, "is_staff", False):
            qs = qs.filter(system_key="")
        return qs  # type: ignore[return-value]


COVER_EXTENSIONS: tuple[str, ...] = ("png", "jpg", "jpeg", "gif", "webp")
MAX_COVER_BYTES = 5 * 1024 * 1024  # 5MB, the blog cover and profile photo limit


def validate_cover_size(image: File) -> None:
    if image.size is not None and image.size > MAX_COVER_BYTES:
        raise ValidationError(f"That image is too large. The limit is {MAX_COVER_BYTES // (1024 * 1024)}MB.")


def cover_upload_to(instance: "Dashboard", filename: str) -> str:
    """A server-chosen name; the uploader's filename is thrown away.

    The same hardening as ``blog.models.cover_upload_to``: keeping a client's
    name once let ``logo.html`` be stored and served as markup (audit C7).
    Covers sit under the public ``/media/`` route like blog covers, so the
    random name is also what keeps a personal dashboard's picture unlisted.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return f"dashboards/covers/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext if ext in COVER_EXTENSIONS else 'bin'}"


class Dashboard(OwnedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, default="")
    cover_image = models.ImageField(
        "picture",
        upload_to=cover_upload_to,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=list(COVER_EXTENSIONS)), validate_cover_size],
        help_text="An image that represents the dashboard in lists. PNG, JPEG, GIF or WebP, up to 5MB.",
    )
    cover_alt = models.CharField(
        "picture description",
        max_length=255,
        blank=True,
        help_text="What the picture shows, for screen readers. Leave blank if it's only decoration.",
    )
    layout = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Cells on a 12-column grid: "
            '[{"id": "c1", "type": "metric", "metric": "open_tickets", "x": 0, "y": 0, "w": 3, "h": 2}]. '
            "Types: see the dashboard component registry."
        ),
    )
    default_period = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Period the dashboard opens with (mtd, last_30, …). Blank = all time.",
    )
    refresh_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(15)],
        help_text="Re-fetch every card on this interval (seconds, ≥ 15). Blank = no auto-refresh.",
    )
    system_key = models.SlugField(
        max_length=40,
        blank=True,
        default="",
        editable=False,
        help_text=(
            'Set on a dashboard a page is built on ("smallstack" = the /smallstack/ page). '
            "Such a dashboard is shared, staff-only, can't be deleted, and gains each newly "
            "published widget (boards.sync_widgets)."
        ),
    )
    offered_widgets = models.JSONField(
        default=list,
        blank=True,
        editable=False,
        help_text="Widget keys sync_widgets has placed once, so a card someone removes stays removed.",
    )

    objects = DashboardQuerySet.as_manager()  # type: ignore[misc]  # narrows OwnedModel.objects

    class Meta:
        ordering = ["name"]
        verbose_name = "dashboard"
        verbose_name_plural = "dashboards"
        constraints = [
            models.UniqueConstraint(
                fields=["system_key"],
                condition=~models.Q(system_key=""),
                name="dashboard_unique_system_key",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        if self.system_key == ADMIN_HOME_KEY:
            return reverse("smallstack_dashboard")
        return reverse("dashboards_dashboard", kwargs={"slug": self.slug})

    def can_view(self, user: Any) -> bool:
        if self.system_key and not getattr(user, "is_staff", False):
            return False
        return super().can_view(user)

    @property
    def is_system(self) -> bool:
        return bool(self.system_key)

    def clean(self) -> None:
        from apps.datasets.dateranges import is_period

        from .components import normalize_layout

        errors: dict[str, list[str]] = {}
        if self.system_key and self.owner_id is not None:
            errors["owner"] = ["A dashboard a page is built on is shared — it can't be personal."]
        if self.default_period and not is_period(self.default_period):
            errors["default_period"] = [f"{self.default_period!r} is not a known period."]
        layout, problems = normalize_layout(self.layout, owner_id=self.owner_id)
        if problems:
            errors["layout"] = problems
        else:
            self.layout = layout
        if errors:
            raise ValidationError(errors)

    def cell(self, cell_id: str) -> dict[str, Any] | None:
        for cell in self.layout if isinstance(self.layout, list) else []:
            if isinstance(cell, dict) and cell.get("id") == cell_id:
                return cell
        return None

    def metric_keys(self) -> set[str]:
        return {c["metric"] for c in self.layout if isinstance(c, dict) and isinstance(c.get("metric"), str)}


class Component(OwnedModel):
    """A saved card: ``type`` (a registered component type), ``metric`` (a
    metric key, for the types that draw one) and the type's ``options``.

    Validated as a one-cell layout, so a component is exactly what a dashboard
    cell would accept. Dashboards place it with ``{"component": key}``;
    ``components.normalize_layout`` copies its definition into the cell, and
    saving a component refreshes every dashboard that shows it
    (``signals.py``). The key is made from the name and never changes."""

    key = models.SlugField(max_length=80, unique=True, help_text="Made from the name; permanent.")
    name = models.CharField(
        max_length=120, help_text="The card's title wherever it's placed (a placement may override it)."
    )
    description = models.TextField(blank=True, default="")
    type = models.CharField(max_length=40, help_text="A registered component type (list_dashboard_components).")
    metric = models.CharField(
        max_length=80, blank=True, default="", help_text="The metric key, for types that draw one."
    )
    options = models.JSONField(default=dict, blank=True, help_text="The type's options (its options_schema).")

    class Meta:
        ordering = ["name"]
        verbose_name = "component"
        verbose_name_plural = "components"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("dashboards/components-update", kwargs={"pk": self.pk})

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Before full_clean (OwnedModel.save), which would refuse a blank key.
        if not self.key and self.name:
            self.key = free_key(Component, self.name, "card")
        super().save(*args, **kwargs)

    def as_cell(self) -> dict[str, Any]:
        """The component as a dashboard cell, ready for ``normalize_layout``."""
        cell: dict[str, Any] = {"type": self.type, "options": self.options or {}}
        if self.metric:
            cell["metric"] = self.metric
        return cell

    def clean(self) -> None:
        from .components import get_component_type, normalize_layout

        if not self.key and self.name:
            self.key = free_key(Component, self.name, "card")
        ct = get_component_type(self.type)
        if ct is None:
            raise ValidationError({"type": [f"{self.type!r} is not a registered component type."]})
        if not ct.needs_metric:
            self.metric = ""
        cell = {**self.as_cell(), "id": "c", "x": 0, "y": 0, "w": ct.default_size[0], "h": ct.default_size[1]}
        normalized, problems = normalize_layout([cell], owner_id=self.owner_id)
        if problems:
            errors: dict[str, list[str]] = {}
            for problem in problems:
                field = "metric" if ".metric" in problem else "type" if ".type" in problem else "options"
                errors.setdefault(field, []).append(problem.replace("layout[0]", "card").replace("card: ", ""))
            raise ValidationError(errors)
        self.options = normalized[0].get("options", {})


class Playlist(OwnedModel):
    """Dashboards shown one after another — paged by hand like slides, or
    rotated on a timer for a wall screen. ``items`` is the sequence:
    ``[{"dashboard": "<slug>", "seconds"?: 5–3600, "period"?: "<key>"|"all"}]``
    (a bare slug is shorthand). The player and its URL options live in
    ``playlists.py``; dashboards renamed or deleted are followed by
    ``signals.py``."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, default="")
    items = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'The dashboards in order: [{"dashboard": "site-health", "seconds": 60, "period": "last_7"}]. '
            "seconds and period are optional (the playlist's dwell, the dashboard's own period)."
        ),
    )
    seconds = models.PositiveIntegerField(
        "seconds per dashboard",
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(3600)],
        help_text="How long each dashboard shows while playing, unless its item says otherwise.",
    )
    loop = models.BooleanField(default=True, help_text="After the last dashboard, start again from the first.")
    auto_start = models.BooleanField(
        default=False,
        help_text="Start playing as soon as the player opens. A link with ?play=0 or ?play=1 overrides it.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "playlist"
        verbose_name_plural = "playlists"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("dashboards_playlist", kwargs={"slug": self.slug})

    def clean(self) -> None:
        from .playlists import normalize_items

        items, problems = normalize_items(self.items, owner_id=self.owner_id)
        if problems:
            raise ValidationError({"items": problems})
        self.items = items

    def dashboard_slugs(self) -> list[str]:
        return [i["dashboard"] for i in self.items if isinstance(i, dict) and isinstance(i.get("dashboard"), str)]

    def goal_list_slugs(self) -> list[str]:
        return [i["goals"] for i in self.items if isinstance(i, dict) and isinstance(i.get("goals"), str)]


class GoalList(OwnedModel):
    """Goals: numbers that boil down to one value each, judged against a
    target — on target, at risk or missed — in titled sections, for reading
    down in an operations meeting. ``sections`` is
    ``[{"title": "Support", "goals": [goal, …]}]`` and a goal is
    ``{"id", "metric"|"component", "label"?, "target": {"op", "value"},
    "warn"?: {"op", "value"}, "period"?, "note"?}``. Validation and evaluation
    live in ``goals.py``; a shared list is the team's, a personal one yours."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, default="")
    sections = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Titled sections of goals: [{"title": "Support", "goals": [{"metric": "open_tickets", '
            '"target": {"op": "<=", "value": 20}, "warn": {"op": "<=", "value": 30}}]}]. '
            "A goal names a metric or a single-stat component; period and label are optional."
        ),
    )
    default_period = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Period the goals are judged over (mtd, last_30, …), unless a goal sets its own. Blank = all time.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "goal list"
        verbose_name_plural = "goal lists"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("dashboards_goals", kwargs={"slug": self.slug})

    def clean(self) -> None:
        from apps.datasets.dateranges import is_period

        from .goals import normalize_sections

        errors: dict[str, list[str]] = {}
        if self.default_period and not is_period(self.default_period):
            errors["default_period"] = [f"{self.default_period!r} is not a known period."]
        sections, problems = normalize_sections(self.sections, owner_id=self.owner_id)
        if problems:
            errors["sections"] = problems
        else:
            self.sections = sections
        if errors:
            raise ValidationError(errors)

    def goals(self) -> list[dict[str, Any]]:
        """Every goal, in reading order across the sections."""
        return [g for s in self.sections if isinstance(s, dict) for g in s.get("goals", []) if isinstance(g, dict)]

    def metric_keys(self) -> set[str]:
        return {g["metric"] for g in self.goals() if isinstance(g.get("metric"), str)}

    def component_keys(self) -> set[str]:
        return {g["component"] for g in self.goals() if isinstance(g.get("component"), str)}


class GoalSnapshot(models.Model):
    """A goal list's values for one week (Monday to Sunday), kept as they were:
    each goal's value, status and the target it was judged against that week,
    so later edits to targets or metrics don't rewrite history — the
    spreadsheet tab, one per week. Taken by the Monday schedule for the week
    just ended, or on demand (``weeks.take_snapshot``)."""

    goal_list = models.ForeignKey(GoalList, on_delete=models.CASCADE, related_name="snapshots")
    week_start = models.DateField(help_text="The Monday the week starts on.")
    rows = models.JSONField(
        default=list,
        blank=True,
        help_text="Each goal that week: id, section, label, metric/component, dataset, value, display, unit, "
        "status, target, warn, target_text, warn_text, note, error.",
    )
    summary = models.JSONField(default=dict, blank=True)
    complete = models.BooleanField(default=False, help_text="Taken after the week ended (not part-way through).")
    taken_at = models.DateTimeField(auto_now=True)
    taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Who took it; blank = the weekly schedule.",
    )

    class Meta:
        ordering = ["-week_start"]
        verbose_name = "goal snapshot"
        verbose_name_plural = "goal snapshots"
        constraints = [models.UniqueConstraint(fields=["goal_list", "week_start"], name="goal_snapshot_one_per_week")]

    def __str__(self) -> str:
        return f"{self.goal_list} — week of {self.week_start:%Y-%m-%d}"


class Report(OwnedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, default="")
    items = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Rows, in order: [{"metric": "open_tickets", "label": "Open tickets", "target": {"op": "<=", "value": 20}, '
            '"warn": {"op": "<=", "value": 30}}] (label, target and warn optional; a target colours each value '
            "on target / at risk / missed)."
        ),
    )
    periods = models.JSONField(
        default=list,
        blank=True,
        help_text='Columns: period keys, e.g. ["mtd", "pmtd", "ytd"]. Empty = one "All time" column.',
    )

    MAX_ITEMS = 200
    MAX_PERIODS = 12

    class Meta:
        ordering = ["name"]
        verbose_name = "report"
        verbose_name_plural = "reports"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("dashboards_report", kwargs={"slug": self.slug})

    def clean(self) -> None:
        from apps.datasets.dateranges import is_period

        from .goals import rule_problems

        errors: dict[str, list[str]] = {}
        items = self.items if self.items not in (None, "") else []
        if not isinstance(items, list):
            errors["items"] = ["items must be a list of {metric, label?} rows"]
        else:
            if len(items) > self.MAX_ITEMS:
                errors.setdefault("items", []).append(f"at most {self.MAX_ITEMS} rows")
            # A bare key string is accepted and normalised to {"metric": key}.
            items = [{"metric": i} if isinstance(i, str) else i for i in items]
            keys = [i.get("metric") for i in items if isinstance(i, dict)]
            owners = dict(
                Metric.objects.filter(key__in=[k for k in keys if isinstance(k, str)]).values_list("key", "owner_id")
            )
            for n, item in enumerate(items):
                where = f"items[{n}]"
                if not isinstance(item, dict) or not isinstance(item.get("metric"), str):
                    errors.setdefault("items", []).append(f"{where}: needs a 'metric' key")
                    continue
                if set(item) - {"metric", "label", "target", "warn"}:
                    errors.setdefault("items", []).append(
                        f"{where}: only 'metric', 'label', 'target' and 'warn' are allowed"
                    )
                for slot in ("target", "warn"):
                    if item.get(slot) in (None, "", {}):
                        item.pop(slot, None)
                    elif problems := rule_problems(item[slot], f"{where}.{slot}"):
                        errors.setdefault("items", []).extend(problems)
                if "warn" in item and "target" not in item:
                    errors.setdefault("items", []).append(f"{where}.warn: an at-risk line needs a target")
                if item["metric"] not in owners:
                    errors.setdefault("items", []).append(f"{where}: no metric with key {item['metric']!r}")
                elif not _visible_to_owner(owners[item["metric"]], self.owner_id):
                    errors.setdefault("items", []).append(f"{where}: {item['metric']!r} is another user's metric")
            self.items = items
        periods = self.periods if self.periods not in (None, "") else []
        if not isinstance(periods, list) or not all(isinstance(p, str) for p in periods):
            errors["periods"] = ["periods must be a list of period keys"]
        else:
            if len(periods) > self.MAX_PERIODS:
                errors.setdefault("periods", []).append(f"at most {self.MAX_PERIODS} periods")
            bad = [p for p in periods if not is_period(p)]
            if bad:
                errors.setdefault("periods", []).append(f"unknown period(s): {', '.join(bad)}")
            self.periods = periods
        if errors:
            raise ValidationError(errors)

    def metric_keys(self) -> list[str]:
        return [i["metric"] for i in self.items if isinstance(i, dict) and isinstance(i.get("metric"), str)]


def metric_usage(metric: Metric, user: Any) -> dict[str, Any]:
    """Where *metric* is used, as *user* can see it: ``{boards: [{obj, cards,
    can_edit}], reports: [{obj, rows, can_edit}], goal_lists: [{obj, goals,
    can_edit}], cards, rows, goals, locked}`` —
    ``locked`` counts the places the user can't edit (they'd keep a broken
    card or row if the metric is deleted)."""
    boards = []
    for d in Dashboard.objects.visible_to(user).order_by("name"):
        n = sum(1 for c in d.layout if isinstance(c, dict) and c.get("metric") == metric.key)
        if n:
            boards.append({"obj": d, "cards": n, "can_edit": d.can_edit(user)})
    reports = []
    for r in Report.objects.visible_to(user).order_by("name"):
        n = r.metric_keys().count(metric.key)
        if n:
            reports.append({"obj": r, "rows": n, "can_edit": r.can_edit(user)})
    goal_lists = []
    for g in GoalList.objects.visible_to(user).order_by("name"):
        n = sum(1 for goal in g.goals() if goal.get("metric") == metric.key)
        if n:
            goal_lists.append({"obj": g, "goals": n, "can_edit": g.can_edit(user)})
    return {
        "boards": boards,
        "reports": reports,
        "goal_lists": goal_lists,
        "cards": sum(b["cards"] for b in boards),
        "rows": sum(r["rows"] for r in reports),
        "goals": sum(g["goals"] for g in goal_lists),
        "locked": sum(1 for x in boards + reports + goal_lists if not x["can_edit"]),
    }


def detach_metric(metric: Metric, user: Any) -> tuple[int, int]:
    """Remove *metric*'s cards and report rows from every dashboard and report
    *user* may edit — so deleting it leaves no "metric no longer exists"
    cards behind; its goals leave the goal lists *user* may edit too (counted
    with the rows). Returns ``(cards_removed, rows_removed)``. Call inside the
    same transaction as the delete."""
    cards = rows = 0
    for d in Dashboard.objects.editable_by(user):
        kept = [c for c in d.layout if not (isinstance(c, dict) and c.get("metric") == metric.key)]
        if len(kept) != len(d.layout):
            cards += len(d.layout) - len(kept)
            d.layout = kept
            d.save()
    for r in Report.objects.editable_by(user):
        kept_items = [i for i in r.items if not (isinstance(i, dict) and i.get("metric") == metric.key)]
        if len(kept_items) != len(r.items):
            rows += len(r.items) - len(kept_items)
            r.items = kept_items
            r.save()
    for g in GoalList.objects.editable_by(user):
        before = len(g.goals())
        g.sections = [
            {**sec, "goals": [x for x in sec.get("goals", []) if x.get("metric") != metric.key]}
            for sec in g.sections
            if isinstance(sec, dict)
        ]
        if len(g.goals()) != before:
            rows += before - len(g.goals())
            g.save()
    return cards, rows
