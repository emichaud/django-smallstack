# Downstream Migration Guide: Self-Contained App Architecture

This document covers what breaks when downstream projects (smallstack_web, opshugger, smallstack-tabler) merge the self-contained app architecture changes from base.

## What Changed in Base

Templates and static files moved from the project root into their respective apps:

| Before (project root) | After (inside app) |
|---|---|
| `templates/smallstack/` | `apps/smallstack/templates/smallstack/` |
| `templates/activity/` | `apps/activity/templates/activity/` |
| `templates/heartbeat/` | `apps/heartbeat/templates/heartbeat/` |
| `templates/usermanager/` | `apps/usermanager/templates/usermanager/` |
| `templates/profile/` | `apps/profile/templates/profile/` |
| `templates/help/` | `apps/help/templates/help/` |
| `templates/registration/` | `apps/accounts/templates/registration/` |
| `templates/accounts/` | `apps/accounts/templates/accounts/` |
| `static/smallstack/` | `apps/smallstack/static/smallstack/` |

Additionally:
- `config/urls.py` now uses `include("apps.smallstack.site_urls")` for all built-in URLs
- Sidebar is data-driven via `apps/smallstack/navigation.py` (apps register in `ready()`)
- Help docs discovery scans installed apps for `help_content_dir` attribute
- SmallStack bundled docs moved from `apps/help/smallstack/` to `apps/smallstack/docs/`

## What Stays at Project Root

These were NOT moved and remain at `templates/` root:
- `website/` (project-specific pages)
- `400.html`, `403.html`, `404.html`, `500.html` (error pages)
- `email/` (email templates)
- `legal/` (legal pages)
- `starter.html`, `starter/` (demo pages)

`static/` root keeps: `robots.txt`, `brand/`, `css/`, `js/` (all project-override dirs).

---

## Predicted Breakage by Project

### smallstack_web

**Severity: HIGH — many merge conflicts, but mechanically simple to resolve.**

smallstack_web has copies of nearly every upstream template in its `templates/` root. After merging, git will see the upstream files deleted from the root and new copies appearing inside apps. The downstream copies at the root will remain as orphans.

**Specific conflicts:**

1. **Template duplicates.** smallstack_web has its own versions of these files at the project root: `activity/`, `heartbeat/`, `usermanager/`, `profile/`, `help/`, `registration/`, `accounts/`, `smallstack/`. After the merge, the upstream-provided copies now live inside apps. The downstream copies at the root will *win* (because `DIRS` beats `APP_DIRS`), which is actually correct — they're downstream overrides. But git will show delete/modify conflicts for every file upstream moved.

2. **`config/urls.py`** — upstream simplified this to use `site_urls`. smallstack_web has its own URL additions (use-cases, roadmap, github). Merge conflict is certain. Resolution: adopt the `site_urls` pattern, keep project-specific routes in `config/urls.py`.

3. **`static/smallstack/`** — upstream moved this into `apps/smallstack/static/smallstack/`. smallstack_web has its own copy at the root. Same resolution as templates: the root copy wins via `STATICFILES_DIRS`, which is fine for overrides. But most files are identical to upstream — delete the root copies for any that aren't customized.

4. **`apps/*/apps.py`** — upstream added `ready()` methods with nav registration. smallstack_web probably has unmodified copies. Should merge cleanly unless smallstack_web added its own `ready()` methods.

5. **`apps/smallstack/context_processors.py`** — upstream added `nav_items`. Should merge cleanly if smallstack_web hasn't modified this.

6. **`apps/help/utils.py`** — upstream rewrote to support per-app help discovery. If smallstack_web has modifications, manual merge needed.

7. **Sidebar** — upstream replaced hardcoded sidebar with registry loop. If smallstack_web customized `smallstack/includes/sidebar.html`, the merge will conflict. Resolution: either adopt the registry sidebar or keep the custom one as a root-level override.

**Recommended merge strategy:**
```bash
git fetch upstream
git merge upstream/main
# Resolve conflicts — for most template files, accept upstream deletion
# and keep the downstream copy at root as an intentional override.
# For files identical to upstream, delete the root copy entirely.
```

### opshugger

**Severity: HIGH — same pattern as smallstack_web.**

opshugger has the same full set of templates at `templates/` root. Same merge pattern.

**Additional concerns:**

1. **Custom branding** in `static/brand/` and `static/images/` — safe, these are at root and won't conflict with the `static/smallstack/` move.

2. **`config/urls.py`** — opshugger has its own routes. Same resolution as smallstack_web.

3. **opshugger may have an `apps/admin_theme/` app** — this won't conflict with upstream changes, but should be evaluated for overlap with the new nav registry.

4. **Custom sidebar** — if opshugger customized sidebar links, the upstream sidebar rewrite will conflict. Keep the custom sidebar at `templates/smallstack/includes/sidebar.html` (root wins over APP_DIRS) or adopt the registry.

**Recommended merge strategy:** Same as smallstack_web. The key decision for both: do you adopt the nav registry or keep custom sidebars? For projects that heavily customized the sidebar, keep the custom version at root. For projects that only changed a few links, adopt the registry and add custom nav items in `apps.py`.

### smallstack-tabler

**Severity: MEDIUM — fewer conflicts because tabler uses a separate base template.**

The tabler project already uses `templates/tabler/base.html` as its base — it doesn't extend `smallstack/base.html`. Most of the upstream template moves are irrelevant because tabler overrides them anyway.

**Specific concerns:**

1. **Templates at root** — tabler has full copies of all upstream templates (activity, heartbeat, help, etc.) changed to `{% extends "tabler/base.html" %}`. These stay at the root and override the APP_DIRS versions. No functional break, but git conflicts during merge.

2. **`config/urls.py`** — merge conflict with `site_urls`. Resolution: adopt `site_urls`.

3. **Sidebar** — tabler doesn't use the sidebar (uses top navbar instead). The upstream sidebar rewrite is irrelevant. The tabler navbar (`templates/tabler/includes/navbar.html`) has hardcoded links — this won't break, but it won't benefit from the nav registry either.

4. **`static/smallstack/`** — tabler still uses `smallstack/js/htmx.min.js`. After the move to `apps/smallstack/static/smallstack/`, the `{% static 'smallstack/js/htmx.min.js' %}` path still resolves correctly via APP_DIRS. No break.

5. **Nav registry** — tabler's navbar is its own HTML, not using the registry. This is fine — tabler can optionally consume `nav_items` from the context to build its navbar dynamically, but it's not required.

---

## Clean Merge Checklist (All Downstream Projects)

After merging upstream:

1. **Delete redundant root templates.** For each file in `templates/<app>/`, check if it's identical to the new `apps/<app>/templates/<app>/` version. If identical, delete the root copy — APP_DIRS will serve the app copy. If customized, keep it at root — DIRS wins.

2. **Delete redundant root static files.** Same check for `static/smallstack/`. If you haven't customized a file, delete the root copy.

3. **Adopt `site_urls.py`.** Update `config/urls.py` to use `include("apps.smallstack.site_urls")` and move project-specific routes after it.

4. **Decide on sidebar/nav.** Either:
   - Keep your custom sidebar at `templates/smallstack/includes/sidebar.html` (root override), or
   - Delete it and let the registry-driven sidebar from APP_DIRS take over, adding custom nav items via `apps.py`

5. **Run `make test`** and verify every page loads.

6. **Check `apps/help/smallstack/`** — if it still exists in your project, delete it. SmallStack docs now live at `apps/smallstack/docs/`.
