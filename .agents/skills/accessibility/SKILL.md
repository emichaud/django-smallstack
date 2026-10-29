---
name: accessibility
description: "Read before building any page/form/modal — a11y primitives (.sr-only, .skip-link, :focus-visible, trapFocus), the rules, and the pre-\"done\" checklist (WCAG 2.1 AA)"
license: MIT
metadata:
  source: "docs/skills/accessibility.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/accessibility.md` by `make skills-index` — edit the source, not this file.

# Accessibility — building interfaces everyone can use

**Read this before building or editing any page, form, table, modal, or
interactive control in SmallStack.** SmallStack ships accessible foundations
(landmarks, keyboard focus rings, a skip link, a focus-trap primitive, labelled
controls). Your job is to *not regress them* and to reuse the primitives so new
UI is accessible on the first try — the same "fix once in the framework,
everything benefits" model as the theme system.

The target is **WCAG 2.1 AA**. You don't need to memorize WCAG; follow the
patterns below and you'll meet it.

## The primitives — reuse these, don't hand-roll

| Primitive | What it is | Use it for |
|---|---|---|
| `.sr-only` (CSS) | Visually hidden, still announced by screen readers | Giving an icon-only control a name; labelling a region |
| `.skip-link` (CSS) + the link in `base.html` | Keyboard bypass to `<main id="main-content">` | Already global — don't remove it; keep `id="main-content"` on your main |
| `:focus-visible` ring (CSS, global) | Keyboard focus outline on every interactive element | Automatic — just **never** add `outline: none` without a `:focus-visible` replacement |
| `window.SmallStack.trapFocus(el)` (JS) | Confines Tab focus to `el`, returns `release()` that restores focus | Every modal / dialog / popover you open |

All four live in `apps/smallstack/static/smallstack/css/theme.css` (Accessibility
primitives block) and `apps/smallstack/static/smallstack/js/theme.js`
(`trapFocus`).

## The rules (in priority order)

### 1. Every interactive control has an accessible name
A button or link a screen reader can't name is useless to it. Text content
counts as a name. Icon-only controls do **not** — give them one:

```html
<!-- ❌ screen reader announces "button" -->
<button onclick="doThing()"><svg>…</svg></button>

<!-- ✓ aria-label names it; the icon is decorative -->
<button onclick="doThing()" aria-label="Delete ticket">
  <svg aria-hidden="true">…</svg>
</button>

<!-- ✓ or a visible label + sr-only detail -->
<button>Save <span class="sr-only">changes to this ticket</span></button>
```

### 2. Decorative icons are hidden from the accessibility tree
Any `<svg>`/icon that sits **next to text** or **inside a labelled control** is
decorative — add `aria-hidden="true"` so it isn't announced as noise. (An icon
that is the *only* content of an unlabelled control is not decorative — label
the control per rule 1.)

### 3. Never kill the focus ring
Keyboard users navigate by the focus ring. The global `:focus-visible` rule
provides it. Do **not** write `outline: none` on `:focus` — that's the
single most common a11y regression in this codebase. If a design needs the
native outline gone (e.g. inputs), add a `:focus-visible` replacement (a
`box-shadow` ring — see how the input rules do it in theme.css).

### 4. Real elements, real semantics
Use `<button>` for actions and `<a href>` for navigation — never a clickable
`<div>` (it isn't focusable or keyboard-operable, and has no role). Use
landmarks: `<main>`, `<nav aria-label="…">`, `<header>`, `<footer>`, `<aside>`.
Every page has exactly one `<h1>`; don't skip heading levels.

### 5. Modals trap focus, label themselves, and close on Escape
When you build a modal/dialog:

```html
<div id="my-modal" role="dialog" aria-modal="true" aria-labelledby="my-modal-title">
  <h2 id="my-modal-title">Title</h2>
  <button aria-label="Close" onclick="closeMyModal()"><span aria-hidden="true">&times;</span></button>
  …
</div>
```
```js
let release = null;
function openMyModal() {
  modal.classList.add('open');
  release = window.SmallStack.trapFocus(modal);   // reuse the primitive
}
function closeMyModal() {
  modal.classList.remove('open');
  if (release) { release(); release = null; }      // restores prior focus
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMyModal(); });
```
The global stat-card modal (`stat_modal.html`) and the omnibar are the
reference implementations.

### 6. Forms: label every field, announce every error
- Associate labels: `<label for="id_x">` with a matching `id="id_x"`. Django's
  form rendering + the `form_default.html` CRUD template already do this — keep it.
- Required fields use the native `required` attribute (Django adds it); the
  visual `*` is decorative (`aria-hidden="true"`).
- Validation errors are announced: wrap them in `role="alert"` (the CRUD form
  template does this — copy it for custom forms).

### 7. Tables: header cells use `scope`
`<th scope="col">` (and `scope="row"` for row headers) so screen readers can
announce the cell's row/column. The shared CRUD table already does; match it in
custom tables. Prefer `.table-plain` (see the theme skill).

### 8. Don't rely on color alone
A status conveyed only by color (a green/red dot) is invisible to colorblind
users. Pair it with text, an icon shape, or an `.sr-only` label. Semantic tokens
(`--success-fg`/`--warning-fg`/`--error-fg`) set the color; you still add the words.

## Before you say "done" — the checklist

- [ ] Every button/link has an accessible name (visible text or `aria-label`).
- [ ] Decorative icons have `aria-hidden="true"`.
- [ ] You added **no** `outline: none` without a `:focus-visible` replacement.
- [ ] You can operate the whole thing with the keyboard alone (Tab, Enter/Space, Escape).
- [ ] New modals call `trapFocus`, set `role="dialog"`/`aria-modal`/`aria-labelledby`, and close on Escape.
- [ ] Form fields have associated labels; errors use `role="alert"`.
- [ ] Table headers have `scope`.
- [ ] Status isn't conveyed by color alone.
- [ ] The page has one `<h1>` and uses landmarks.

## Verifying

Screenshot with a control focused to confirm the ring shows (the theme skill's
`screenshot_auth` + shot-scraper flow, adding
`--javascript "document.querySelector('SELECTOR').focus()"`). Tab through the
page in a real browser to confirm order and that focus never disappears or gets
trapped behind a modal. Chrome DevTools' Lighthouse and the accessibility tree
inspector catch missing names and contrast issues.

## Anti-patterns (the regressions to avoid)

1. **`outline: none` on `:focus`** with no `:focus-visible` replacement — invisible keyboard focus. (Rule 3.)
2. **Icon-only `<button>`/`<a>` with no `aria-label`** — an unnamed control. (Rule 1.)
3. **Decorative `<svg>` without `aria-hidden`** — screen-reader noise. (Rule 2.)
4. **Clickable `<div>`/`<span>`** for actions — not focusable or keyboard-operable. (Rule 4.)
5. **A modal without `trapFocus`** — keyboard focus escapes behind it. (Rule 5.)
6. **Errors that only appear visually** (no `role="alert"`) — screen-reader users never hear them. (Rule 6.)

## Related

- [`modern-dark-theme.md`](modern-dark-theme.md) — build pages with the CSS variables; a11y and palette-correctness are complementary
- [`templates.md`](templates.md) — template inheritance and the base layout landmarks
