# smallstack — framework core

The heart of SmallStack: the CRUDView library (one model → HTML admin + REST + MCP), the
theming/palette system, navigation, the dashboard, displays, and the API/OpenAPI factories.

**Status:** Framework-provided — **don't edit in downstream forks** (upstream merges will
conflict). Extend by subclassing in your own app.

**Key files:** `crud.py` (CRUDView), `api.py` (REST runtime), `openapi.py` (schema),
`displays.py` (list/detail/form renderers), `transforms.py`, `mixins.py`, `pagination.py`,
`templatetags/`.

**See:** [`../../docs/skills/crud-views.md`](../../docs/skills/crud-views.md) ·
[`../../docs/skills/modern-dark-theme.md`](../../docs/skills/modern-dark-theme.md) ·
[`docs/`](docs/) (in-app reference) · repo `CLAUDE.md`.
