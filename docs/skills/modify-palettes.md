# Modify palettes — add a new color palette, tune an existing one

**Read this** before adding a new palette to SmallStack or changing an existing one. The file map, the variable list, the gotchas, and the verification steps.

> **Prerequisite**: read [`modern-dark-theme.md`](modern-dark-theme.md) first. It explains the variable system every palette overrides.

## File map — what touches a palette

| File | Role |
|---|---|
| `apps/smallstack/static/smallstack/css/palettes.css` | Every palette's variable overrides live here |
| `apps/smallstack/palettes.yaml` | The palette registry — id / label / description / preview swatches |
| `apps/profile/models.py` (`UserProfile.COLOR_PALETTE_CHOICES`) | The form choices for the profile-edit page |
| `apps/profile/migrations/` | A new migration is needed when you add a palette id |
| `apps/profile/views.py` (`PalettePreferenceView.VALID_PALETTES`) | The allowlist for the live palette-swap endpoint |
| `apps/smallstack/templates/smallstack/base.html` | The blocking script that sets `data-palette` on every page load |
| `apps/smallstack/static/smallstack/js/theme.js` | `setPalette()` — fires when the user picks a swatch in the menu |
| `apps/smallstack/context_processors.py` (`_get_effective_palette`) | Resolves user preference → server-side `data-palette` |

## Add a new palette in 4 steps

Four wiring points, in this order. They're independent, and **each failure mode is silent and different** — so do all four, don't stop early:

1. **`palettes.yaml`** — or the swatch never appears in the picker
2. **`palettes.css`** — or the swatch appears but selecting it does nothing visible
3. **`COLOR_PALETTE_CHOICES` + migration** — or the profile-edit dropdown omits it (and `makemigrations --check` fails in CI)
4. **`VALID_PALETTES`** — or the live swap silently rejects the save

### Step 1 — append to the registry (`palettes.yaml`)

```yaml
palettes:
  # ... existing entries ...
  - id: emerald-bright
    label: "Emerald Bright"
    description: "Higher-saturation green for outdoor / glare scenarios"
    preview:
      light: "#059669"
      dark: "#34d399"
```

`id` must be a valid Python identifier-ish slug (URL-safe + ASCII). The two preview swatches drive the small color circles in the user-menu palette grid.

### Step 2 — add the CSS overrides (`palettes.css`)

```css
/* Light mode */
html[data-palette="emerald-bright"] {
    --primary: #059669;
    /* ... light-mode overrides ... */
}

/* Dark mode — follow the modern-black pattern: cool-biased near-black
   surfaces + vibrant -500 accent. See modern-dark-theme.md for the
   token list and color-science notes. */
html[data-palette="emerald-bright"][data-theme="dark"] {
    /* Accent */
    --primary: #34d399;          /* Tailwind emerald-400 */
    --primary-hover: #6ee7b7;    /* emerald-300 */
    --secondary: #10b981;        /* emerald-500 */
    --sidebar-active-bg: #34d399;
    --sidebar-active-fg: #000000;  /* dark text on bright accent */
    --input-focus-border: #34d399;
    --button-bg: #34d399;
    --button-fg: #000000;
    --button-hover-bg: #6ee7b7;

    /* Links */
    --link-fg: #6ee7b7;
    --link-color: #6ee7b7;
    --link-hover: #a7f3d0;
    --breadcrumb-link: #e4e4e7;

    /* Surfaces — cool-biased near-black. For accents whose
       complement is red/magenta (greens) push stronger cool. */
    --body-bg: #07080f;
    --content-bg: #07080f;
    --header-bg: #10131c;
    --hero-gradient-end: #171a26;
    --card-bg: #131722;
    --card-header-bg: #1a1e2b;
    --card-border: #232838;
    --hairline-color: #232838;
    --sidebar-bg: #090b13;
    --sidebar-hover-bg: #131722;
    --sidebar-border: #232838;
    --footer-bg: #07080f;
    --input-bg: #131722;
    --input-border: #383c4c;

    /* Muted text */
    --text-muted: #a1a1aa;
    --footer-fg: #71717a;
    --breadcrumb-fg: #a1a1aa;
    --breadcrumb-separator: #52525b;
}
```

### Step 3 — register the choice on `UserProfile`

`apps/profile/models.py`:

```python
COLOR_PALETTE_CHOICES = [
    ("", "System Default"),
    ("django", "Django"),
    ("high-contrast", "Contrast"),
    ("dark-blue", "Blue"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("emerald-bright", "Emerald Bright"),  # NEW
]
```

Then create the migration:

```bash
uv run python manage.py makemigrations profile
uv run python manage.py migrate
```

The migration only updates the choices metadata; no schema changes.

### Step 4 — allowlist the id for live swap

`apps/profile/views.py`:

```python
class PalettePreferenceView(View):
    VALID_PALETTES = {
        "",
        "django",
        "high-contrast",
        "dark-blue",
        "orange",
        "purple",
        "emerald-bright",  # NEW
    }
```

This guards the AJAX endpoint that fires when a user clicks a swatch in the user menu — without the id in this set, the swap silently fails.

## Test it

1. `uv run python manage.py runserver` — **if a server is already running, restart it** and hard-refresh the browser. The autoreloader watches `.py` files but not `palettes.yaml`, and browsers cache `palettes.css`. (Also make sure you're running the branch that has your changes — a palette that "won't show up" is usually a stale server or the wrong branch, not a code bug.)
2. Open the user menu (avatar dropdown) — your new swatch should appear in the palette grid
3. Click it — the page should re-skin instantly
4. Navigate to `/smallstack/`, `/smallstack/activity/`, `/smallstack/help/`, `/smallstack/backups/`
5. Verify: cards are not warm-gray brown; accent shows on numbers / buttons / sidebar-active; hero band reads correctly

If a band or the hero gradient goes muddy, the palette's accent at low lightness is producing a problematic hue (brown/olive/gray). `palettes.css` already has **two grouped override rules** for this — add your palette's selector to **both** (missing the second is the easy mistake: the band cleans up but the `.hero-section` gradient stays brown):

```css
/* 1. the band VARIABLE — page-header-bleed, toc-header, etc. */
html[data-palette="orange"][data-theme="dark"],
html[data-palette="emerald-bright"][data-theme="dark"],          /* ← add here */
html[data-palette="django"][data-theme="dark"],
html[data-palette="high-contrast"][data-theme="dark"] {
    --accent-band-bg: var(--card-bg);
}

/* 2. .hero-section uses a saturated GRADIENT, not the variable, so it
      has its own sibling override rule just below the first */
html[data-palette="orange"][data-theme="dark"] .hero-section,
html[data-palette="emerald-bright"][data-theme="dark"] .hero-section,   /* ← and here */
html[data-palette="django"][data-theme="dark"] .hero-section,
html[data-palette="high-contrast"][data-theme="dark"] .hero-section {
    background: var(--card-bg) !important;
}
```

Warm and desaturated accents (orange, **gold**, django-emerald, contrast-white) all need both; blue and purple don't.

## Tune an existing palette

If you're not adding a new palette but changing an existing one:

1. **Find the palette block**: `grep -n 'html\[data-palette="<id>"\]\[data-theme="dark"\] {' apps/smallstack/static/smallstack/css/palettes.css`
2. **Change the variables in that block** — only the ones you mean to change
3. **Switch your profile to the palette** via the user menu and verify on every key page (dashboard, activity, backups, help)

## Color-science gotchas — the things this codebase learned the hard way

### Gotcha 1: warm and yellow-shifted accents go muddy at low lightness
- Blue × dark = navy ✓
- Purple × dark = plum ✓
- **Orange × dark = brown ✗**
- **Gold × dark = muddy tan ✗** (shipped: the `gold` palette — the reference case for this fix)
- **Emerald × dark = olive ✗**
- **White × dark = noisy medium gray ✗**

For affected palettes, add the selector to **both** override rules (the `--accent-band-bg` group *and* the `.hero-section` group — see "Test it" above) so bands and hero gradients stay clean.

Also, warm/light accents like gold need **dark** `--button-fg` / `--sidebar-active-fg` (near-black, not white) or button and active-nav text is unreadable on the accent.

### Gotcha 2: bright accents pull neutral surfaces warm
Neutral cards next to bright accents drift warm via complementary-contrast. Mitigate with cool channel bias on surfaces:
- Blue/purple/orange palettes: card-bg = `#161b22` (+12 B vs R)
- Django (emerald — complement is red): card-bg = `#131722` (+15 B vs R, stronger correction)

### Gotcha 3: data-palette must always be set
The blocking script in `base.html` and `setPalette()` in `theme.js` must set `data-palette` on every page load, even when the value is the default ("django"). If they skip it for the default, the default palette's CSS overrides never apply and the page falls back to base `[data-theme="dark"]` (legacy warm-gray). This is fixed in the current codebase — don't reintroduce the skip.

### Gotcha 4: hard-coded `[data-theme="dark"] .X { background: #abc; }` overrides bypass everything
Search for these whenever a page mysteriously stays brown on a new palette:

```bash
grep -rn '\[data-theme="dark"\] \..* {' apps/ | grep -v "var(--"
```

Replace the hex literals with variables (`var(--card-bg)`, `var(--card-border)`, etc.).

## Variables you must override per palette (the minimum)

If you set nothing else, you must set these 9 for a usable dark palette:

```css
--primary
--primary-hover
--sidebar-active-bg
--button-bg
--input-focus-border
--card-bg
--body-bg
--card-border
--link-color
```

Everything else cascades from the base `[data-theme="dark"]` block in `theme.css`. **But you almost certainly want to also override `--card-header-bg`, `--sidebar-bg`, `--footer-bg`, `--input-bg`, `--input-border`, `--text-muted`** — otherwise the page is half-modern-half-legacy and looks jarring.

The cleanest practice: copy the entire dark-blue palette block, change accent values, tweak surface bias if needed. Three lines of accent overrides + 15 lines of surface overrides = a complete palette.

## Light-mode considerations

This skill (and the recent refactor) is dark-mode-first. The light-mode overrides in `palettes.css` are less heavily tested and still use a more traditional "Bootstrap-style" palette. If you want a modern-light palette (Vercel / Linear / Anthropic light), the pattern is:

- Body: pure white or very light gray (`#fafafa`)
- Cards: white, with light hairline border (`#e4e4e7`)
- Accents: same Tailwind -500 values used in dark
- Text: black or near-black

But this skill doesn't prescribe light-mode values — the existing light palettes were left alone in the v0.9.x refactor.

## Related

- [`modern-dark-theme.md`](modern-dark-theme.md) — must-read for page-building
- [`apps/smallstack/docs/theme-architecture.md`](../../apps/smallstack/docs/theme-architecture.md) — color science + variable cascade
- [`apps/smallstack/docs/theme-color-reference.md`](../../apps/smallstack/docs/theme-color-reference.md) — full variable list with current values per palette
- [`adding-your-own-theme.md`](adding-your-own-theme.md) — bigger-scope skill for adding a Tailwind/Bootstrap-style theme alongside SmallStack
