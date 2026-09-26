---
title: Theme Architecture
description: How the modern-dark theme system works — variables, palettes, color science
---

# Theme Architecture

The post-v0.9.x SmallStack theme system. How variables cascade, why palettes look the way they do, and what design principles drove the current values.

> **For AI agents building pages**: read [`docs/skills/modern-dark-theme.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/modern-dark-theme.md) — that's the prescriptive companion to this design-philosophy doc.

## The big picture

```
┌─ Visitor's browser ─────────────────────────────────────────────┐
│                                                                 │
│  <html data-theme="dark" data-palette="orange">                 │
│   ↓                                                             │
│   theme.css :root              ◀── universal defaults           │
│   theme.css [data-theme="dark"] ◀── dark mode defaults          │
│   palettes.css [data-palette="orange"][data-theme="dark"]       │
│       ◀── palette + theme combined override                     │
│   ↓                                                             │
│   Every CSS rule resolves --primary, --card-bg, etc.            │
│   to the right values for THIS visitor's chosen palette         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Three cascading layers:

1. **Universal defaults** (`theme.css :root`) — light-mode-ish defaults: a few brand colors and spacing tokens that every palette uses unless overridden.

2. **Dark-mode defaults** (`theme.css [data-theme="dark"]`) — the historical Django-admin-style dark theme. Warm-gray surfaces, Django brand teal accent. **Modern palettes override these.**

3. **Palette-specific overrides** (`palettes.css html[data-palette="X"][data-theme="dark"]`) — the modern values: cool-biased near-black surfaces, vibrant Tailwind -500 accents, palette-specific surface bias.

A visitor's `data-palette` attribute is set by a blocking inline script in `templates/smallstack/base.html` from one of:
- `localStorage["smallstack-palette"]` (set by the user menu swatches)
- `UserProfile.color_palette` (server-side default, passed via `{{ color_palette }}`)
- The string `"django"` (final fallback)

The attribute is ALWAYS set — even for the default "django" palette. This was a bug fix; previously the default skipped the attribute and the default palette's overrides never applied.

## The six palettes

| Palette | id | Accent | Surface bias | Hero band |
|---|---|---|---|---|
| Django | `django` | `#10b981` emerald | strong cool (B+15 R) | neutral |
| Blue | `dark-blue` | `#3b82f6` blue | cool (B+12 R) | tinted |
| Purple (default) | `purple` | `#a855f7` purple | cool (B+12 R) | tinted |
| Orange | `orange` | `#f97316` orange | cool (B+12 R) | neutral |
| Contrast | `high-contrast` | `#ffffff` white | strictly neutral (R=G=B) | neutral |
| Gold | `gold` | `#d3b559` gold | cool (B+12 R) | neutral |

**Switch palettes** via the user-menu dropdown (the avatar in the top-right). The grid below "Palette" shows a swatch per option; clicking persists to your profile AND `localStorage` so it survives a refresh.

## Design philosophy

### Modern-black canvas + vibrant accent

The dark palettes follow a pattern proven by Linear, Vercel, GitHub Dark, and Anthropic's console:

- **Body**: nearly-pure black (`#0a0b0f` or similar)
- **Cards**: clearly lifted from body but still very dark (`#161b22` matches GitHub Dark's panel)
- **Accent**: ONE saturated color (Tailwind -500) used sparingly — for numbers, buttons, links, active state, focus
- **Everything else**: neutral grays from the zinc family (slate-blue muted text)

Why this works: the saturated accent does ALL the visual work. The neutral canvas stays out of the way. Information hierarchy comes from where the accent lives, not from competing tints.

### The accent palette

Every palette uses a vibrant Tailwind -500 family value:

- `#3b82f6` blue-500
- `#a855f7` purple-500
- `#f97316` orange-500
- `#10b981` emerald-500
- `#ffffff` for high-contrast (max-contrast accessibility)

These are saturated enough to pop on near-black surfaces but not so saturated they look "neon dashboard 2010." Hover states use the -400 sibling (one notch lighter); links typically use the -400 too so they don't compete with the primary -500.

### Surface bias — the color-science correction

Pure neutral surfaces (R=G=B) sitting next to bright accent colors don't read neutral. The human visual system contrast-enhances surfaces toward the complementary hue of the dominant accent. So:

| Accent | Complement | Surfaces drift toward | Counter-bias needed |
|---|---|---|---|
| Blue (`#3b82f6`) | orange | warm | subtle cool bias |
| Purple (`#a855f7`) | yellow-green | slightly warm | subtle cool bias |
| Orange (`#f97316`) | cyan | slightly cool — but warm at low lightness! | subtle cool bias |
| **Emerald (`#10b981`)** | **red-magenta** | **distinctly warm/brown** | **stronger cool bias** |
| White (`#ffffff`) | gray | no drift | pure neutral |

The blue/purple/orange palettes use `--card-bg: #161b22` (R22 G27 B34 — 12 RGB points B>R). Django uses `--card-bg: #131722` (R19 G23 B34 — 15 points B>R) because emerald's red-magenta complement pulls harder.

This is why the surface values vary slightly across palettes. They're all "modern dark," but each is tuned to its specific accent's contrast behavior.

### Hero band — the muddy-color exception

`theme.css` defines `--accent-band-bg: color-mix(in srgb, var(--primary) 15%, var(--body-bg))`. This is the "subtle accent-tinted band" used on every page header (`.page-header-bleed`), the help TOC header (`.toc-header`), and other hero strips.

For blue and purple, the 15% mix produces a clean navy / plum tint that reads as "accent zone."

For orange, the mix produces brown (color science: dark orange = brown).
For emerald, the mix produces olive (dark green = olive).
For white, the mix produces medium gray that's visually noisy.

So orange, django (emerald), and high-contrast override `--accent-band-bg` to `var(--card-bg)` — a clean neutral lift. The accent stays reserved for actual data and actions.

### Table striping

The `.table-plain` (and the auto-generated CRUD tables) use neutral lifts for zebra striping:

```css
tbody tr:nth-child(even) {
    background: color-mix(in srgb, var(--body-fg) 4%, var(--card-bg));
}
```

This was a deliberate move away from `color-mix(--primary X%, body-bg)` — that was painting accent into every other row and pulling visual attention away from the data the user actually wanted to read.

## The variable reference

For the complete list of variables and what they control, see [`theme-color-reference.md`](theme-color-reference.md).

The 11 variables every page should know about:

| Variable | Purpose |
|---|---|
| `--body-bg` | Page canvas |
| `--card-bg` | Every elevated surface (cards, stat boxes, inputs) |
| `--card-header-bg` | Subtle band on top of cards |
| `--card-border` | Hairline borders |
| `--sidebar-bg` | Sidebar canvas |
| `--footer-bg` | Footer canvas |
| `--primary` | Saturated accent |
| `--link-color` | Body links |
| `--body-fg` | Default text |
| `--body-quiet-color` | Subtle text |
| `--accent-band-bg` | Subtle accent-tinted hero band |

## What this replaced

The pre-v0.9 dark theme used warm-gray surfaces (`#212121`, `#1e1e1e`, `#3a3a3a`) and the Django brand teal accent (`#44b78b`). It looked correct in 2014 — "this is Django-themed" — but read as muddy/brown next to most modern UIs by 2026.

Specifically:
- Stat cards on the dashboard read brown
- Page header bands went muddy with warm accents
- Tables had accent-tinted zebra stripes that competed with data
- Sidebar warm gray clashed with the cool navy header `#0A192F` used by the blue palette
- Hard-coded `#1e1e1e` overrides in component CSS (`help.css`) bypassed palette tokens entirely

The v0.9.x refactor systematically replaced all of these with the modern-dark pattern + the `--accent-band-bg` variable + the strict "no hard-coded hex" discipline.

## How to extend or modify

- **Adding a new palette**: see [`docs/skills/modify-palettes.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/modify-palettes.md) for the file map and step-by-step.
- **Adding a custom theme (Bootstrap/Tailwind alongside SmallStack)**: see [`adding-your-own-theme.md`](adding-your-own-theme.md) — different scope, different scenario.
- **Modifying surface values for an existing palette**: edit `apps/smallstack/static/smallstack/css/palettes.css`, change the variables in the relevant `html[data-palette="X"][data-theme="dark"]` block, hot-reload should pick up the change. Verify across all pages via the user-menu palette swatches.

## Related

- [`theming.md`](theming.md) — high-level theming guide
- [`theme-color-reference.md`](theme-color-reference.md) — complete variable list
- [`adding-your-own-theme.md`](adding-your-own-theme.md) — custom theme alongside SmallStack
- [`components.md`](components.md) — UI component patterns
- [`cards.md`](cards.md) — card markup specifically
