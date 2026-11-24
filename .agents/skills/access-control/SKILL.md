---
name: access-control
description: "Read before adding a permission check or declaring a group — Django groups + permissions as the one model, register_group (groups shipped in code, kept in step), every access change recorded to AccessEvent + the log + the account's history, the /smallstack/access/ review (findings, per-user \"why\", exports), register_check, acting_as for directory syncs; REST at /smallstack/api/access/, MCP read tools + a membership proposal an approver decides, manage.py access; directory-managed groups (directory_role); periodic access reviews (attestation: frozen roster → decide → sign, immutable evidence); the evidence pack (/smallstack/access/evidence/: roster, matrix, changes, joiners, leavers, authentication, credentials, findings, reviews → CSV/ZIP/JSON/print, access evidence); the review cadence (a daily @scheduled tick opens the review when a quarter closes, stores the pack with its SHA-256, tells/reminds/escalates the attesters; signing stays human; the access.review.signed webhook event; stored packs, access…"
license: MIT
metadata:
  source: "docs/skills/access-control.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/access-control.md` by `make skills-index` — edit the source, not this file.

# Skill: Access Control — groups, permissions, the audit trail and the review

How SmallStack decides who may do what, records every change to it, and shows
an auditor the result. Read before adding a permission check, declaring a
group, or answering "can X do Y, and why?".

## The model: Django's, with three additions

Access is Django's own: `is_staff` opens the `/smallstack/` area, `is_superuser`
bypasses every check, **Groups** bundle **Permissions**, and `user.has_perm()`
is the one question every page, REST route, MCP tool and `sc` verb asks. There
is no parallel role system. SmallStack adds:

1. **Groups declared in code** (`register_group`), created after `migrate` and
   kept in step, so a role is something you can read in the repository.
2. **A record of every change to access** (`AccessEvent`), written from model
   signals so it doesn't matter which surface made the change.
3. **The Access pages** at `/smallstack/access/`: who holds what and why, a
   least-privilege findings, periodic access reviews, exports, and a
   per-user permission check. (*Findings* are the continuous checks below;
   a *review* is always the periodic attestation a person signs.)

Row-level rules (`get_list_queryset`, `can_update`, `check_object_permission`
on a `CRUDView`) are a separate layer, below this one; see `crud-views.md`.

This skill is long; the full text is in [references/access-control.md](references/access-control.md) — read it before acting.
