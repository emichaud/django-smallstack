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
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .metrics import (
    AGGS_NEEDING_MEASURE,
    ALL_AGGS,
    FORMATS,
    MANUAL_AGGS,
    NUMERIC_AGGS,
    MetricResult,
    aggs_available,
    validate_thresholds,
)


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

    def active(self) -> "OwnedQuerySet":
        """Not archived: what lists and pickers show. Anything that *refers*
        to a row (a card drawing a metric) reads it whether archived or not."""
        return self.filter(archived_at__isnull=True)

    def archived(self) -> "OwnedQuerySet":
        return self.filter(archived_at__isnull=False)

    def tagged(self, tag: str) -> "OwnedQuerySet":
        """Rows carrying *tag* — the whole tag, any case; "ops" doesn't match
        "devops"."""
        import re

        tag = tag.strip()
        if not tag:
            return self
        return self.filter(tags__iregex=r"(^|,\s*)" + re.escape(tag) + r"(\s*,|$)")


def tag_cloud(*querysets: Any, current: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """The tags in use across *querysets*, for a row of chips that narrow a
    page: ``[{name, count, current}]``, A to Z. ``count`` is how many rows
    carry the tag, any case counted together. With more than *limit* tags the
    most used are kept; *current* (the tag the page is narrowed to) is always
    there, even when nothing carries it any more."""
    counts: dict[str, list[Any]] = {}
    for qs in querysets:
        for text in qs.exclude(tags="").values_list("tags", flat=True):
            for tag in split_tags(text):
                slot = counts.setdefault(tag.lower(), [tag, 0])
                slot[1] += 1
    wanted = current.strip().lower()
    kept = sorted(counts.values(), key=lambda slot: (-slot[1], slot[0].lower()))[:limit]
    if wanted and not any(slot[0].lower() == wanted for slot in kept):
        kept.append(counts.get(wanted, [current.strip(), 0]))
    kept.sort(key=lambda slot: slot[0].lower())
    return [{"name": name, "count": count, "current": name.lower() == wanted} for name, count in kept]


def split_tags(text: Any) -> list[str]:
    """``"Ops, weekly review, ops"`` → ``["Ops", "weekly review"]``: trimmed,
    empties dropped, repeats (any case) dropped after the first."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(text or "").split(","):
        tag = " ".join(raw.split())
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def join_tags(tags: list[str]) -> str:
    return ", ".join(tags)


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
    tags = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Labels, comma-separated — ops, weekly review. The overviews filter by one.",
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text="Set when archived: out of lists and pickers, still drawn wherever it's referred to.",
    )
    # A default an app ships (defaults.py): which app, its name for it there, the
    # fingerprints of the declaration and of the row as last applied. The row is
    # edited in place like any other; a sync updates it only while it still
    # matches what was applied.
    provided_by = models.CharField(
        max_length=100,
        blank=True,
        default="",
        editable=False,
        help_text="The app that ships this row as a default (blank = made here).",
    )
    provided_key = models.CharField(
        max_length=100,
        blank=True,
        default="",
        editable=False,
        help_text="The default's key or slug as the app declares it.",
    )
    provided_spec = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
        help_text="Fingerprint of the app's declaration last applied; a new one means the app changed its default.",
    )
    provided_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
        help_text="Fingerprint of the row as last applied; a different one now means someone changed it.",
    )
    provided_parked = models.BooleanField(
        default=False,
        editable=False,
        help_text="Archived by the defaults sync because its app is turned off; restored when it's back.",
    )

    objects = OwnedQuerySet.as_manager()

    @property
    def visibility(self) -> str:
        """``shared`` or ``personal``, in the words the forms and tools take."""
        return "personal" if self.owner_id else "shared"

    @property
    def tag_list(self) -> list[str]:
        return split_tags(self.tags)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def set_archived(self, archived: bool) -> None:
        """Archive or restore, saving only that column."""
        self.archived_at = timezone.now() if archived else None
        self.save(update_fields=["archived_at"])

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

    @property
    def is_default(self) -> bool:
        """Shipped by an app (``provided_by``), not made here."""
        return bool(self.provided_by)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # The one gate: an invalid row never reaches the table, whichever
        # surface wrote it (form, REST, MCP, shell, seed command). Archiving or
        # sharing writes only bookkeeping columns, so it isn't refused (a 500)
        # because the row stopped validating since: say a metric it draws went
        # personal. The next real edit still has to fix that.
        update_fields = kwargs.get("update_fields")
        if update_fields is None or not set(update_fields) <= BOOKKEEPING_FIELDS:
            self.full_clean()
        super().save(*args, **kwargs)


#: Columns a save may write without validating the whole row (OwnedModel.save).
BOOKKEEPING_FIELDS = frozenset({"archived_at", "shared_with_everyone", "updated_at"})


def _visible_to_owner(metric_owner_id: Any, container_owner_id: Any) -> bool:
    """A container (dashboard/report) may reference shared metrics, and its own
    owner's personal ones — never another user's personal metric."""
    return metric_owner_id is None or metric_owner_id == container_owner_id


#: The group whose members may change an address, besides superusers.
ADDRESS_ADMIN_GROUP = "admin"


def can_change_address(user: Any) -> bool:
    """Whether *user* may change the address (slug) of an existing dashboard,
    report, playlist or goal list: a superuser, or a member of the ``admin``
    group. Moving a page breaks every bookmark, embed and playlist pointing at
    it, so it's an administrator's call; everyone else sees the address read-only."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return bool(user.groups.filter(name=ADDRESS_ADMIN_GROUP).exists())


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


def free_slug(model: type[models.Model], name: str) -> str:
    """An address (``slug``) made from *name* that *model* doesn't use yet:
    ``"Site health"`` → ``site-health``, then ``site-health-2``. A name with
    nothing a slug can keep (``"!!!"``, or one in another script) takes the
    model's own word: ``dashboard``, ``goal-list``."""
    from django.utils.text import slugify

    base = slugify(name)[:72] or slugify(str(model._meta.verbose_name)) or "page"
    slug, n = base, 1
    while model._default_manager.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def metric_key_from_name(name: str) -> str:
    """What a metric gets when it's created without a key — from the builder,
    the API or an agent (:func:`free_key`)."""
    return free_key(Metric, name, "metric")


SOURCE_DATASET = "dataset"
SOURCE_MANUAL = "manual"
SOURCE_RATE = "rate"
SOURCES = [
    (SOURCE_DATASET, "From a dataset"),
    (SOURCE_MANUAL, "Entered by hand"),
    (SOURCE_RATE, "A rate"),
]
#: The dataset behind every hand-entered metric (see datasets.py).
MANUAL_DATASET = "metric_entries"


class Metric(OwnedModel):
    key = models.SlugField(
        max_length=80,
        unique=True,
        help_text="Stable handle used by templates ({% metric_card 'key' %}), dashboards, reports and agents.",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="", help_text="What this number means and why it matters.")
    source = models.CharField(
        max_length=10,
        choices=SOURCES,
        default=SOURCE_DATASET,
        help_text="Where the number comes from: a dataset, values entered by hand, or one metric divided by another.",
    )
    dataset = models.CharField(
        max_length=100, blank=True, default="", help_text="The @dataset key this metric reads."
    )
    numerator = models.SlugField(
        max_length=80, blank=True, default="", help_text="A rate's top: the key of the metric being divided."
    )
    denominator = models.SlugField(
        max_length=80, blank=True, default="", help_text="A rate's bottom: the key of the metric it's divided by."
    )
    filter_tree = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "The stored filter: a nested AND/OR tree, e.g. "
            '{"and": [{"field": "status", "op": "=", "value": "open"}]}. Empty = every row.'
        ),
    )
    agg = models.CharField("aggregation", max_length=12, choices=ALL_AGGS, default="count")
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

    @property
    def is_manual(self) -> bool:
        return self.source == SOURCE_MANUAL

    @property
    def is_rate(self) -> bool:
        return self.source == SOURCE_RATE

    @property
    def source_label(self) -> str:
        """Where the number comes from, for a table's Source column."""
        from apps.datasets.registry import get_def

        if self.is_manual:
            return "Entered by hand"
        if self.is_rate:
            return "Rate"
        dfn = get_def(self.dataset)
        return str(dfn.label) if dfn is not None else self.dataset

    def read_datasets(self) -> list[str]:
        """Every dataset this number comes from: what a viewer must be able to read."""
        if not self.is_rate:
            return [self.dataset] if self.dataset else []
        parts = Metric.objects.filter(key__in=[self.numerator, self.denominator])
        return sorted({p.dataset for p in parts if p.dataset})

    def normalise_source(self) -> None:
        """Set the fields a source decides, so the rest of the app reads a
        hand-entered metric as an ordinary metric over the entries dataset, and a
        rate as period-aware when its parts are. The filter is fixed to this
        metric's own entries; an unsaved metric matches none rather than all."""
        if self.is_manual:
            self.dataset = MANUAL_DATASET
            self.measure = "value"
            self.period_field = "date"
            self.filter_tree = {"field": "metric", "op": "=", "value": self.pk or 0}
            if self.agg not in {key for key, _label in MANUAL_AGGS}:
                self.agg = "latest"
        elif self.is_rate:
            self.dataset = ""
            self.measure = ""
            self.filter_tree = {}
            self.agg = "count"
            numerator = Metric.objects.filter(key=self.numerator).first()
            self.period_field = numerator.period_field if numerator is not None else ""

    def _clean_rate(self, errors: dict[str, list[str]]) -> None:
        found: dict[str, Metric] = {}
        for name, key in (("numerator", self.numerator), ("denominator", self.denominator)):
            if not key:
                errors.setdefault(name, []).append("Pick a metric.")
                continue
            part = Metric.objects.filter(key=key).first()
            if part is None:
                errors.setdefault(name, []).append(f"No metric with the key {key!r}.")
            elif part.is_rate:
                errors.setdefault(name, []).append("A rate can't be made from another rate. Pick a plain metric.")
            elif not _visible_to_owner(part.owner_id, self.owner_id):
                errors.setdefault(name, []).append(f"“{part.name}” is personal, so a shared rate can't use it.")
            else:
                found[name] = part
        if self.numerator and self.numerator == self.denominator:
            errors.setdefault("denominator", []).append("Pick a different metric: this would always read 1.")
        if len(found) == 2 and bool(found["numerator"].period_field) != bool(found["denominator"].period_field):
            errors.setdefault("denominator", []).append(
                "One of these depends on time and the other doesn't, so they can't be compared for a period."
            )

    def clean(self) -> None:
        from apps.datasets.core import get_dataset

        errors: dict[str, list[str]] = {}
        self.normalise_source()
        if self.is_rate:
            self._clean_rate(errors)
        if self.is_manual or self.is_rate:
            threshold_problems = validate_thresholds(self.thresholds)
            if threshold_problems:
                errors.setdefault("thresholds", []).extend(threshold_problems)
            if errors:
                raise ValidationError(errors)
            return
        if self.agg == "latest":
            errors.setdefault("agg", []).append("“Latest value” is for metrics entered by hand.")
        if not self.dataset:
            errors.setdefault("dataset", []).append("Pick a dataset.")
        ds = get_dataset(self.dataset) if self.dataset else None
        if ds is None:
            if self.dataset:
                errors.setdefault("dataset", []).append(f"No dataset named {self.dataset!r} is registered.")
        else:
            col_types = dict(ds.columns())
            declared = ds.declared_measures()
            if self.agg in AGGS_NEEDING_MEASURE and not self.measure:
                errors.setdefault("measure", []).append(f"“{self.get_agg_display()}” needs a column to aggregate.")
            if self.agg == "median" and "median" not in dict(aggs_available()):
                errors.setdefault("agg", []).append("This database can't compute a median; use the average.")
            if self.measure:
                if self.measure in declared:
                    pass  # a declared ratio defines its own aggregation
                elif self.measure not in col_types:
                    errors.setdefault("measure", []).append(f"{self.measure!r} is not a column of this dataset.")
                elif self.agg in NUMERIC_AGGS and col_types[self.measure] not in ("integer", "float", "decimal"):
                    what = "it has no median" if self.agg == "median" else "it can't be summed"
                    errors.setdefault("measure", []).append(f"{self.measure!r} isn't numeric — {what}.")
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

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.normalise_source()
        super().save(*args, **kwargs)
        if self.is_manual and self.filter_tree.get("value") != self.pk:
            # The filter names this row, whose pk only now exists.
            self.normalise_source()
            type(self).objects.filter(pk=self.pk).update(filter_tree=self.filter_tree)
        # A rate is period-aware when its parts are.
        Metric.objects.filter(source=SOURCE_RATE, numerator=self.key).exclude(period_field=self.period_field).update(
            period_field=self.period_field
        )

    def evaluate(self, request: Any, *, period: str | None = None) -> MetricResult:
        from .metrics import evaluate

        return evaluate(self, request, period=period)

    @property
    def measure_label(self) -> str:
        """The measure column's label in prose case ("response time"), or the
        raw name when the dataset isn't available. A rate has none."""
        from apps.datasets.core import get_dataset

        ds = get_dataset(self.dataset) if self.measure else None
        return ds.column_label(self.measure).lower() if ds is not None else self.measure

    @property
    def filter_summary(self) -> str:
        """The filter's one-line reading ("Status = open AND Created: MTD")."""
        from apps.datasets.core import get_dataset
        from apps.datasets.filter_tree import describe_filter_tree

        if self.is_manual:
            return "Entered by hand"
        if self.is_rate:
            names = dict(Metric.objects.filter(key__in=[self.numerator, self.denominator]).values_list("key", "name"))
            return f"{names.get(self.numerator, self.numerator)} ÷ {names.get(self.denominator, self.denominator)}"
        ds = get_dataset(self.dataset)
        return describe_filter_tree(self.filter_tree, ds.column_labels() if ds else {})


class MetricEntry(models.Model):
    """One hand-entered value of a metric, for one date: CSAT from a survey tool,
    spend from an invoice. The date decides which period and week it counts in."""

    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name="entries")
    date = models.DateField(help_text="The day this value is for.")
    value = models.DecimalField(max_digits=20, decimal_places=4)
    note = models.CharField(max_length=200, blank=True, default="", help_text="Where it came from, or what changed.")
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "metric entry"
        verbose_name_plural = "metric entries"
        constraints = [models.UniqueConstraint(fields=["metric", "date"], name="metric_entry_one_per_day")]

    def __str__(self) -> str:
        return f"{self.metric} on {self.date:%Y-%m-%d}: {self.value}"


#: ``Dashboard.system_key`` of the dashboard behind the ``/smallstack/`` page.
ADMIN_HOME_KEY = "smallstack"


class DashboardQuerySet(OwnedQuerySet):
    def visible_to(self, user: Any) -> "DashboardQuerySet":
        """As for any owned row, plus the personal dashboards shared with
        *user* (with everyone, or with them by name), except that a system
        dashboard (``system_key``) is staff-only: it shows the widgets apps
        publish for operators."""
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_staff", False):
            return self.all()
        return self.filter(
            models.Q(owner__isnull=True)
            | models.Q(owner=user)
            | models.Q(shared_with_everyone=True)
            | models.Q(pk__in=self._shared_by_name(user)),
            system_key="",
        )

    def shared_with_me(self, user: Any) -> "DashboardQuerySet":
        """Other people's personal dashboards *user* may open because they
        were shared: with everyone, or with them by name. Never their own,
        never the ownerless shared ones (those are everyone's already)."""
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        return self.filter(
            models.Q(shared_with_everyone=True) | models.Q(pk__in=self._shared_by_name(user)),
            owner__isnull=False,
            system_key="",
        ).exclude(owner=user)

    def _shared_by_name(self, user: Any) -> Any:
        through = self.model.shared_with.through  # type: ignore[attr-defined]  # Dashboard's M2M
        return through.objects.filter(user=user).values("dashboard_id")


COVER_EXTENSIONS: tuple[str, ...] = ("png", "jpg", "jpeg", "gif", "webp")
MAX_COVER_BYTES = 5 * 1024 * 1024  # 5MB, the blog cover and profile photo limit


def validate_cover_size(image: File) -> None:
    if image.size is not None and image.size > MAX_COVER_BYTES:
        raise ValidationError(f"That image is too large. The limit is {MAX_COVER_BYTES // (1024 * 1024)}MB.")


def cover_upload_to(instance: "Dashboard", filename: str) -> str:
    """A server-chosen name; the uploader's filename is thrown away.

    The same hardening as ``blog.models.cover_upload_to``: keeping a client's
    name once let ``logo.html`` be stored and served as markup.
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
    # Sharing a personal dashboard: the owner keeps editing it; others open it.
    # (An ownerless dashboard is everyone's already, and staff-edited.)
    shared_with_everyone = models.BooleanField(
        default=False,
        help_text="Everyone who can sign in may open this personal dashboard. Its owner still edits it.",
    )
    shared_with = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="+",
        help_text="The people this personal dashboard is shared with by name: they open it, its owner edits it.",
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

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Sharing is the owner's choice: a dashboard changing hands (made
        # shared, or taken personal by someone) starts unshared, rather than
        # bringing back a list a past owner chose.
        new_hands = bool(self.pk) and type(self).objects.filter(pk=self.pk).exclude(owner_id=self.owner_id).exists()
        if new_hands:
            self.shared_with_everyone = False
        super().save(*args, **kwargs)
        if new_hands:
            self.shared_with.clear()

    def get_absolute_url(self) -> str:
        if self.system_key == ADMIN_HOME_KEY:
            return reverse("smallstack_dashboard")
        return reverse("dashboards_dashboard", kwargs={"slug": self.slug})

    def can_view(self, user: Any) -> bool:
        if self.system_key and not getattr(user, "is_staff", False):
            return False
        if super().can_view(user):
            return True
        return self.shared_with_user(user)

    def shared_with_user(self, user: Any) -> bool:
        """Whether *user* may open this personal dashboard because it was
        shared with them (with everyone, or by name) — not because it's theirs."""
        if self.owner_id is None or user is None or not getattr(user, "is_authenticated", False):
            return False
        if self.owner_id == user.pk:
            return False
        if self.shared_with_everyone:
            return True
        return bool(self.pk) and self.shared_with.filter(pk=user.pk).exists()

    @property
    def sharing(self) -> dict[str, Any]:
        """``{everyone, people}`` — who a personal dashboard is shared with,
        as REST reads it (``dashboard_share`` sets it)."""
        people = list(self.shared_with.order_by("username").values_list("username", flat=True)) if self.pk else []
        return {"everyone": bool(self.shared_with_everyone), "people": people}

    @property
    def is_shared_out(self) -> bool:
        """A personal dashboard its owner has shared, with everyone or with anyone."""
        if self.owner_id is None:
            return False
        return self.shared_with_everyone or (bool(self.pk) and self.shared_with.exists())

    def audience(self, user: Any = None) -> str:
        """Who may open it, in a few words for a badge: "Personal", "Shared"
        (ownerless), "Shared with everyone", "Shared with 3 people"; for
        someone it was shared with, "Shared by <owner>"."""
        if self.owner_id is None:
            return "Shared"
        if user is not None and self.shared_with_user(user):
            return f"Shared by {self.owner}"
        if self.shared_with_everyone:
            return "Shared with everyone"
        count = self.shared_with.count() if self.pk else 0
        if count:
            return f"Shared with {count} {'person' if count == 1 else 'people'}"
        return "Personal"

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
    """A saved card: ``type`` (a registered component type), where its numbers
    come from, and the type's ``options``.

    A card that draws data has one of two sources. **A dataset it filters
    itself** (``dataset`` + ``filter_tree`` + ``agg``/``measure`` +
    ``period_field``, the same definition a metric holds) suits every design:
    a stat, a split, a chart. **A metric** (``metric``) suits only the designs
    that show one number (``ComponentType.single_value``): a metric is a
    filtered result rolled up to one value, for goals and thresholds, and a
    chart needs the rows behind it, so it filters a dataset of its own. The
    source's format, unit and colour rules come from ``options.style`` and
    ``options.thresholds``, or from the metric.

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
        max_length=80,
        blank=True,
        default="",
        help_text="The metric key, for a design that shows one number. Otherwise the card filters a dataset.",
    )
    dataset = models.CharField(
        max_length=100, blank=True, default="", help_text="The @dataset key the card filters, when it draws no metric."
    )
    filter_tree = models.JSONField(
        default=dict,
        blank=True,
        help_text="The card's own filter over its dataset (a metric's shape). Empty = all rows.",
    )
    agg = models.CharField("aggregation", max_length=12, choices=ALL_AGGS, default="count", blank=True)
    measure = models.CharField(
        max_length=100, blank=True, default="", help_text="Column to aggregate (not needed for Count rows)."
    )
    period_field = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Date column the dashboard's period narrows and a chart buckets by. Blank = the period never applies",
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

    @property
    def source_label(self) -> str:
        """"Requests (metric)" or "Requests (dataset)", for lists."""
        if self.metric:
            return f"{self.metric} (metric)"
        return f"{self.dataset} (dataset)" if self.dataset else ""

    def as_cell(self) -> dict[str, Any]:
        """The component as a dashboard cell, ready for ``normalize_layout``."""
        cell: dict[str, Any] = {"type": self.type, "options": self.options or {}}
        if self.metric:
            cell["metric"] = self.metric
        elif self.dataset:
            cell["dataset"] = self.dataset
            cell["filter_tree"] = self.filter_tree or {}
            cell["agg"] = self.agg or "count"
            cell["measure"] = self.measure
            cell["period_field"] = self.period_field
        return cell

    def clean(self) -> None:
        from .components import SOURCE_KEYS, get_component_type, normalize_layout

        if not self.key and self.name:
            self.key = free_key(Component, self.name, "card")
        ct = get_component_type(self.type)
        if ct is None:
            raise ValidationError({"type": [f"{self.type!r} is not a registered component type."]})
        if not ct.needs_metric:
            self.metric = ""
            self.dataset = ""
        if self.metric:  # one source: a metric, or a dataset of its own
            self.dataset, self.filter_tree, self.measure, self.period_field = "", {}, "", ""
        cell = {**self.as_cell(), "id": "c", "x": 0, "y": 0, "w": ct.default_size[0], "h": ct.default_size[1]}
        normalized, problems = normalize_layout([cell], owner_id=self.owner_id)
        if problems:
            errors: dict[str, list[str]] = {}
            for problem in problems:
                field = "options"
                for name in ("metric", "type", *SOURCE_KEYS):
                    if f".{name}" in problem:
                        field = name
                        break
                errors.setdefault(field, []).append(problem.replace("layout[0]", "card").replace("card: ", ""))
            raise ValidationError(errors)
        self.options = normalized[0].get("options", {})
        if not self.dataset:
            self.filter_tree, self.agg, self.measure, self.period_field = {}, "count", "", ""


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

    # Deleting a list takes its captures and trackers with it.
    snapshots = GenericRelation("Snapshot", content_type_field="subject_type", object_id_field="subject_id")
    trackers = GenericRelation("SnapshotTracker", content_type_field="subject_type", object_id_field="subject_id")

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


SNAPSHOT_CADENCES = [
    ("hourly", "Hourly"),
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
]


class Snapshot(models.Model):
    """One capture of a subject's values for one period, kept as it was: each goal's
    value, status and the target it was judged against, so later edits to targets or
    metrics don't rewrite history. A period can have several captures; the newest is
    what pages show. Made by ``snapshots.capture``."""

    subject_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    subject_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey("subject_type", "subject_id")
    cadence = models.CharField(max_length=10, choices=SNAPSHOT_CADENCES)
    period_start = models.DateTimeField(help_text="When the period starts.")
    period_end = models.DateTimeField(help_text="When the next period starts.")
    rows = models.JSONField(
        default=list,
        blank=True,
        help_text="Each goal in the period: id, section, label, metric/component, datasets, value, display, unit, "
        "status, target, warn, target_text, warn_text, note, error.",
    )
    summary = models.JSONField(default=dict, blank=True)
    complete = models.BooleanField(default=False, help_text="Taken after the period ended (not part-way through).")
    taken_at = models.DateTimeField(auto_now_add=True)
    taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Who took it; blank = the schedule.",
    )
    reason = models.CharField(
        max_length=60, blank=True, default="", help_text="Why this capture was added, if not by hand or schedule."
    )

    class Meta:
        ordering = ["-period_start", "-taken_at", "-pk"]
        verbose_name = "snapshot"
        verbose_name_plural = "snapshots"
        indexes = [models.Index(fields=["subject_type", "subject_id", "cadence", "period_start"])]

    def __str__(self) -> str:
        return f"{self.subject}: {self.cadence} from {self.period_start:%Y-%m-%d %H:%M}"

    @property
    def week_start(self) -> Any:
        """The local date the period starts: a weekly capture's Monday."""
        return timezone.localtime(self.period_start).date()


class SnapshotTracker(models.Model):
    """One cadence turned on for one subject: the hourly job captures each of its
    periods once it has ended. See ``snapshots.set_tracking``."""

    subject_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    subject_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey("subject_type", "subject_id")
    cadence = models.CharField(max_length=10, choices=SNAPSHOT_CADENCES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "snapshot tracker"
        verbose_name_plural = "snapshot trackers"
        constraints = [
            models.UniqueConstraint(
                fields=["subject_type", "subject_id", "cadence"], name="snapshot_tracker_one_per_cadence"
            )
        ]

    def __str__(self) -> str:
        return f"{self.subject}: {self.cadence}"


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
    for d in Dashboard.objects.visible_to(user).active().order_by("name"):
        n = sum(1 for c in d.layout if isinstance(c, dict) and c.get("metric") == metric.key)
        if n:
            boards.append({"obj": d, "cards": n, "can_edit": d.can_edit(user)})
    reports = []
    for r in Report.objects.visible_to(user).active().order_by("name"):
        n = r.metric_keys().count(metric.key)
        if n:
            reports.append({"obj": r, "rows": n, "can_edit": r.can_edit(user)})
    goal_lists = []
    for g in GoalList.objects.visible_to(user).active().order_by("name"):
        n = sum(1 for goal in g.goals() if goal.get("metric") == metric.key)
        if n:
            goal_lists.append({"obj": g, "goals": n, "can_edit": g.can_edit(user)})
    components = [
        c for c in Component.objects.visible_to(user).active().filter(metric=metric.key).order_by("name")
    ]
    rates = list(
        Metric.objects.visible_to(user)
        .active()
        .filter(source=SOURCE_RATE)
        .filter(models.Q(numerator=metric.key) | models.Q(denominator=metric.key))
        .order_by("name")
    )
    return {
        "rates": rates,
        "boards": boards,
        "reports": reports,
        "goal_lists": goal_lists,
        "components": components,
        "cards": sum(b["cards"] for b in boards),
        "rows": sum(r["rows"] for r in reports),
        "goals": sum(g["goals"] for g in goal_lists),
        "locked": sum(1 for x in boards + reports + goal_lists if not x["can_edit"]),
    }


def usage_index(user: Any) -> dict[str, dict[str, int]]:
    """Where every metric is used, as *user* can see it, in one pass: per
    metric key ``{boards, reports, goal_lists, components, rates, total}``
    (the number of boards, reports, goal lists, saved cards and rates that
    draw it). A key that's used nowhere isn't in the index. For a list of
    metrics, where :func:`metric_usage` per row would scan every board once
    per metric."""
    counts: dict[str, dict[str, int]] = {}

    def hit(key: Any, where: str) -> None:
        if not isinstance(key, str) or not key:
            return
        row = counts.setdefault(key, {"boards": 0, "reports": 0, "goal_lists": 0, "components": 0, "rates": 0})
        row[where] += 1

    # An archived board or report doesn't count: archiving it frees its metrics.
    for d in Dashboard.objects.visible_to(user).active().only("layout", "owner_id", "created_by_id"):
        for key in {c.get("metric") for c in d.layout if isinstance(c, dict)}:
            hit(key, "boards")
    for r in Report.objects.visible_to(user).active().only("items", "owner_id", "created_by_id"):
        for key in set(r.metric_keys()):
            hit(key, "reports")
    for g in GoalList.objects.visible_to(user).active().only("sections", "owner_id", "created_by_id"):
        for key in {goal.get("metric") for goal in g.goals()}:
            hit(key, "goal_lists")
    for key in Component.objects.visible_to(user).active().exclude(metric="").values_list("metric", flat=True):
        hit(key, "components")
    for num, den in (
        Metric.objects.visible_to(user)
        .active()
        .filter(source=SOURCE_RATE)
        .values_list("numerator", "denominator")
    ):
        for key in {num, den}:
            hit(key, "rates")
    for row in counts.values():
        row["total"] = sum(row.values())
    return counts


def same_metrics(user: Any, dataset: str, filter_tree: Any, agg: str, measure: str) -> list[Metric]:
    """The metrics *user* can see that read *dataset* the same way — the same
    conditions, the same aggregate over the same column — so a builder can
    say "you already have this" before another one is saved. The format,
    period column and name may differ; those don't change what's counted."""
    wanted = _canonical_tree(filter_tree or {})
    return [
        m
        for m in Metric.objects.visible_to(user)
        .active()
        .filter(source=SOURCE_DATASET, dataset=dataset, agg=agg or "count", measure=measure or "")
        if _canonical_tree(m.filter_tree or {}) == wanted
    ]


def _canonical_tree(tree: Any) -> Any:
    """*tree* with every number as a float, whether it was stored as a number
    or typed as text ("500" from a quick filter, 500 from the editor), so two
    trees that apply the same way compare equal."""
    if isinstance(tree, dict):
        return {k: _canonical_tree(v) for k, v in sorted(tree.items())}
    if isinstance(tree, list):
        return [_canonical_tree(v) for v in tree]
    if isinstance(tree, bool):
        return tree
    if isinstance(tree, (int, float)):
        return float(tree)
    if isinstance(tree, str):
        try:
            return float(tree)
        except ValueError:
            return tree
    return tree


def detach_metric(metric: Metric, user: Any) -> tuple[int, int]:
    """Remove *metric*'s cards and report rows from every dashboard and report
    *user* may edit — so deleting it leaves no "metric no longer exists"
    cards behind; its goals leave the goal lists *user* may edit too (counted
    with the rows). Returns ``(cards_removed, rows_removed)``. Call inside the
    same transaction as the delete."""
    cards = rows = 0
    # Its saved cards go too: a card with no metric can't be placed or drawn.
    # Their goals are on the same number, so they leave with the metric's own.
    saved_cards = Component.objects.editable_by(user).filter(metric=metric.key)
    saved_keys = set(saved_cards.values_list("key", flat=True))
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
            {
                **sec,
                "goals": [
                    x
                    for x in sec.get("goals", [])
                    if x.get("metric") != metric.key and x.get("component") not in saved_keys
                ],
            }
            for sec in g.sections
            if isinstance(sec, dict)
        ]
        if len(g.goals()) != before:
            rows += before - len(g.goals())
            g.save()
    saved_cards.delete()
    return cards, rows


class RemovedDefault(models.Model):
    """A default someone deleted: the sync never brings it back (unless asked
    to, ``manage.py dashboard_defaults --restore``)."""

    app = models.CharField(max_length=100)
    kind = models.CharField(max_length=20)
    key = models.CharField(max_length=100)
    removed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["app", "kind", "key"], name="removed_default_unique")]

    def __str__(self) -> str:
        return f"{self.app}:{self.kind}:{self.key}"
