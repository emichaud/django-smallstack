---
name: api-doctor
description: "Debug API setup + threat signals via /smallstack/api/ (Health + Activity) and python manage.py api_doctor"
license: MIT
metadata:
  source: "docs/skills/api-doctor.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/api-doctor.md` by `make skills-index` — edit the source, not this file.

# API doctor & admin pages — debugging skill

When the user reports "my API isn't working," "Swagger is empty," "I'm seeing weird traffic on `/api/`," or "something's hammering us," start at `/smallstack/api/`. The same checks live in the CLI as `python manage.py api_doctor`.

## When to use this skill

- Setting up SmallStack as an API server for the first time → run Health, fix anything WARN/FAIL
- Swagger / ReDoc unexpectedly empty → check `API registry` card
- A new CRUDView's REST endpoint isn't reachable → check `Orphan files` card
- OpenAPI schema returns 500 or invalid JSON → check `OpenAPI validity` card
- Customer reports a 401 on a request that should work → use the Activity page's filter (IP + user) to confirm what the server saw
- Suspicious traffic in logs → load the Activity page; the threat panel shows the same signals you'd grep for

## Decision tree

```
Issue?
├── Setup-time check (clone-from-source)
│   └── /smallstack/api/  → fix any WARN/FAIL row from the top down
│       └── If running headless: `uv run python manage.py api_doctor --check-only`
│
├── "Swagger is empty" / "no endpoints visible"
│   └── Open /smallstack/api/  →  API registry card
│       ├── 0 endpoints → Add `enable_api = True` to a CRUDView
│       └── Orphan files WARN → That CRUDView's module isn't imported at startup;
│                               add `from . import views` to AppConfig.ready()
│
├── "Spec is broken / Swagger renders nothing"
│   └── OpenAPI validity card → red FAIL shows the validator error
│       └── Reproduce in CLI: `uv run python manage.py api_doctor --no-self-test --json | jq '.[] | select(.name == "OpenAPI validity")'`
│
├── "Customer says they're getting 401s"
│   └── /smallstack/api/activity/
│       ├── Filter by IP or username
│       ├── Check status_class=4xx
│       └── If the token shows is_active=False → see Threat panel "Revoked token use" row
│
└── "Something is hammering us"
    └── /smallstack/api/activity/  → Threat signals card
        ├── HIGH auth-failure burst → grab the IP, block at the edge or revoke the token they're trying
        ├── MEDIUM path scanning   → likely fuzzer; check error rate in the Top endpoints card
        ├── MEDIUM scanner UA      → name of the tool (sqlmap/dirbuster/etc) is in the row
        └── MEDIUM request burst   → 200+ req/min from one IP; same response: edge block
```

## CLI quick reference

```bash
# Same checks as the Health page
uv run python manage.py api_doctor

# Skip the HTTP self-test (faster, no DB write)
uv run python manage.py api_doctor --no-self-test

# Machine-readable for CI
uv run python manage.py api_doctor --json --no-self-test

# Exit non-zero on FAIL — for `make check`-style scripts
uv run python manage.py api_doctor --check-only

# Dump every endpoint with its model + URL name + filters + ordering
uv run python manage.py api_doctor --explain

# Filter to one endpoint
uv run python manage.py api_doctor --explain /api/orders/
```

## What the doctor doesn't do

- It doesn't call `make api-test`. That command hits the *running* HTTP server end-to-end (proxy + middleware + WSGI). The doctor runs in-process via the Django test client. Both have value; the doctor is the fast feedback loop.
- It doesn't *fix* things. WARN rows describe the fix; you apply it.
- It doesn't profile performance. For p95 latency, use the Activity page's Top endpoints card or external APM.

## When NOT to use this skill

- General Django setup issues (those are in `docs/skills/django-apps.md`)
- MCP failures (those are in `docs/skills/mcp/debug-mcp-failure.md` — the parallel module)
- Token management (mint/reveal/revoke) — `docs/skills/manage-api-tokens.md`

## Related

- [`api-documentation.md`](../../apps/smallstack/docs/api-documentation.md) — Swagger / ReDoc / the OpenAPI builder
- [`api-doctor.md`](../../apps/smallstack/docs/api-doctor.md) — user-facing reference
- [`mcp/debug-mcp-failure.md`](mcp/debug-mcp-failure.md) — parallel skill for MCP
