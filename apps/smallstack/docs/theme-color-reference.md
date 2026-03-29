---
title: Theme Color Quick Reference
description: Complete reference of every CSS custom property with current values for light and dark modes
---

# Theme Color Quick Reference

Every color in SmallStack is a CSS custom property defined in `static/smallstack/css/theme.css`. This page lists every variable, its current value in both modes, and what it controls — so you can hand this to a designer or AI and get back a complete, cohesive palette.

**File:** `apps/smallstack/static/smallstack/css/theme.css`

## Primary Colors

The brand colors that define the overall look. These cascade into buttons, links, sidebar highlights, and form focus states.

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--primary` | `#417690` | `#6366F1` | Main brand color — links, active states, header background |
| `--primary-hover` | `#205067` | `#818CF8` | Hover/pressed variant of primary |
| `--secondary` | `#79aec8` | `#818CF8` | Complementary color for secondary UI elements |
| `--accent` | `#f5dd5d` | `#A5B4FC` | Highlight color for badges, indicators, emphasis |

## Backgrounds

The layered surface colors that create depth. Listed darkest-to-lightest in dark mode.

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--body-bg` | `#f7f7f7` | `#121212` | Page background (outermost layer) |
| `--body-fg` | `#333333` | `#f5f5f5` | Main text color on body-bg |
| `--content-bg` | `#ffffff` | `#1e1e1e` | Content area / main panel background |
| `--header-bg` | `#417690` | `#1e1e1e` | Top navigation bar background |
| `--header-fg` | `#ffffff` | `#ffffff` | Top navigation bar text |

## Sidebar

Controls the left navigation panel. Active state should use primary brand color.

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--sidebar-bg` | `#ffffff` | `#1e1e1e` | Sidebar background |
| `--sidebar-fg` | `#333333` | `#f5f5f5` | Sidebar text |
| `--sidebar-hover-bg` | `#f0f0f0` | `#303030` | Sidebar item hover highlight |
| `--sidebar-active-bg` | `#417690` | `#6366F1` | Selected/active item background |
| `--sidebar-active-fg` | `#ffffff` | `#ffffff` | Selected/active item text |
| `--sidebar-border` | `#e0e0e0` | `#3d3d3d` | Sidebar border/divider |

## Cards

Content containers with optional headers. Card-bg should be one step lighter than body-bg.

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--card-bg` | `#ffffff` | `#212121` | Card/panel background |
| `--card-border` | `#e0e0e0` | `#3d3d3d` | Card border |
| `--card-header-bg` | `#f5f5f5` | `#2a2a2a` | Card header background (slightly different from card-bg) |
| `--hairline-color` | `#e0e0e0` | `#3d3d3d` | Thin divider lines inside cards and tables |

## Forms

Input fields and focus states. Focus border should match or complement primary.

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--input-bg` | `#ffffff` | `#303030` | Form input background |
| `--input-border` | `#cccccc` | `#4a4a4a` | Form input border |
| `--input-focus-border` | `#417690` | `#6366F1` | Form input border when focused |

## Status Messages

Muted backgrounds with readable foreground text. Dark mode uses desaturated tones to avoid glare.

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--success-bg` | `#dff0d8` | `#264d26` | Success message background |
| `--success-fg` | `#3c763d` | `#8fd68f` | Success message text |
| `--warning-bg` | `#fcf8e3` | `#4d4426` | Warning message background |
| `--warning-fg` | `#8a6d3b` | `#e6c84d` | Warning message text |
| `--error-bg` | `#f2dede` | `#4d2626` | Error message background |
| `--error-fg` | `#a94442` | `#f08080` | Error message text |
| `--info-bg` | `#d9edf7` | `#264d4d` | Info message background |
| `--info-fg` | `#31708f` | `#8fd6d6` | Info message text |

## Buttons

Primary action buttons. Button-fg must contrast with button-bg (white text on dark buttons, black text on bright buttons).

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--button-bg` | `#417690` | `#6366F1` | Primary button background (usually matches --primary) |
| `--button-fg` | `#ffffff` | `#ffffff` | Primary button text |
| `--button-hover-bg` | `#205067` | `#818CF8` | Primary button hover state |

## Text & Links

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--text-muted` | `#666666` | `#b0b0b0` | Secondary/dimmed text |
| `--link-color` | `var(--primary)` | `#ffffff` | Link color |
| `--link-hover` | `var(--primary-hover)` | `#e0e0e0` | Link hover color |
| `--link-fg` | `var(--primary)` | `#ffffff` | Link foreground (alias) |

## Breadcrumbs

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--breadcrumb-fg` | `#666666` | `#b0b0b0` | Breadcrumb text color |
| `--breadcrumb-link` | `var(--primary)` | `#ffffff` | Breadcrumb link color |
| `--breadcrumb-separator` | `#999999` | `#808080` | Separator character (/) color |

## Footer

| Variable | Light | Dark | Used For |
|----------|-------|------|----------|
| `--footer-bg` | `#f5f5f5` | `#1e1e1e` | Footer background |
| `--footer-fg` | `#666666` | `#b0b0b0` | Footer text |

## Shadows

Higher opacity in dark mode for visibility against dark surfaces.

| Variable | Light | Dark |
|----------|-------|------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | `0 1px 3px rgba(0,0,0,0.4)` |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | `0 4px 8px rgba(0,0,0,0.5)` |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | `0 10px 20px rgba(0,0,0,0.5)` |

## Spacing & Layout

These are shared across both modes.

| Variable | Value | Used For |
|----------|-------|----------|
| `--topbar-height` | `56px` | Height of the top navigation bar |
| `--sidebar-width` | `250px` | Sidebar width when expanded |
| `--sidebar-collapsed-width` | `60px` | Sidebar width when collapsed (icons only) |
| `--control-height` | `36px` | Standard height for buttons and inputs |

## Effects

| Variable | Value | Used For |
|----------|-------|----------|
| `--transition-fast` | `0.15s ease` | Quick interactions (hover, focus) |
| `--transition-normal` | `0.3s ease` | Sidebar open/close, theme transitions |
| `--radius-sm` | `4px` | Buttons, inputs, small elements |
| `--radius-md` | `8px` | Cards, modals |
| `--radius-lg` | `12px` | Large containers, hero sections |

## AI Prompt Template

Copy the block below and paste it into any AI to generate a complete theme palette. Replace the primary colors with your desired brand colors and the AI will suggest values for everything else.

~~~
I need a complete dark mode color theme for a Django admin-style web app.
Below are all the CSS custom properties I need values for.
Suggest a cohesive palette that works well together on dark backgrounds.

## Primary colors (adjust these to your brand):
- Primary: #6366F1
- Hover: #818CF8
- Accent: #A5B4FC

## Variables to theme:

### Primary colors
--primary:            (main brand color, used for links, active states)
--primary-hover:      (lighter/brighter variant for hover states)
--secondary:          (complementary color, used for secondary elements)
--accent:             (highlight color for badges, indicators, emphasis)

### Backgrounds
--body-bg:            (page background, darkest layer)
--body-fg:            (main text color on body-bg)
--content-bg:         (content area / main panel background)
--header-bg:          (top navigation bar background)
--header-fg:          (top navigation bar text)

### Sidebar
--sidebar-bg:         (sidebar background)
--sidebar-fg:         (sidebar text)
--sidebar-hover-bg:   (sidebar item hover)
--sidebar-active-bg:  (sidebar active/selected item background)
--sidebar-active-fg:  (sidebar active/selected item text)
--sidebar-border:     (sidebar border/divider color)

### Cards
--card-bg:            (card/panel background)
--card-border:        (card border)
--card-header-bg:     (card header background, slightly different from card-bg)
--hairline-color:     (thin divider lines)

### Forms
--input-bg:           (form input background)
--input-border:       (form input border)
--input-focus-border: (form input border when focused)

### Status messages
--success-bg:         (success message background)
--success-fg:         (success message text)
--warning-bg:         (warning message background)
--warning-fg:         (warning message text)
--error-bg:           (error message background)
--error-fg:           (error message text)
--info-bg:            (info message background)
--info-fg:            (info message text)

### Buttons
--button-bg:          (primary button background, usually matches --primary)
--button-fg:          (primary button text, must contrast with button-bg)
--button-hover-bg:    (primary button hover, usually matches --primary-hover)

### Text
--text-muted:         (secondary/dimmed text)
--link-color:         (link color)
--link-hover:         (link hover color)
--link-fg:            (link foreground)

### Breadcrumbs
--breadcrumb-fg:      (breadcrumb text)
--breadcrumb-link:    (breadcrumb link color)
--breadcrumb-separator: (breadcrumb separator character color)

### Footer
--footer-bg:          (footer background)
--footer-fg:          (footer text)

### Shadows
--shadow-sm:          (subtle shadow)
--shadow-md:          (medium shadow)
--shadow-lg:          (large shadow)

## Constraints:
- Body background should be very dark (#121212 range)
- Text on dark backgrounds must be high contrast (WCAG AA minimum)
- Status colors (success/warning/error/info) need dark-appropriate muted backgrounds with readable text
- Shadows should use higher opacity for dark mode visibility
- Provide hex values for all colors, box-shadow values for shadows
~~~

## How to Apply a New Theme

After getting values from the AI prompt above, update the `[data-theme="dark"]` block in `static/smallstack/css/theme.css`, then run:

```bash
python manage.py collectstatic --noinput
```

Django serves static files from the `staticfiles/` directory. Without `collectstatic`, your source changes won't be picked up by the dev server.

## Related Docs

- [Theming & Customization](/help/smallstack/theming/) — How the theme system works, palettes, dark mode toggle
- [Adding Your Own Theme](/help/smallstack/adding-your-own-theme/) — Using a separate CSS framework alongside SmallStack
