"""Keep what points at a dashboard in step with it.

- **Its picture:** Django never deletes a ``FileField``'s file, so replacing,
  clearing or deleting a dashboard's picture would leave the old image in
  ``MEDIA_ROOT`` for good. Deletion waits for the commit, so a rolled-back save
  still has its file.
- **Playlists:** they name dashboards by slug, so a renamed dashboard is
  renamed in every playlist and a deleted one leaves them — no playlist is
  left pointing at nothing.
- **Saved cards (Component):** a dashboard cell that places one carries a
  copy of its definition; saving the component refreshes those copies, and
  deleting it leaves them as ordinary cards (keeping its name as the title).
  A goal on a deleted card becomes a goal on the card's metric.
- **Goal lists:** playlists name them by slug too, and follow a rename or a
  delete the same way.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Component, Dashboard, GoalList, Metric, Playlist, Report

logger = logging.getLogger(__name__)


def _delete_file_on_commit(storage: Any, name: str) -> None:
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(pre_save, sender=Dashboard)
def remember_previous_values(sender: type[Dashboard], instance: Dashboard, **kwargs: Any) -> None:
    previous = ("", "")
    if instance.pk:
        previous = Dashboard.objects.filter(pk=instance.pk).values_list("cover_image", "slug").first() or ("", "")
    instance._previous_cover = previous[0] or ""  # type: ignore[attr-defined]
    instance._previous_slug = previous[1] or ""  # type: ignore[attr-defined]


def _rewrite_playlists(slug: str, new_slug: str | None, kind: str = "dashboard") -> None:
    """Point every playlist item for *slug* (a ``dashboard`` or a ``goals``
    list) at *new_slug*, or drop it (``None``). ``update()``, not ``save()``:
    the playlists' other items are untouched and need no re-validation."""
    for playlist in Playlist.objects.all().only("pk", "items"):
        items = playlist.items if isinstance(playlist.items, list) else []
        if not any(isinstance(i, dict) and i.get(kind) == slug for i in items):
            continue
        if new_slug is None:
            kept = [i for i in items if not (isinstance(i, dict) and i.get(kind) == slug)]
        else:
            kept = [{**i, kind: new_slug} if isinstance(i, dict) and i.get(kind) == slug else i for i in items]
        Playlist.objects.filter(pk=playlist.pk).update(items=kept)


@receiver(post_save, sender=Dashboard)
def follow_renamed_dashboard(sender: type[Dashboard], instance: Dashboard, **kwargs: Any) -> None:
    previous = getattr(instance, "_previous_slug", "")
    if previous and previous != instance.slug:
        _rewrite_playlists(previous, instance.slug)
    instance._previous_slug = instance.slug  # type: ignore[attr-defined]


@receiver(post_save, sender=Dashboard)
def delete_replaced_cover(sender: type[Dashboard], instance: Dashboard, **kwargs: Any) -> None:
    previous = getattr(instance, "_previous_cover", "")
    if previous and previous != instance.cover_image.name:
        _delete_file_on_commit(instance.cover_image.storage, previous)
    instance._previous_cover = instance.cover_image.name or ""  # type: ignore[attr-defined]


@receiver(post_delete, sender=Dashboard)
def delete_cover_with_dashboard(sender: type[Dashboard], instance: Dashboard, **kwargs: Any) -> None:
    _delete_file_on_commit(instance.cover_image.storage, instance.cover_image.name or "")


@receiver(post_delete, sender=Dashboard)
def drop_deleted_dashboard_from_playlists(sender: type[Dashboard], instance: Dashboard, **kwargs: Any) -> None:
    _rewrite_playlists(instance.slug, None, kind="dashboard")


def _boards_placing(key: str) -> list[Dashboard]:
    return [
        d
        for d in Dashboard.objects.all()
        if any(isinstance(c, dict) and c.get("component") == key for c in (d.layout or []))
    ]


@receiver(post_save, sender=Component)
def refresh_placed_copies(sender: type[Component], instance: Component, created: bool, **kwargs: Any) -> None:
    """Re-save each dashboard showing the component, so normalize_layout
    copies the new definition in. A dashboard the edit no longer fits (a
    personal metric on a shared board, say) keeps its old copy and is logged."""
    if created:
        return
    from django.core.exceptions import ValidationError

    for board in _boards_placing(instance.key):
        try:
            board.save()
        except ValidationError:
            logger.warning("dashboard %s kept its copy of card %s: the edit doesn't fit it", board.slug, instance.key)


@receiver(post_delete, sender=Component)
def keep_placed_copies_as_cards(sender: type[Component], instance: Component, **kwargs: Any) -> None:
    for board in _boards_placing(instance.key):
        layout = []
        for c in board.layout:
            if isinstance(c, dict) and c.get("component") == instance.key:
                c = {k: v for k, v in c.items() if k not in ("component", "name")}
                c.setdefault("title", instance.name)
            layout.append(c)
        Dashboard.objects.filter(pk=board.pk).update(layout=layout)


@receiver(pre_save, sender=GoalList)
def remember_goal_list_slug(sender: type[GoalList], instance: GoalList, **kwargs: Any) -> None:
    previous = GoalList.objects.filter(pk=instance.pk).values_list("slug", flat=True).first() if instance.pk else ""
    instance._previous_slug = previous or ""  # type: ignore[attr-defined]


@receiver(post_save, sender=GoalList)
def follow_renamed_goal_list(sender: type[GoalList], instance: GoalList, **kwargs: Any) -> None:
    previous = getattr(instance, "_previous_slug", "")
    if previous and previous != instance.slug:
        _rewrite_playlists(previous, instance.slug, kind="goals")
        _rewrite_goal_cards(previous, instance.slug)
    instance._previous_slug = instance.slug  # type: ignore[attr-defined]


@receiver(post_delete, sender=GoalList)
def drop_deleted_goal_list_from_playlists(sender: type[GoalList], instance: GoalList, **kwargs: Any) -> None:
    _rewrite_playlists(instance.slug, None, kind="goals")
    _drop_goal_cards(instance.slug)


def _shows_goal_list(cell: Any, slug: str) -> bool:
    if not isinstance(cell, dict) or cell.get("type") != "goals":
        return False
    opts = cell.get("options")
    return isinstance(opts, dict) and opts.get("goal_list") == slug


def _rewrite_goal_cards(slug: str, new_slug: str) -> None:
    """Point every goals card (placed, or saved as a component) showing *slug*
    at *new_slug* (a renamed list)."""
    for board in Dashboard.objects.all().only("pk", "layout"):
        layout = board.layout if isinstance(board.layout, list) else []
        cells = [c for c in layout if _shows_goal_list(c, slug)]
        for cell in cells:
            cell["options"]["goal_list"] = new_slug
        if cells:
            Dashboard.objects.filter(pk=board.pk).update(layout=layout)
    for card in Component.objects.filter(type="goals"):
        if isinstance(card.options, dict) and card.options.get("goal_list") == slug:
            Component.objects.filter(pk=card.pk).update(options={**card.options, "goal_list": new_slug})


def _drop_goal_cards(slug: str) -> None:
    """Take a deleted list's goals cards off every dashboard, so none is left
    refusing to save over a list that's gone."""
    for board in Dashboard.objects.all().only("pk", "layout"):
        layout = board.layout if isinstance(board.layout, list) else []
        kept = [c for c in layout if not _shows_goal_list(c, slug)]
        if len(kept) != len(layout):
            Dashboard.objects.filter(pk=board.pk).update(layout=kept)


@receiver(post_delete, sender=Component)
def keep_goals_on_the_cards_metric(sender: type[Component], instance: Component, **kwargs: Any) -> None:
    """A goal on a deleted single-stat card keeps going on the card's metric
    (named as the card was), rather than turning into a broken row."""
    for goal_list in GoalList.objects.all().only("pk", "sections"):
        sections = goal_list.sections if isinstance(goal_list.sections, list) else []
        changed = False
        for section in sections:
            for goal in section.get("goals", []) if isinstance(section, dict) else []:
                if isinstance(goal, dict) and goal.get("component") == instance.key:
                    goal.pop("component")
                    goal["metric"] = instance.metric
                    goal.setdefault("label", instance.name)
                    changed = True
        if changed:
            GoalList.objects.filter(pk=goal_list.pk).update(sections=sections)


@receiver(post_save, sender=GoalList)
def start_default_tracking(sender: type[GoalList], instance: GoalList, created: bool, raw: bool, **kwargs: Any) -> None:
    """A new list tracks ``SMALLSTACK_SNAPSHOT_DEFAULT_CADENCES`` until someone changes it."""
    if created and not raw:
        from .snapshots import default_cadences, set_tracking

        set_tracking(instance, default_cadences(), by=instance.created_by)


def remember_removed_default(sender: Any, instance: Any, **kwargs: Any) -> None:
    """A default an app ships was deleted: the defaults sync leaves it deleted."""
    if getattr(instance, "provided_by", ""):
        from .defaults import remember_removed

        remember_removed(instance)


for _model in (Metric, Component, Dashboard, Report, GoalList, Playlist):
    post_delete.connect(remember_removed_default, sender=_model, dispatch_uid=f"remember_removed_{_model.__name__}")
