---
name: branding
description: "Brand assets — the BRAND_ logo/icon/favicon settings, sizes and formats, where upstream defaults vs. a downstream's own files live"
license: MIT
metadata:
  source: "docs/skills/branding.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/branding.md` by `make skills-index` — edit the source, not this file.

# SmallStack Branding & Theming

## Logo Specifications

### Topbar Logo (`BRAND_LOGO_TEXT`)
- **Display height**: 32px (set in `static/smallstack/css/theme.css` at `.site-logo .logo-img`)
- **Format**: SVG recommended
- **Background**: Dark topbar, so use white/light text
- **Default location**: `static/smallstack/brand/` (upstream defaults)
- **Custom location**: `static/brand/` (downstream project overrides)

### Logo Sizes Reference

| Setting | Purpose | Size | Format |
|---------|---------|------|--------|
| `BRAND_LOGO_TEXT` | Topbar | 32px height | SVG |
| `BRAND_LOGO` | Marketing pages | 40-60px height | SVG |
| `BRAND_LOGO_DARK` | Dark backgrounds | 40-60px height | SVG |
| `BRAND_ICON` | Small spaces | 32-48px square | SVG |
| `BRAND_FAVICON` | Browser tab | 32x32, 16x16 | ICO |
| `BRAND_SOCIAL_IMAGE` | Social previews | 1200x630px | PNG |

## Creating a Text Logo SVG

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 28">
  <text x="0" y="22" font-family="Segoe UI, system-ui, sans-serif" font-size="22" font-weight="600">
    <tspan fill="#ffffff">Your </tspan>
    <tspan fill="#4FD1A5">Brand</tspan>
  </text>
</svg>
```

- Adjust `viewBox` width based on text length
- Use white (`#ffffff`) for dark topbar background
- Add colored accent using your brand color

## Branding Settings

Settings are in `config/settings/base.py`:

```python
BRAND_NAME = "My Project"
BRAND_LOGO_TEXT = "brand/my-logo-text.svg"
BRAND_LOGO = "brand/my-logo.svg"
BRAND_LOGO_DARK = "brand/my-logo-dark.svg"
BRAND_ICON = "brand/my-icon.svg"
BRAND_FAVICON = "brand/my-icon.ico"
BRAND_SOCIAL_IMAGE = "brand/my-social.png"
BRAND_TAGLINE = "Your project tagline"
```

## CSS Variables for Theming

Key variables in `static/smallstack/css/theme.css`:

```css
:root {
    --topbar-height: 56px;
    --sidebar-width: 250px;
    --primary: #417690;
    --primary-hover: #205067;
}
```

## Template Access

Branding is available in all templates via `brand` context:

```html
{% load static %}
<img src="{% static brand.logo_text %}" alt="{{ brand.name }}">
{{ brand.name }}
{{ brand.tagline }}
```

## Files to Modify for Rebranding

1. **Settings**: `config/settings/base.py` - Update `BRAND_*` settings
2. **Assets**: `static/brand/` - Add your custom logo files (defaults are in `static/smallstack/brand/`)
3. **Colors**: `static/smallstack/css/theme.css` - Update CSS variables (or add overrides in `static/css/project.css`)

## Related Documentation

- `/apps/help/docs/customization.md` - Full branding guide
- `/apps/help/docs/theming.md` - CSS theming reference
- `/apps/smallstack/context_processors.py` - Branding context processor
