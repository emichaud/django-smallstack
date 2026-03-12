# Getting Started

Every page in SmallStack extends `base.html`, which gives you the topbar, sidebar, breadcrumbs, and theme support automatically.

## Minimal Page Template

```html
{% extends "smallstack/base.html" %}
{% load static theme_tags %}

{% block title %}My Page{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "My Page" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="page-header-with-actions">
    <div class="page-header-content">
        <h1>My Page</h1>
    </div>
</div>

<div class="card">
    <div class="card-header"><h2>Hello</h2></div>
    <div class="card-body">
        <p>Your content here.</p>
    </div>
</div>
{% endblock %}
```

## Creating the View

Add a view in `config/views.py` or your app's `views.py`:

```python
from django.shortcuts import render

def my_page_view(request):
    return render(request, "my_page.html")
```

For pages that require login:

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

class MyPageView(LoginRequiredMixin, TemplateView):
    template_name = "my_page.html"
```

## Adding a URL

In `config/urls.py` or your app's `urls.py`:

```python
from .views import my_page_view

urlpatterns = [
    path("my-page/", my_page_view, name="my_page"),
]
```

## Available Template Blocks

| Block | Purpose |
|-------|---------|
| `title` | Page title in `<title>` tag |
| `breadcrumbs` | Breadcrumb navigation |
| `content` | Main page content |
| `extra_css` | Additional CSS (loaded in `<head>`) |
| `extra_js` | Additional JavaScript (loaded before `</body>`) |

## Enabling / Disabling Features

**Sidebar** — included by default in `base.html`. To hide it, override the sidebar block with an empty block in your template.

**Breadcrumbs** — only appear if you populate the `breadcrumbs` block. Omit the block for no breadcrumbs.

**Login requirement** — use `LoginRequiredMixin` on class-based views or `@login_required` on function views. Without these, pages are public.

**Dark mode** — works automatically via CSS variables. No per-page setup needed.

## Starter Pages

Live template pages you can copy as a starting point:

- [Basic](/starter/basic/) — blank page with just an `<h1>`, topbar, sidebar, and breadcrumbs
- [Forms](/starter/forms/) — date pickers, two-column alignment, file uploads
- [All Components](/starter/) — every component on one page

## Next Steps

Browse the component pages in this section to see what's available:

- [Cards](/help/smallstack/cards/) — content containers
- [Buttons](/help/smallstack/buttons/) — actions and links
- [Forms](/help/smallstack/forms/) — inputs, selects, file uploads
- [Grid Layout](/help/smallstack/grid-layout/) — multi-column pages
- [Messages](/help/smallstack/messages/) — notifications
- [Quick Links](/help/smallstack/quick-links/) — icon navigation grids
- [Navigation](/help/smallstack/navigation/) — sidebar, breadcrumbs, page headers
- [Theme Bars](/help/smallstack/theme-bars/) — data visualization bars
