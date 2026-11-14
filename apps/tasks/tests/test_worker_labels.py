"""Every shipped worker launch site must pass a readable `--worker-id` label.

Downstream-reported from a production migration: the inline worker in
`docker-entrypoint.sh` passed no `--worker-id`, so upstream's 32-char random
default became the label and the heartbeat table read
`oxp0RB1Z85F7X4yFX7IO8Vc1kAedLTER#a1b2c3…` — which tells an operator nothing
about which process that is.

A stable label is *safe* (and has been since v0.23.0): `db_worker` mints a
per-process incarnation `<label>#<token>` and gives that to the queue, so
reusing one label across restarts can't make a dead predecessor's abandoned
task look live. See `TestWorkerIncarnation` in test_reaper.py for that
guarantee — this file only guards that the shipped deployment files actually
take advantage of it.

Why a file-content test: these are shell and YAML, so nothing imports them and
no unit test executes them. A flag dropped during an unrelated edit would
silently restore the unreadable default, and the only symptom would be a
heartbeat table nobody can read — months later, in production.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# (path, the launch line's marker, the label we expect it to carry)
LAUNCH_SITES = [
    ("docker-entrypoint.sh", "manage.py db_worker", "web"),
    ("utils/dev_services.sh", "manage.py db_worker", "dev"),
]


@pytest.mark.parametrize("relpath,marker,label", LAUNCH_SITES)
def test_shipped_worker_launch_passes_a_label(relpath, marker, label):
    text = (REPO_ROOT / relpath).read_text()
    assert marker in text, f"{relpath} no longer starts db_worker — update this test"
    assert "--worker-id" in text, (
        f"{relpath} starts db_worker without --worker-id, so the heartbeat table "
        "falls back to upstream's random 32-char id and becomes unreadable"
    )
    assert label in text, f"{relpath} should default its label to {label!r}"


def test_the_label_is_overridable_per_deployment():
    """One label is right for the single-container default; an operator running
    several workers needs to tell them apart without editing the image."""
    for relpath, _marker, label in LAUNCH_SITES:
        text = (REPO_ROOT / relpath).read_text()
        assert f"${{SMALLSTACK_WORKER_ID:-{label}}}" in text, (
            f"{relpath} should honour SMALLSTACK_WORKER_ID with {label!r} as the default"
        )


def test_the_optional_worker_container_uses_a_distinct_label():
    """config/deploy.yml ships a commented-out separate worker container. If
    someone uncomments it, its label must not collide with the inline one —
    two pools reading as `web` defeats the point of labelling at all."""
    text = (REPO_ROOT / "config/deploy.yml").read_text()
    line = next((ln for ln in text.splitlines() if "manage.py db_worker" in ln), None)
    assert line is not None, "deploy.yml no longer documents a worker container"
    assert "--worker-id" in line, "the documented worker container passes no label"
    assert "web" not in line, "the separate worker must not reuse the inline worker's label"


def test_the_default_labels_are_valid_worker_ids():
    """Upstream validates the label (non-empty, <64 chars) and db_worker raises
    CommandError on a bad one — a shipped default that fails validation would
    stop the container from starting."""
    from django_tasks_db.management.commands.db_worker import validate_worker_id

    for _relpath, _marker, label in LAUNCH_SITES:
        assert validate_worker_id(label) == label


def test_incarnation_keeps_the_label_readable_and_unique():
    """The whole point: the label survives into the worker id as a prefix, so
    the table is scannable, while the token keeps each process distinct."""
    from apps.tasks import heartbeat

    first = heartbeat.new_incarnation("web")
    second = heartbeat.new_incarnation("web")

    assert first.startswith("web")
    assert first != second, "two processes under one label must not collide"
    assert re.fullmatch(r"web.+", first)
    # And it still fits the column upstream validates against.
    assert len(first) < 64
