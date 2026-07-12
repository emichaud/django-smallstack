# help — bundled docs at `/smallstack/help/`

Renders the Markdown docs under `content/` (and repo `docs/`) as in-app help pages with a table
of contents. Content is filesystem-sourced and searchable via `sync_help_index`.

**Status:** Framework-provided — don't edit the app; add/edit Markdown in `content/`.

**Key files:** `utils.py` (`render_markdown`), `content/`, `views.py`.
**URL:** `/smallstack/help/`.

**See:** [`../../docs/skills/help-documentation.md`](../../docs/skills/help-documentation.md).
