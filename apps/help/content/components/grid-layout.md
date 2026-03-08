# Grid Layout

SmallStack uses CSS Grid for multi-column layouts. No framework classes needed — just inline styles or your own CSS.

## Two-Column Grid

```html
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
    <div class="card">
        <div class="card-header"><h2>Column 1</h2></div>
        <div class="card-body"><p>Left content.</p></div>
    </div>
    <div class="card">
        <div class="card-header"><h2>Column 2</h2></div>
        <div class="card-body"><p>Right content.</p></div>
    </div>
</div>
```

## Three-Column Grid

```html
<div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px;">
    <div class="card">
        <div class="card-body"><p>First</p></div>
    </div>
    <div class="card">
        <div class="card-body"><p>Second</p></div>
    </div>
    <div class="card">
        <div class="card-body"><p>Third</p></div>
    </div>
</div>
```

## Responsive Stacking

For grids that stack on mobile, add a media query in your `extra_css` block:

```html
{% block extra_css %}
<style>
    .my-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
    }
    @media (max-width: 768px) {
        .my-grid {
            grid-template-columns: 1fr;
        }
    }
</style>
{% endblock %}
```

## Unequal Columns

```html
<div style="display: grid; grid-template-columns: 2fr 1fr; gap: 24px;">
    <div class="card">
        <div class="card-body"><p>Wide column (2/3).</p></div>
    </div>
    <div class="card">
        <div class="card-body"><p>Narrow column (1/3).</p></div>
    </div>
</div>
```

## Where SmallStack Uses Grids

- **Dashboard** — stats cards in a multi-column layout
- **Activity** — charts and tables side by side
- **Starter page** — two-column card demo
