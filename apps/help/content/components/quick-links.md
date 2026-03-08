# Quick Links

Quick links provide an icon-based navigation grid, useful for dashboards and landing pages.

## Basic Usage

```html
<div class="quick-links">
    <a href="/dashboard/" class="quick-link">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
            <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>
        </svg>
        <span>Dashboard</span>
    </a>
    <a href="/settings/" class="quick-link">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
            <path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58..."/>
        </svg>
        <span>Settings</span>
    </a>
    <a href="/help/" class="quick-link">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10..."/>
        </svg>
        <span>Help</span>
    </a>
</div>
```

## Inside a Card

Quick links work well inside a card body:

```html
<div class="card">
    <div class="card-header"><h2>Quick Links</h2></div>
    <div class="card-body">
        <div class="quick-links">
            <a href="/" class="quick-link">
                <svg><!-- icon --></svg>
                <span>Home</span>
            </a>
            <!-- more links -->
        </div>
    </div>
</div>
```

## Notes

- Links wrap automatically based on container width
- Each `.quick-link` shows an icon above a text label
- Use any 24x24 SVG icon
- Works in both light and dark mode

## Where SmallStack Uses Quick Links

- **Starter page** — navigation demo
- **Home page** — can be added for quick navigation
