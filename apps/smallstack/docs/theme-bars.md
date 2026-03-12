# Theme Bars

Theme bars are a simple stacked horizontal bar visualization for showing proportional data.

![Theme usage bars showing light/dark mode breakdown per color palette](/static/smallstack/help/images/stacked-horizontal-grid.png)

## Basic Usage

```html
<div class="theme-usage-row">
    <div class="theme-bar">
        <div class="theme-bar-segment is-dark" style="width: 65%;"
             title="Dark mode: 65%"></div>
        <div class="theme-bar-segment is-light" style="width: 35%;"
             title="Light mode: 35%"></div>
    </div>
</div>
```

## With Labels

Combine with surrounding HTML to add context:

```html
<div style="display: flex; align-items: center; gap: 12px;">
    <span style="min-width: 80px;">Chrome</span>
    <div class="theme-usage-row" style="flex: 1;">
        <div class="theme-bar">
            <div class="theme-bar-segment is-dark" style="width: 72%;"
                 title="72%"></div>
            <div class="theme-bar-segment is-light" style="width: 28%;"
                 title="28%"></div>
        </div>
    </div>
    <span style="min-width: 40px; text-align: right;">72%</span>
</div>
```

## Segment Types

- `.is-dark` — uses the dark theme color
- `.is-light` — uses the light theme color

Set the width of each segment as a percentage. Segments should add up to 100%.

## Where SmallStack Uses Theme Bars

- **Activity dashboard** — dark/light mode usage breakdown
- **Activity users** — per-user theme preference visualization
