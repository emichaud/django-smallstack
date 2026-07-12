"""Seed Runbook's own documentation — as a runbook (dogfooding).

Creates the ``runbook-guide`` runbook with User / Admin / Developer sections and
managed, locked documents. This is the same shape an app developer produces with
``export_runbook`` / ``import_runbook``: ``is_generated`` + a ``source`` label +
``locked`` (superuser to edit). Idempotent — re-run to refresh content in place.

    uv run python manage.py seed_runbook_docs
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.runbook import service
from apps.runbook.models import Runbook, Section

User = get_user_model()

RUNBOOK_SLUG = "runbook-guide"
SOURCE = "runbook-docs"

SECTIONS: list[tuple[str, str, str, int]] = [
    ("User Guide", "user-guide", "Reading, writing, and searching documents.", 0),
    ("Admin Guide", "admin-guide", "Organizing runbooks, versions, retention, and access.", 1),
    ("Developer Guide", "developer-guide", "Driving documents from code, MCP, REST, CLI, and bundles.", 2),
]

# Each doc: (section slug, key, title, doc_type, markdown body).
DOCS: list[tuple[str, str, str, str, str]] = [
    (
        "user-guide", "getting-started", "Getting Started with Runbook", "guide",
        """# Getting Started with Runbook

A **runbook** is a collection of markdown **documents** grouped into **sections**.
Think of it as a small, versioned wiki you can drive from the browser *or* from code.

## The pieces

| Term | What it is |
|---|---|
| Runbook | A named container (a namespace) for related docs, e.g. *Onboarding*. |
| Section | An ordered grouping inside a runbook, e.g. *Operations*. |
| Document | A markdown page with a title, a stable **key**, and full version history. |
| Version | An immutable snapshot of a document's content at a point in time. |

## Finding your way around

- The runbook index lists every runbook with a live preview of its documents.
- Open a runbook to see its sections and documents.
- Every document page shows **breadcrumbs** (Runbook › Section › Document) so you
  always know where you are, and a **version** badge for the current revision.

## Reading a document

Documents render as clean, themed HTML. Images embedded in the markdown display
inline. Use the **Read** view for a distraction-free, full-width reading layout.

Next: [Writing & Editing Documents](writing-documents) and
[Searching & Navigating](search-and-navigation).
""",
    ),
    (
        "user-guide", "writing-documents", "Writing & Editing Documents", "guide",
        """# Writing & Editing Documents

Documents are plain **markdown**, so headings, lists, tables, code blocks, and
links all work the way you expect.

## Creating a document

1. Open a runbook and choose **New Document**.
2. Give it a title — the **key** (its stable address) is derived from the title.
3. Write markdown, or start from a template, then save.

## Editing

Use **Edit content** to change the body. Saving can either update the current
version in place or capture a **new version** — your choice on the edit screen.

## Images

Upload images (up to 10 at once) from the edit screen. Each becomes an embeddable
snippet like `![alt](…)` that you paste where you want it. Images belong to the
document itself, so they survive across every version.

## Versions

Every meaningful save can create a new version. The **version history** lists them
all; you can preview any version and **restore** an older one, which writes it back
as a new current version (nothing is ever lost).

> Managed docs show a **🔒 Managed** badge — those are read-only unless you are a
> superuser. See [Locking & Access Control](../admin-guide/locking-and-access).
""",
    ),
    (
        "user-guide", "search-and-navigation", "Searching & Navigating", "guide",
        """# Searching & Navigating

## Search

The search box matches your terms against each document's **title**,
**description**, and **content** (case-insensitive). Searching for `deploy` finds
every document mentioning deploys, whether the word is in the heading or buried in
a paragraph.

Search is available three ways, all backed by the same query:

- the **Search** page in the UI,
- the REST endpoint `GET api/documents/?q=deploy`,
- the MCP tool `runbook_list_documents(query="deploy")` for AI clients.

## Navigating

- **Breadcrumbs** at the top of every page walk you back up the hierarchy.
- **Sections** group related documents; their order is set by an admin.
- The **runbook index** is the home base — every runbook, each with a preview of
  the documents inside it.

Tip: because a document's **key** is stable, you can bookmark or link to it and the
link keeps working even after the title changes.
""",
    ),
    (
        "admin-guide", "managing-runbooks", "Managing Runbooks & Sections", "guide",
        """# Managing Runbooks & Sections

## Runbooks

Create a runbook for each distinct body of knowledge (onboarding, operations,
a product area). A runbook has a name, a URL **slug**, an optional description and
icon, and retention defaults (see [Versions & Retention](versioning-and-retention)).

## Sections

Sections order documents within a runbook. Give each a name, slug, and an **order**
number (low numbers sort first). Documents without a section still belong to the
runbook — they just appear ungrouped.

## Deleting a runbook

Deleting a runbook asks how to treat its documents:

- **Detach** — keep the documents as standalone, uid-addressable pages (their
  section and key are cleared, their content and history are preserved).
- **Cascade** — delete the documents along with the runbook.

Detach is the safe default: identity lives on the document's **uid**, not on the
runbook, so a document can outlive its container.
""",
    ),
    (
        "admin-guide", "versioning-and-retention", "Versions & Retention", "guide",
        """# Versions & Retention

## Version history

Each document keeps an ordered history of immutable versions. From a document you
can open the **version history**, preview any entry, and **restore** one — restoring
writes the old content back as a new current version, so the timeline only grows.

## Retention

Unbounded history costs storage, so runbooks support **retention** on two axes:

| Axis | Knob | Effect |
|---|---|---|
| Version count | `max_versions` | Keep only the N most recent versions. |
| Version age | `max_version_age_days` | Prune versions older than N days. |
| Document TTL | `ttl_days` | Expire the whole document after N days. |

Policy resolves **document → runbook → global default** (the global default differs
for generated vs. human-authored docs). Pruning runs as a background task on write
plus a periodic sweep, so it never blocks a save.

Managed/generated documents typically want tighter retention than hand-authored
pages — they're regenerated from a source of truth anyway.
""",
    ),
    (
        "admin-guide", "locking-and-access", "Locking & Access Control", "guide",
        """# Locking & Access Control

## Who can do what

- **Staff** can read and edit ordinary documents.
- **Superusers** can additionally edit **locked** documents and toggle the lock.

## Locked (managed) documents

A **locked** document is read-only in the UI, REST, and MCP for everyone except a
superuser. Locked docs show a **🔒 Managed** badge. Locking is how *shipped*
documentation stays authoritative: the content comes from a source of truth (a
bundle, a seed command, or a generator), and casual edits are prevented.

The enforcement lives in the service layer, so **every** transport honors it
identically — a write to a locked doc raises `DocumentLocked`, which the REST API
surfaces as `403` and MCP returns as an error. Authorized syncs (import, seed)
pass an internal `bypass_lock` flag; end users never can.

To edit a managed doc, a superuser **unlocks** it, makes changes, and re-locks — or
edits the source and re-imports. See
[Shipping App Documentation as Bundles](../developer-guide/app-documentation-bundles).
""",
    ),
    (
        "developer-guide", "service-and-transports", "The Document Service & Transports", "guide",
        """# The Document Service & Transports

Every write — browser, MCP, REST, CLI — goes through **one service layer**
(`smallstack_runbook.service`), so versioning, provenance, concurrency, and events
behave identically everywhere.

## The service

```python
from apps.runbook import service

# Idempotent upsert addressed by (runbook, key):
service.put_document("ops", "backup-report", body=md, title="Backup Report",
                     on_exists="overwrite", source="cron")

doc = service.get_document("ops", "backup-report", with_body=True)
hits = service.list_documents(runbook="ops", query="backup")
service.append_to_document("ops", "backup-report", body="\\n- ran at 03:00")
```

`on_exists` chooses the write semantics: `new_version` (default), `overwrite`,
`append`, or `fail`. Pass `expected_version=N` for an optimistic lock.

## Transports (all thin skins over the service)

| Surface | How you call it |
|---|---|
| REST | `GET/PUT/DELETE api/documents/<runbook>/<key>/`, plus `…/append/`, `…/move/`, `…/archive/`, `by-uid/<uid>/`. |
| MCP | Tools `runbook_{list,get,put,append,move,delete}_document`. |
| CLI | The management commands, and anything you script over the service directly. |

## Identity & events

- **uid** is the canonical, container-independent address; `(runbook, key)` is a
  convenient alias. `move_document` re-places a doc without changing its uid.
- Writes emit domain signals on commit — `document_written`, `document_archived`,
  `document_moved`, `document_image_attached` — for subscribers (e.g. notifiers).
""",
    ),
    (
        "developer-guide", "app-documentation-bundles", "Shipping App Documentation as Bundles", "guide",
        """# Shipping App Documentation as Bundles

Author your app's help docs **as a runbook** (rich editor, images, preview), then
ship them as a portable **bundle** that installs into any downstream project.

## The round trip

```bash
# 1. Author in a runbook while developing (edit freely).
# 2. Freeze to a portable ZIP that lives in your app repo:
uv run python manage.py export_runbook my-app-docs --out docs-bundle.zip

# 3. On install (or in CI), hydrate it into the target project:
uv run python manage.py import_runbook docs-bundle.zip --slug my-app-docs
```

The bundle is a ZIP of `manifest.json`, one markdown file per document, and
content-hashed images — image URLs are rewritten to relative refs so the bundle is
database-independent.

## What import does

- Upserts the runbook, sections, and documents **by key** (safe to re-run).
- Marks every doc `is_generated`, stamps a `source`, and **locks** it — the bundle
  is the source of truth, so the installed copy is read-only (superuser to change).
- `--unlock` imports editable copies (for authoring on a dev box).
- `--prune` archives managed docs from the same `source` that are no longer in the
  bundle, so deletions propagate.

## Editing shipped docs

To change managed documentation: import with `--unlock` (or unlock as a superuser),
edit in the runbook UI, then `export_runbook` again and commit the refreshed ZIP.
The lock keeps the *installed* copy authoritative between those authoring passes.

These commands are developer/admin tools (they need shell access), which is exactly
the gate you want: app developers build install docs; end users just read them.
""",
    ),
]


class Command(BaseCommand):
    help = "Seed Runbook's own documentation as a managed, locked runbook (dogfooding)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--unlock", action="store_true",
            help="Seed the docs unlocked (editable) instead of managed/locked.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        locked = not options["unlock"]
        actor = User.objects.filter(is_superuser=True).order_by("pk").first()

        runbook, created = Runbook.objects.get_or_create(
            slug=RUNBOOK_SLUG,
            defaults={
                "name": "Runbook Guide",
                "description": "How to use Runbook — for readers, admins, and developers.",
                "icon": "📘",
            },
        )
        self.stdout.write(f"Runbook {'created' if created else 'exists'}: {runbook.slug}")

        for name, slug, description, order in SECTIONS:
            Section.objects.get_or_create(
                runbook=runbook, slug=slug,
                defaults={"name": name, "description": description, "order": order},
            )

        written = 0
        for section_slug, key, title, doc_type, body in DOCS:
            service.put_document(
                RUNBOOK_SLUG, key,
                body=body,
                title=title,
                section=section_slug,
                on_exists="overwrite",     # refresh in place; no version churn on re-seed
                source=SOURCE,
                via="seed",
                is_generated=True,
                doc_type=doc_type,
                locked=locked,
                actor=actor,
                bypass_lock=True,          # authorized sync (mirrors import_bundle)
            )
            written += 1

        state = "locked/managed" if locked else "unlocked"
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {written} document(s) into '{RUNBOOK_SLUG}' ({state}). "
            f"Browse at /smallstack/runbook/{RUNBOOK_SLUG}/."
        ))
