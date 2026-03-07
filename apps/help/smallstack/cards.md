# Cards

Cards are the primary content container in SmallStack. They provide a consistent visual structure with a header and body.

## Basic Card

```html
<div class="card">
    <div class="card-header">
        <h2>Card Title</h2>
    </div>
    <div class="card-body">
        <p>Card content goes here.</p>
    </div>
</div>
```

## Card Without Header

You can use just the body for simple content blocks:

```html
<div class="card">
    <div class="card-body">
        <p>Content without a header.</p>
    </div>
</div>
```

## Multi-Column Cards

Use CSS Grid to place cards side by side:

```html
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
    <div class="card">
        <div class="card-header"><h2>Left</h2></div>
        <div class="card-body"><p>Left column content.</p></div>
    </div>
    <div class="card">
        <div class="card-header"><h2>Right</h2></div>
        <div class="card-body"><p>Right column content.</p></div>
    </div>
</div>
```

Columns stack automatically on mobile via the responsive grid.

## Where SmallStack Uses Cards

- **Dashboard** — stats and activity summaries
- **Profile** — user info and edit forms
- **Activity** — log tables and charts
- **Starter page** — component demos
