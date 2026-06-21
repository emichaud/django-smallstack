# Modern Dark Theme — the canonical guide for AI agents

**Read this first** before building any new page, component, card, table, or admin surface in SmallStack. The patterns here produce pages that work correctly across every palette + theme combination on the first try. Following them avoids the most common AI-built-page failure mode: pages that look fine on the default palette but turn brown / olive / muddy on others.

> **Other skill files**: `admin-page-styling.md` has many useful patterns (forms, modals, badges, etc.). When it conflicts with this file, **this file wins** — it reflects the post-v0.9 modern-dark refactor with the cool-biased near-black surfaces and vibrant Tailwind -500 accents.

## The architecture in one paragraph

SmallStack ships **five color palettes** (django/default, dark-blue, dark-purple, orange, high-contrast) × **two themes** (light, dark). Each palette overrides CSS custom properties via `html[data-palette="X"][data-theme="dark"]` selectors. The `data-palette` attribute is set by a blocking script in `templates/smallstack/base.html` from the user's profile (`UserProfile.color_palette`) or the system default (`SMALLSTACK_COLOR_PALETTE`, defaults to `"django"`). Your page **never** hard-codes a color — it references variables. The variables resolve to the right value for whichever palette the visitor is using.

The user can switch palettes from the user menu (the avatar dropdown shows Dark/Light toggle + a Palette grid).

## The one rule that prevents 90% of AI-built-page bugs

**Don't hard-code hex colors.** Use the CSS variables. Every time you write `background: #1e1e1e` or `color: #ffffff` you are creating a page that breaks on at least one palette.

Two specific anti-patterns I've fixed in this codebase:

```css
/* ❌ ANTI-PATTERN — this is what was wrong with help.css */
[data-theme="dark"] .help-card {
    background-color: #1e1e1e;  /* legacy warm gray — bypasses palette */
    border-color: #3a3a3a;       /* legacy warm gray — bypasses palette */
}

/* ✓ CORRECT — let the base rule's variables flow through */
.help-card {
    background-color: var(--card-bg);
    border-color: var(--card-border);
}
```

```html
<!-- ❌ ANTI-PATTERN — inlined color-mix recipe in a template -->
<div style="background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));">

<!-- ✓ CORRECT — reference the variable that already does this -->
<div style="background: var(--accent-band-bg);">
```

## The variables every page should know

### Surfaces
Use these for backgrounds. They're palette-correct.

| Variable | Purpose |
|---|---|
| `--body-bg` | The page canvas. Don't use for cards. |
| `--card-bg` | Every elevated surface: cards, stat boxes, sidebar items at rest, inputs |
| `--card-header-bg` | A subtle band on top of a card (table header rows, card titles) |
| `--card-border` | Hairline borders on cards |
| `--hairline-color` | Generic hairline (same as `--card-border` in practice) |
| `--input-bg` | Form input fields |
| `--input-border` | Form input borders (slightly lighter than card-border for affordance) |
| `--sidebar-bg` | Sidebar canvas |
| `--sidebar-hover-bg` | Sidebar item hover background (matches `--card-bg`) |
| `--footer-bg` | Footer canvas (matches `--body-bg`) |

### Accent
Use for one thing only: things the user is acting on (numbers, buttons, links, active state, focus borders).

| Variable | Purpose |
|---|---|
| `--primary` | Saturated accent (Tailwind -500: `#3b82f6` blue, `#a855f7` purple, `#f97316` orange, `#10b981` emerald) |
| `--primary-hover` | Lighter accent for hover (Tailwind -400) |
| `--link-color` | Body links — usually a lighter accent than `--primary` so they don't compete |
| `--button-bg` / `--button-fg` | Primary buttons |
| `--sidebar-active-bg` | The pill behind the active sidebar item |
| `--input-focus-border` | Form field focus ring |

### Text
| Variable | Purpose |
|---|---|
| `--body-fg` | Default text — pure white on near-black |
| `--body-quiet-color` | Subtle text (subtitles, labels) — light gray |
| `--text-muted` | Muted footer / metadata — slate gray |
| `--breadcrumb-fg` | Breadcrumb text |
| `--breadcrumb-link` | Breadcrumb link |

### Semantic / status
Don't override these per palette. Use them for STATE, not decoration.

| Variable | Purpose |
|---|---|
| `--success-fg` | "Up", "operational", success counts |
| `--warning-fg` | "Degraded", warnings, pending |
| `--error-fg` | "Down", failures, 4xx/5xx counts |
| `--message-warning-bg` | Warning banner background |
| `--delete-button-bg` | Destructive button background |

### The new variable (v0.9.4+)
| Variable | Purpose |
|---|---|
| `--accent-band-bg` | A subtle accent-tinted band — used by `.page-header-bleed`, hero sections, TOC headers. Defaults to `color-mix(--primary 15%, --body-bg)` for blue/purple, automatically falls back to `--card-bg` for orange/django/high-contrast where the mix would go muddy. **Use this for any hero band you build.** |

## The class system

Build pages from these. They wire up the variables for you.

### Layout
- `.page-header-bleed` — full-width title band at the top of an admin page. Includes the auto-palette-correct background.
- `.page-header-bleed.page-header-with-actions` — flex layout for title + action buttons on right
- `.page-header-content` — the title + subtitle group inside the bleed
- `.page-subtitle` — the small grey text below the H1

### Cards
- `.card` — generic elevated container. Uses `--card-bg` + `--card-border`.
- `.card-header` — title band on a card. Uses `--card-header-bg`.
- `.card-body` — content area. Use `padding: 0` if the card contains a table that bleeds to edges.

### Tables
- `.table-plain` — full-width data table with the canonical zebra striping. Headers, body, hover all wire up automatically.
- `.crud-table` — alias for tables generated by the CRUDView system.

### Buttons
- `.btn-primary` — vibrant accent background, white foreground
- `.btn-outline` — accent-bordered transparent (for secondary actions)
- `.btn-sm` — small modifier

### Tabs (Backups / MCP admin / API admin all use these)
- `.tab-btn` — single tab button. Add `.active` on the current tab.

### Buttons inside `.page-header-bleed`
The right-side action cluster is usually styled inline. Use the canonical "card-style action button" pattern (see `Pattern: Action card buttons` below).

## Patterns you will reach for constantly

### Pattern: A standard admin page

```django
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}My Thing{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block page_header %}
<div class="page-header-bleed page-header-with-actions"
     style="display: flex; align-items: center; justify-content: space-between;">
  <div class="page-header-content">
    <h1>My Thing</h1>
    <p class="page-subtitle">One short sentence about what this page does.</p>
    <nav style="margin-top: 0.5rem; font-size: 0.8rem;">
      <a href="{% url 'website:home' %}"
         style="color: var(--body-quiet-color); text-decoration: none;">Home</a>
      <span style="color: var(--body-quiet-color); margin: 0 0.3rem;">/</span>
      <span style="color: var(--body-fg);">My Thing</span>
    </nav>
  </div>
  {# Action buttons (card-style) go here — see below #}
</div>
{% endblock %}

{% block content %}
<div class="card">
  <div class="card-header">
    <h2>Content</h2>
  </div>
  <div class="card-body">
    {# Your page body. #}
  </div>
</div>
{% endblock %}
```

The `.page-header-bleed` background comes from `--accent-band-bg`. **You do not need to add any color**. Switch palettes and watch it render correctly on each.

### Pattern: Stat-cards row (the top-of-dashboard pattern)

```django
<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px;">
  <div class="card">
    <div class="card-body" style="text-align: center; padding: 14px 8px;">
      <div style="font-size: 1.75rem; font-weight: 700; color: var(--primary);">{{ count }}</div>
      <div style="color: var(--body-quiet-color); font-size: 0.8rem;">Active</div>
    </div>
  </div>
  {# ... repeat for each stat ... #}
</div>
```

Numbers use `var(--primary)` for the accent. Use the SEMANTIC variables for state-driven colors:

```django
<div style="color: {% if errors %}var(--error-fg){% else %}var(--primary){% endif %};">{{ count }}</div>
```

### Pattern: Action-card buttons (the htmx-style top-right buttons on admin pages)

```html
<a href="..." class="action-card">
  <div class="action-card-body">
    <svg viewBox="0 0 24 24" class="action-card-icon">
      <path d="..."/>
    </svg>
    <div style="text-align: left;">
      <div class="action-card-title">Mint Token</div>
      <div class="action-card-subtitle">Create a new API key</div>
    </div>
  </div>
</a>
```

This is the canonical card-button used across Tokens, MCP admin, API admin. The hover *and* keyboard-focus affordances live on the `.action-card`
class in `components.css` (`:hover, :focus-visible` together); use `<button>` for "performs an action," `<a>` for "goes somewhere." Wrap multiple in `.action-cards` for the standard 12px-gap row.

Two colour variants for state-tinted CTAs: `.action-card-success` (green border, success-tinted hover) and `.action-card-danger` (red, for destructive actions).

> **Anti-pattern**: hand-rolled inline `style="border: 2px solid …" onmouseover="…" onmouseout="…"` button. Bypasses keyboard focus (`:focus-visible` doesn't fire), defeats CSP `script-src 'self'` if tightened, and duplicates ~6 lines of inline JS at every call site. Use the class.

### Pattern: Status badges (inside table cells)

```html
{# Pass status. Cell renders the correct color automatically. #}
{% if status == "PASS" %}
  <span style="display: inline-block; padding: 2px 8px; border-radius: 4px;
               font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em;
               background: color-mix(in srgb, var(--success-fg) 15%, var(--card-bg));
               color: var(--success-fg);">✓ PASS</span>
{% elif status == "WARN" %}
  <span style="display: inline-block; padding: 2px 8px; border-radius: 4px;
               font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em;
               background: color-mix(in srgb, var(--message-warning-bg, orange) 18%, var(--card-bg));
               color: var(--message-warning-bg, orange);">⚠ WARN</span>
{% else %}
  <span style="display: inline-block; padding: 2px 8px; border-radius: 4px;
               font-size: 0.7rem; font-weight: 700; letter-spacing: 0.04em;
               background: color-mix(in srgb, var(--delete-button-bg, red) 15%, var(--card-bg));
               color: var(--delete-button-bg, red);">✗ FAIL</span>
{% endif %}
```

The `color-mix(... 15%, var(--card-bg))` pattern is the canonical "tinted badge" recipe. Always mix into `--card-bg` (the surface the badge sits on), never into `--body-bg`.

### Pattern: Tables

```django
<div class="card">
  <div class="card-header">
    <h2>Recent items</h2>
  </div>
  <div class="card-body" style="padding: 0;">
    <table class="table-plain" style="width: 100%; border-collapse: collapse;">
      <thead>
        <tr>
          <th style="text-align: left; padding: 10px 16px;">Path</th>
          <th style="text-align: right; padding: 10px 16px;">Count</th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr>
            <td style="padding: 10px 16px;">{{ row.path }}</td>
            <td style="padding: 10px 16px; text-align: right;">{{ row.count }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
```

`.table-plain` wires up the neutral zebra striping and the subtle header band automatically. **Don't manually set row backgrounds.**

### Pattern: A hero band on a landing-style page

```html
<div class="page-header-bleed">
  <div class="page-header-content">
    <h1>Welcome</h1>
    <p class="page-subtitle">A short sentence.</p>
  </div>
</div>
```

Or, if you need a custom hero element that isn't `.page-header-bleed`, **use the variable**:

```html
<div style="background: var(--accent-band-bg); padding: 24px;">
  <h1>Custom hero</h1>
</div>
```

`--accent-band-bg` is defined in `theme.css` as `color-mix(in srgb, var(--primary) 15%, var(--body-bg))` and overridden per palette to `var(--card-bg)` for orange / django / high-contrast (where the default mix goes muddy).

## Anti-patterns: things to never do

### 1. Hard-coded hex colors
```html
<!-- ❌ -->
<div style="background: #1e1e1e; border: 1px solid #3a3a3a;">
<!-- ✓ -->
<div style="background: var(--card-bg); border: 1px solid var(--card-border);">
```

### 2. Dark-mode override blocks with hex literals
```css
/* ❌ — this was the help.css bug */
[data-theme="dark"] .my-card {
    background: #1a1a1a;
}
/* ✓ — let the base rule's --card-bg flow through */
.my-card {
    background: var(--card-bg);
}
```

### 3. Inlined color-mix(--primary 15%, --body-bg)
```html
<!-- ❌ — locks you out of per-palette overrides -->
<div style="background: color-mix(in srgb, var(--primary) 15%, var(--body-bg));">
<!-- ✓ — uses the canonical variable -->
<div style="background: var(--accent-band-bg);">
```

### 4. Primary-tinted table stripes
```css
/* ❌ — accent leaks into every row, pulls eye from data */
tr:nth-child(even) {
    background: color-mix(in srgb, var(--primary) 12%, var(--body-bg));
}
/* ✓ — neutral lift via body-fg, accent stays on data */
tr:nth-child(even) {
    background: color-mix(in srgb, var(--body-fg) 4%, var(--card-bg));
}
```

The `.table-plain` class already does this for you — just use it.

### 5. White-on-white or black-on-black actions
The button-fg color for accent palettes was changed from `#000000` to `#ffffff` because saturated blue/purple/orange/emerald with black text has poor contrast. Use the variables:
```html
<!-- ✓ — palette decides fg color -->
<button style="background: var(--button-bg); color: var(--button-fg);">Submit</button>
```

## The palette-color cheat sheet

You don't need to memorize the hex values — use `var(--primary)`. But this is the reference for what your page will look like across palettes:

| Palette | `--primary` | `--card-bg` | Hero band |
|---|---|---|---|
| `django` (default) | `#10b981` emerald | `#131722` cool near-black | neutral card |
| `dark-blue` | `#3b82f6` blue | `#161b22` GitHub Dark | tinted `color-mix(primary 15%, body-bg)` |
| `dark-purple` | `#a855f7` purple | `#161b22` | tinted |
| `orange` | `#f97316` orange | `#161b22` | neutral card |
| `high-contrast` | `#ffffff` white | `#1a1a1a` pure neutral | neutral card |

**Why the bands differ**: warm and yellow-shifted accents (orange, emerald, white) produce muddy / brown / olive / noisy gray when mixed at 15% with near-black body. Blue and purple stay readable as navy / plum at the same mix. So orange/emerald/high-contrast skip the mix and use the neutral card surface for hero bands.

## How to test your work

After building a page, **switch palettes** via the user menu (avatar dropdown → palette grid). Cycle through:

1. **Django** (default) — should look modern dark with emerald accent
2. **Blue** — modern dark with vibrant blue
3. **Purple** — modern dark with vibrant purple
4. **Orange** — modern dark with vibrant orange (verify no brown bands)
5. **Contrast** — pure black/white with visible borders

If your page looks fine on Django/Blue/Purple but goes brown on Orange or olive on Django, you have hard-coded a color somewhere. Grep your page for hex literals and replace with variables.

Then switch from Dark to Light theme via the same menu. Cards / text / accents should all flip cleanly. If they don't, you have a `[data-theme="dark"]` override with hex literals — same fix.

## Decision tree

```
Building a new page or component?
├── Use one of the canonical patterns above
│   └── Done — your variables resolve correctly on every palette
│
├── Need a new color somewhere?
│   ├── Is it state-driven (success/warning/error)?
│   │   └── Use --success-fg / --warning-fg / --error-fg
│   ├── Is it a surface / container?
│   │   └── Use --card-bg / --body-bg / --sidebar-bg
│   ├── Is it accent (data, action, focus)?
│   │   └── Use --primary / --link-color / --button-bg
│   └── Is it a subtle accent-tinted band?
│       └── Use --accent-band-bg
│
└── Tempted to hard-code a hex?
    └── Stop. Re-read this skill. There's a variable for that.
```

## Related skills

- `admin-page-styling.md` — exhaustive component-by-component reference (buttons, modals, etc).
- `theming-system.md` — architectural overview of the variable cascade.
- `modify-palettes.md` — adding a new palette or modifying an existing one.
- `apps/smallstack/docs/theme-architecture.md` — the design philosophy + color science behind these patterns.
