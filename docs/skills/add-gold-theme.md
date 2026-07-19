# Adding a Gold Color Palette to SmallStack

> **This is a worked example, not the canonical guide.** For the authoritative, current steps + gotchas for adding *any* palette, read [`modify-palettes.md`](modify-palettes.md) first — this page just walks the Gold/Auxiom case concretely.

## Overview

SmallStack themes are built on **CSS custom properties** organized per-palette and per-theme (light/dark). Adding a palette touches **four wiring points** (miss any one and it half-works — see `modify-palettes.md` for the per-step failure modes):

1. **`apps/smallstack/palettes.yaml`** — register the palette so its swatch appears in the picker
2. **`apps/smallstack/static/smallstack/css/palettes.css`** — the light + dark CSS variable overrides (plus the two "muddy accent" override rules — gold is a warm accent)
3. **`apps/profile/models.py`** `COLOR_PALETTE_CHOICES` **+ a migration** — the profile-form choice
4. **`apps/profile/views.py`** `PalettePreferenceView.VALID_PALETTES` — allowlist the live swap, or saves silently fail

This guide shows how to add a **Gold palette** inspired by the Auxiom branding color scheme.

---

## Auxiom Brand Colors (Reference)

From `ai_cowork/auxiom-branding.skill`:

| Color | HEX | RGB | Usage |
|-------|-----|-----|-------|
| **Auxiom Gold** | `#D3B559` | 211, 181, 89 | Primary brand color |
| **Dark Gray** | `#343434` | 52, 52, 52 | Body text, dark backgrounds |
| **Smoky Blue** | `#4F636D` | 79, 99, 109 | Accents, supporting elements |
| **White** | `#FFFFFF` | 255, 255, 255 | Page background |
| **Off-White** | `#F7F7F7` | 247, 248, 249 | Section backgrounds |

---

## Step 1: Register the Palette in Models

Edit `apps/profile/models.py`, line 104–111:

```python
COLOR_PALETTE_CHOICES = [
    ("", "System Default"),
    ("django", "Django"),
    ("high-contrast", "High Contrast"),
    ("dark-blue", "Blue"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("gold", "Gold"),           # ← ADD THIS LINE
]
```

**Why?** This makes "Gold" appear in the user profile theme picker.

---

## Step 2: Add CSS Variables to palettes.css

Edit `apps/smallstack/static/smallstack/css/palettes.css`, appending this section at the end (before or after the "Palette Selector UI" section):

```css
/* ============================================
   Gold Palette (Auxiom Inspired)
   ============================================ */

html[data-palette="gold"] {
    /* Light mode: Gold primary accent on white backgrounds */
    --primary: #D3B559;
    --primary-hover: #C9A84F;
    --secondary: #4F636D;
    --header-bg: #D3B559;
    --body-fg: #343434;
    --text-muted: #666666;
    --sidebar-fg: #343434;
    --sidebar-active-bg: #D3B559;
    --sidebar-active-fg: #ffffff;
    --sidebar-border: #cccccc;
    --sidebar-hover-bg: #F7F7F7;
    --input-focus-border: #D3B559;
    --input-border: #cccccc;
    --button-bg: #D3B559;
    --button-fg: #000000;
    --button-hover-bg: #C9A84F;
    --card-border: #e0e0e0;
    --link-color: #D3B559;
    --link-fg: #D3B559;
    --link-hover: #C9A84F;
    --breadcrumb-fg: #666666;
    --breadcrumb-link: #D3B559;
    --breadcrumb-separator: #999999;
    --body-quiet-color: #999999;
    --footer-fg: #666666;
}

html[data-palette="gold"][data-theme="dark"] {
    /* Modern dark + vibrant gold accent. Surfaces use near-black
       with subtle cool-channel bias (R<G<B). Gold (#D3B559) is the
       single source of color — primary buttons, sidebar-active, link
       color, focus borders.

       The Auxiom Gold is slightly desaturated compared to Tailwind
       yellows, giving it a premium/professional feel. The hover shade
       (#C9A84F) is slightly darker to maintain contrast on dark.

       Accent: #D3B559 (Auxiom Gold) — warm but not garish, works
       well as a strong accent in a neutral dark space.

       Surfaces (same cool-biased near-black as other dark palettes):
         body-bg / footer-bg  #0a0b0f  ◀── deep near-black canvas
         header-bg            #111218  ◀── chrome band, slight lift
         sidebar-bg           #0c0d12  ◀── between body and card
         card-bg / input-bg   #161b22  ◀── elevated surface
         card-header-bg       #1d2230  ◀── subtle band on cards
         card-border          #262d3d  ◀── visible hairline */

    /* Vibrant gold accent */
    --primary: #D3B559;
    --primary-hover: #E6C871;
    --secondary: #4F636D;
    --sidebar-active-bg: #D3B559;
    --sidebar-active-fg: #000000;
    --input-focus-border: #D3B559;
    --button-bg: #D3B559;
    --button-fg: #000000;
    --button-hover-bg: #E6C871;

    /* Links — lighter gold to pop on near-black without competing
       with the primary saturated gold. */
    --link-fg: #E6C871;
    --link-color: #E6C871;
    --link-hover: #F0D580;
    --breadcrumb-link: #e4e4e7;

    /* Surfaces — same cool-biased near-black as dark-blue / dark-purple */
    --body-bg: #0a0b0f;
    --content-bg: #0a0b0f;
    --header-bg: #111218;
    --hero-gradient-end: #181d24;
    --card-bg: #161b22;
    --card-header-bg: #1d2230;
    --card-border: #262d3d;
    --hairline-color: #262d3d;
    --sidebar-bg: #0c0d12;
    --sidebar-hover-bg: #161b22;
    --sidebar-border: #262d3d;
    --footer-bg: #0a0b0f;
    --footer-fg: #71717a;
    --input-bg: #161b22;
    --input-border: #3c4356;

    /* Muted text — zinc family, readable on near-black */
    --text-muted: #a1a1aa;
    --breadcrumb-fg: #a1a1aa;
    --breadcrumb-separator: #52525b;
}

/* Accent band override — gold (like orange and django) has an accent
   color that goes muddy at low lightness when mixed with body-bg,
   so we use the card surface instead. */
html[data-palette="gold"][data-theme="dark"] {
    --accent-band-bg: var(--card-bg);
}

html[data-palette="gold"][data-theme="dark"] .hero-section {
    background: var(--card-bg) !important;
}
```

---

## Step 3: Verify Registration (Optional)

Run the dev server and check the theme picker:

```bash
make run
```

1. Log in to http://localhost:8005
2. Click your user menu → "Profile Settings"
3. Look for the "Gold" option in the palette selector
4. Switch to Gold and verify:
   - Light mode: Gold accents on white
   - Dark mode: Gold accents on near-black surfaces
   - All text is readable
   - Links and buttons have correct colors

---

## Color Palette Details

### Light Mode (html[data-palette="gold"])
- **Primary**: `#D3B559` (Auxiom Gold) — used for buttons, links, headers
- **Primary Hover**: `#C9A84F` (slightly darker for hover states)
- **Background**: White (default) / Off-white (`#F7F7F7` for cards)
- **Text**: Dark Gray (`#343434`) on light backgrounds

### Dark Mode (html[data-palette="gold"][data-theme="dark"])
- **Primary**: `#D3B559` (same gold)
- **Primary Hover**: `#E6C871` (slightly lighter for contrast on dark)
- **Surfaces**: Near-black (`#0a0b0f` body, `#161b22` cards) with cool-channel bias
- **Links**: Lighter gold (`#E6C871`) to pop on dark without washing out
- **Text**: Zinc gray (`#a1a1aa`) for readability on near-black

---

## Design Rationale

**Why these colors?**

1. **Gold is warm** — balances the cool-biased neutral surfaces used in SmallStack's dark mode
2. **Auxiom Gold is professional** — not as saturated as Tailwind yellow, reads as "premium"
3. **Smoky Blue as secondary** — future-proofs for accent elements (badges, warnings) without competing with gold
4. **Dark Gray on light** — matches Auxiom's brand typography

**Why the hover shades?**

- Light mode: darker gold (`#C9A84F`) — more contrast on white
- Dark mode: lighter gold (`#E6C871`, `#F0D580`) — still readable on `#0a0b0f`

---

## Testing Scenarios

Create a test page to verify all color uses:

```html
<a href="#">Link in Gold</a>
<button class="primary">Primary Button</button>
<input type="text" placeholder="Focus this input">
<div style="background: var(--sidebar-active-bg); color: var(--sidebar-active-fg);">
  Sidebar Active State
</div>
```

Check on both light and dark modes, with the Gold palette selected.

---

## Optional: Add to Documentation

If you want to document this palette in the help system, create a new file at:

```
apps/help/content/theme-gold-palette.md
```

With content explaining the Gold palette, its inspiration (Auxiom), and use cases.

---

## Files Changed

- `apps/profile/models.py` — 1 line added to `COLOR_PALETTE_CHOICES`
- `apps/smallstack/static/smallstack/css/palettes.css` — ~80 lines added (light + dark mode + overrides)

**No migrations needed** — the field already supports custom values via `max_length=20`.

---

## Color Values Cheat Sheet

Copy-paste these into your CSS or design tools:

### Primary Colors
```
Gold Primary:      #D3B559
Gold Hover Light:  #C9A84F
Gold Hover Dark:   #E6C871
Gold Link Dark:    #E6C871
Gold Link Hover:   #F0D580
```

### Supporting Colors
```
Dark Gray:         #343434
Smoky Blue:        #4F636D
White:             #FFFFFF
Off-White:         #F7F7F7
```

---

## Further Reading

- **Theme Architecture**: `docs/skills/modern-dark-theme.md`
- **Color Reference**: `apps/smallstack/docs/theme-color-reference.md`
- **Palette Customization**: `docs/skills/modify-palettes.md`
- **Auxiom Brand Spec**: `ai_cowork/auxiom-branding.skill`

---

## CRITICAL: Register Gold in Three Additional Places

The documentation above (Steps 1-2) is **incomplete**. You must also register the Gold palette in two more places or it **won't appear in the dropdown menu**:

### Step 3: Add to palettes.yaml

Edit `apps/smallstack/palettes.yaml`, add this entry at the end of the `palettes:` list:

```yaml
  - id: gold
    label: Gold
    description: Warm gold accent palette inspired by Auxiom branding
    preview:
      light: "#D3B559"
      dark: "#E6C871"
```

**Why**: This file defines what appears in the palette selector dropdown. The `preview` colors show the light/dark accent swatches in the UI. The `id` must match your CSS `data-palette="gold"` attribute.

### Step 4: Add to PalettePreferenceView.VALID_PALETTES

Edit `apps/profile/views.py`, line 67:

```python
VALID_PALETTES = {"", "django", "high-contrast", "dark-blue", "orange", "purple", "gold"}
```

Add `"gold"` to the set.

**Why**: This whitelist validates palette selections on the backend. Without it, even if users select Gold in the UI, the server will reject the save.

---

## Complete Implementation Checklist

- [ ] Step 1: Edit `apps/profile/models.py` — Add ("gold", "Gold") to COLOR_PALETTE_CHOICES
- [ ] Step 2: Edit `apps/smallstack/static/smallstack/css/palettes.css` — Add CSS for light/dark modes
- [ ] **Step 3: Edit `apps/smallstack/palettes.yaml` — Add gold palette definition**
- [ ] **Step 4: Edit `apps/profile/views.py` line 67 — Add "gold" to VALID_PALETTES set**
- [ ] Test: Run `make run`, log in, go to Profile Edit, verify "Gold" appears in dropdown
- [ ] Test light mode with Gold
- [ ] Test dark mode with Gold
- [ ] Verify all buttons and links are readable

---

## Why These Four Steps?

1. **models.py** — Registers as a Django choice (database + forms)
2. **palettes.css** — Defines the actual CSS colors
3. **palettes.yaml** — Makes it appear in the UI dropdown selector
4. **views.py** — Validates palette selection on the backend

**Skip any of these and Gold won't work properly.**

---

