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

### The stock logo follows the theme

While a project still uses SmallStack's own logo files, the logo is **drawn live from the
theme** instead of loaded as an image, so it matches every palette in both themes:

| Piece | Template | Styled by |
|---|---|---|
| The four-square mark (also the sidebar toggle) | `smallstack/includes/brand_mark.html` | `.brand-mark`: all four squares in `--brand-mark`, stepped by opacity |
| The wordmark in the top bar | `smallstack/includes/brand_wordmark.html` | `.brand-word`: "Django" in the bar's text colour, "SmallStack" in `--brand-mark` |
| The full logo on the sign-in pages | `smallstack/includes/brand_lockup.html` | the same two, with `.brand-on-page` |

| Where | `--brand-mark` | Why |
|---|---|---|
| Top bar, dark theme | `var(--primary)` | the bar is near-black, so the logo is the palette's accent |
| Top bar, light theme | `var(--header-fg)` | the bar itself is the accent, so the logo takes the bar's text colour and the two words differ by weight |
| A page's own background (`.brand-on-page`) | `var(--primary)` | the accent reads on the page in both themes |

**Your own logo is untouched.** The context processor sets `brand.wordmark_themed` only while
`BRAND_LOGO_TEXT` is the stock file, and `brand.logo_themed` only while `BRAND_LOGO` and
`BRAND_LOGO_DARK` are. Point any of them at your own file and that image is used, as before.
To keep the stock logo but pin its colour, set `--brand-mark` in your stylesheet.

**As files.** `manage.py brand_logos` writes the same logo for every palette to
`static/smallstack/brand/palettes/` (`logo-<palette>-{dark,light}.svg`,
`icon-<palette>-{dark,light}.svg`), from each palette's `--primary` (`apps/smallstack/brand_logos.py`).
Use those outside the app. The favicon and `BRAND_ICON` (public status and blog pages) are still
single image files and don't change with the palette.

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

Key variables in `static/smallstack/css/core.css` (imported by `theme.css`):

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

1. **Settings**: `BRAND_*` in `config/settings/smallstack.py`, or the same names in the environment
2. **Assets**: `static/brand/` - Add your custom logo files (defaults are in `static/smallstack/brand/`)
3. **Colors**: add a palette (`docs/skills/modify-palettes.md`) rather than editing SmallStack's CSS, which the next upgrade replaces

## Related Documentation

- `/apps/help/docs/customization.md` - Full branding guide
- `/apps/help/docs/theming.md` - CSS theming reference
- `/apps/smallstack/context_processors.py` - Branding context processor
