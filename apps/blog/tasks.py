"""Background work for the blog.

Autodiscovered by the scheduler (it looks for a ``tasks`` module in every
installed app), so nothing else has to import this. ``@scheduled`` is applied
*above* ``@task`` so the wrapped object stays enqueue-able, and the DB
``ScheduledJob`` row is the runtime source of truth — ops can pause or retune
a cadence in ``/smallstack/scheduler/`` without a redeploy.
"""

from __future__ import annotations

import logging

from django.tasks import task

logger = logging.getLogger("smallstack.blog")


@task()
def resync_post_task(post_id: int) -> bool:
    """Pull fresh runbook content into one post. Enqueued by the receiver."""
    from . import service
    from .models import Post

    post = Post.objects.filter(pk=post_id).select_related("source_document").first()
    if post is None:
        return False
    try:
        service.resync_post(post, actor=None)
    except Exception:  # noqa: BLE001 — a failed resync must not retry forever
        logger.exception("blog: resync task failed for post %s", post_id)
        return False
    return True


def _blog_enabled() -> bool:
    """Whether the feature is switched on.

    The ticks check this themselves because the `@scheduled` decorators below
    are applied at **module import**, which the scheduler autodiscovers
    independently of `AppConfig.ready()` — so the ScheduledJob rows exist and
    stay enabled even when `SMALLSTACK_BLOG_ENABLED` is off. Without this guard
    a "disabled" blog went on publishing scheduled posts and would have gone on
    draining queued newsletter sends: the one documented as "no scheduled
    ticks" was the one setting that did not stop them.

    Guarding the task bodies rather than the registration keeps the jobs
    visible in the scheduler UI (so an operator can see they exist and are
    deliberately idle) and means flipping the setting back on needs no
    re-registration.
    """
    from django.conf import settings

    return bool(getattr(settings, "SMALLSTACK_BLOG_ENABLED", True))


@task()
def publish_scheduled_posts() -> list[int]:
    """Publish every scheduled post whose time has come.

    Five minutes, not one: a blog post is not a cron job and a few minutes of
    lateness is invisible, while a tighter cadence just adds wake-ups.
    """
    from . import service

    if not _blog_enabled():
        return []
    return service.publish_due_posts()


@task(queue_name="email")
def newsletter_send_tick() -> list[dict]:
    """Drain in-flight newsletter sends.

    One minute, not five: at the default 100 x 20 that is 2,000 recipients a
    tick, which drains 10,000 in five minutes while keeping each individual
    task well inside the lost-task reaper window. A task that outlives that
    window gets declared lost and retried — which, mid-send, is exactly how a
    blast would go out twice.

    Reaping comes first so a batch orphaned by a dead worker is returned to
    the pool before this run claims anything.
    """
    from . import service

    if not _blog_enabled():
        return []
    reclaimed = service.reap_stale_claims()
    if reclaimed:
        logger.info("blog: returned %s orphaned deliveries to the queue", reclaimed)
    return service.process_sending_issues()


# Scheduling is a soft dependency: the app still works (and the tasks are
# still enqueue-able by hand) in a project that has removed apps.scheduler.
try:
    from apps.scheduler import scheduled

    publish_scheduled_posts = scheduled(  # type: ignore[assignment]
        every="5m", name="Blog: publish scheduled posts"
    )(publish_scheduled_posts)
    newsletter_send_tick = scheduled(  # type: ignore[assignment]
        every="1m", name="Blog: send queued newsletter batches", queue_name="email"
    )(newsletter_send_tick)
except ImportError:  # pragma: no cover - scheduler is installed by default
    logger.debug("blog: scheduler not installed; scheduled publishing is off")


def enqueue_resync(post_id: int) -> None:
    """Queue a resync, falling back to running it inline.

    Runbook's own receiver does the same (``apps/runbook/receivers.py``): a
    project with no worker running should still see its content converge,
    just synchronously. The fallback is safe here because a resync is a single
    row read plus a render — unlike, say, a newsletter blast, which must never
    fall back into a web request.
    """
    from . import service
    from .models import Post

    try:
        resync_post_task.enqueue(post_id=post_id)
        return
    except Exception:  # noqa: BLE001
        logger.debug("blog: task backend unavailable, resyncing inline", exc_info=True)

    post = Post.objects.filter(pk=post_id).first()
    if post is not None:
        try:
            service.resync_post(post, actor=None)
        except Exception:  # noqa: BLE001
            logger.exception("blog: inline resync failed for post %s", post_id)
