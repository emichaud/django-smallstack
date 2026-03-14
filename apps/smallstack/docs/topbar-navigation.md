# Topbar Navigation

> **This document covers the legacy settings-based topbar nav.** The topbar now renders from the unified nav registry. See [Navigation System](navigation.md) for the full guide.

## Migration from Settings-Based Topbar Nav

The old system used `SMALLSTACK_TOPBAR_NAV_ENABLED` and `SMALLSTACK_TOPBAR_NAV_ITEMS` in settings. The new system uses the nav registry with `section="topbar"`.

### Before (deprecated)

```python
# settings.py
SMALLSTACK_TOPBAR_NAV_ENABLED = True
SMALLSTACK_TOPBAR_NAV_ITEMS = [
    {"label": "Features", "url": "website:features"},
    {"label": "Docs", "url": "help:index"},
    {"label": "More", "children": [
        {"label": "About", "url": "website:about"},
        {"label": "GitHub", "url": "https://github.com/...", "external": True},
    ]},
]
```

### After (registry-based)

```python
# apps/website/apps.py
from apps.smallstack.navigation import nav

class WebsiteConfig(AppConfig):
    def ready(self):
        # These appear in the topbar instead of "main" items
        nav.register(section="topbar", label="Features", url_name="website:features", order=0)
        nav.register(section="topbar", label="Docs", url_name="help:index", order=1)
        nav.register(section="topbar", label="About", url_name="website:about", parent="More", order=0)
```

```python
# settings.py
SMALLSTACK_TOPBAR_NAV_ALWAYS = True  # show topbar nav even when sidebar is open
```

### Key Differences

| Old System | New System |
|------------|------------|
| Configured in settings (Python dicts) | Registered in AppConfig.ready() |
| Separate from sidebar data | Same registry drives both |
| `SMALLSTACK_TOPBAR_NAV_ENABLED` toggle | `SMALLSTACK_TOPBAR_NAV_ALWAYS` + per-page `{% block topbar_nav_mode %}` |
| `external: True` for external links | Use `url_name` with absolute URLs or external patterns |
| Always visible when enabled | Visibility controlled by sidebar state + settings + template blocks |

### Backward Compatibility

The old settings still work — if `SMALLSTACK_TOPBAR_NAV_ITEMS` has items, they render in a separate `<nav class="topbar-nav">` element. A deprecation warning is logged. Remove the old settings once you've migrated to the registry.
