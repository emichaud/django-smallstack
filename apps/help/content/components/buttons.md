# Buttons

SmallStack provides several button styles. All use the `.button` base class.

## Button Variants

```html
<button class="button button-primary">Primary</button>
<button class="button button-primary button-prominent">Prominent</button>
<button class="button button-secondary">Secondary</button>
<button class="button button-small">Small</button>
```

- **Primary** — main actions (submit, save)
- **Prominent** — high-emphasis actions (create, primary CTA)
- **Secondary** — cancel, back, less important actions
- **Small** — compact buttons for tight spaces

## Links as Buttons

Any `<a>` tag can use button classes:

```html
<a href="/some-page/" class="button button-primary">Go There</a>
```

## Buttons with Icons

Add an SVG icon before the label text:

```html
<button class="button button-primary">
    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
        <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
    </svg>
    Add Item
</button>
```

## Delete Button Style

Use the `--delete-button-bg` CSS variable for destructive actions:

```html
<button class="button button-secondary" style="color: var(--delete-button-bg);">
    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
        <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
    </svg>
    Delete
</button>
```

## Where SmallStack Uses Buttons

- **Page headers** — action buttons in `.page-header-actions`
- **Forms** — submit and cancel buttons
- **Cards** — inline actions
