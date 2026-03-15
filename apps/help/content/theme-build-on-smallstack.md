---
title: "Scenario C: Build on SmallStack's Theme"
description: "Use SmallStack's built-in theme for everything. The fastest path."
---

# Scenario C: Build on SmallStack's Theme

You want to use SmallStack's built-in theme — sidebar, topbar, cards, dark mode, palettes — for your entire app. No external CSS framework. This is the fastest path.

## What You're Building

```
All pages:        SmallStack theme (sidebar + topbar + cards)
Login/Signup:     SmallStack theme
Admin tools:      SmallStack theme (same look, seamless)
Custom pages:     Extend smallstack/base.html, use built-in CSS classes
```

## Step 1: Update Branding

In `config/settings/base.py`:

```python
BRAND_NAME = "My App"
```

This updates the sidebar, topbar, page titles, and footer everywhere. For logos, favicon, and other brand assets, see [Settings & Configuration](/help/smallstack/settings-configuration/).

## Step 2: Customize Your Homepage

Edit `templates/website/home.html`. It already extends SmallStack's base:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header"><h2>Welcome</h2></div>
    <div class="card-body">
        <p>This is my app. There are many like it, but this one is mine.</p>
    </div>
</div>
{% endblock %}
```

## Step 3: Add Pages

Every page follows the same pattern: **view, URL, template, optional nav item**.

**View** in `apps/website/views.py`:

```python
def pricing_view(request):
    return render(request, "website/pricing.html")
```

**URL** in `apps/website/urls.py`:

```python
path("pricing/", views.pricing_view, name="pricing"),
```

**Template** at `templates/website/pricing.html`:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Pricing{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Pricing" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header"><h2>Pricing</h2></div>
    <div class="card-body">
        <p>Your pricing content here.</p>
    </div>
</div>
{% endblock %}
```

**Nav item** (optional) in `apps/website/apps.py`:

```python
nav.register(
    section="main",
    label="Pricing",
    url_name="website:pricing",
    order=50,
)
```

## Step 4: Use SmallStack's CSS

SmallStack's theme is built on Django's admin CSS, extended with custom properties. You don't need to install anything — it's already loaded. Use these patterns:

### Cards

```html
<div class="card">
    <div class="card-header"><h3>Title</h3></div>
    <div class="card-body">Content</div>
</div>
```

### Buttons

```html
<a href="#" class="btn">Primary Button</a>
<button class="btn btn-secondary">Secondary</button>
```

### Forms

```html
<form method="post">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit" class="btn">Save</button>
</form>
```

### Grid Layout

```html
<div class="grid-row">
    <div class="grid-col-6">Left half</div>
    <div class="grid-col-6">Right half</div>
</div>
```

### CSS Variables

All colors respond to dark mode and palette selection automatically:

```css
.my-widget {
    background: var(--card-bg);
    color: var(--body-fg);
    border: 1px solid var(--card-border);
}

.my-highlight {
    color: var(--primary);
}
```

For the full component reference, see the [Starter Page](/starter/) or individual guides: [Cards](/help/smallstack/cards/), [Buttons](/help/smallstack/buttons/), [Forms](/help/smallstack/forms/), [Grid Layout](/help/smallstack/grid-layout/).

## Step 5: Pick a Color Palette

SmallStack ships with 5 palettes. Set the default in `config/settings/base.py`:

```python
SMALLSTACK_COLOR_PALETTE = "django"          # default blue
SMALLSTACK_COLOR_PALETTE = "purple"          # purple accent
SMALLSTACK_COLOR_PALETTE = "orange"          # orange accent
SMALLSTACK_COLOR_PALETTE = "dark-blue"       # deep blue
SMALLSTACK_COLOR_PALETTE = "high-contrast"   # accessibility-focused
```

Users can also choose their own palette from Profile settings.

## That's It

No extra CSS frameworks to install. No theme conflicts to manage. Everything uses the same sidebar, topbar, dark mode, and palette system. Your pages look and feel like the built-in tools because they *are* the same theme.

## Related

- [Getting Started](/help/getting-started/) — Full first-run walkthrough
- [Theming & Customization](/help/smallstack/theming/) — CSS variables, dark mode, palettes in depth
- [Components](/help/smallstack/components/) — Blank page template
- [Building CRUD Pages](/help/smallstack/building-crud-pages/) — Management pages for your models
