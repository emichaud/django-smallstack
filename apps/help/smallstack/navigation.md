# Navigation

SmallStack includes three navigation components: sidebar, breadcrumbs, and page headers.

## Sidebar

The sidebar is defined in `templates/smallstack/includes/sidebar.html`. Add links using `.nav-item` and `.nav-link`:

```html
<li class="nav-item">
    <a href="{% url 'my_page' %}" class="nav-link {% nav_active 'my_page' %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <!-- icon path -->
        </svg>
        <span>My Page</span>
    </a>
</li>
```

### Section Titles

Group sidebar links with section titles:

```html
<li class="nav-section-title">Admin</li>
```

### Active State

Use the `{% nav_active %}` template tag (from `theme_tags`) to highlight the current page:

```html
class="nav-link {% nav_active 'url_name' %}"
```

This adds the `active` class when the current URL matches.

## Breadcrumbs

Add breadcrumbs in the `breadcrumbs` block using template tags:

```html
{% load theme_tags %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Section" "section_url" %}
{% breadcrumb "Current Page" %}
{% render_breadcrumbs %}
{% endblock %}
```

- Items with a URL become clickable links
- The last item (no URL) is displayed as the current page
- Omit the `breadcrumbs` block entirely to hide breadcrumbs

## Page Headers

Use `.page-header-with-actions` for page titles with action buttons:

```html
<div class="page-header-with-actions">
    <div class="page-header-content">
        <h1>Page Title</h1>
        <p class="page-subtitle">Optional subtitle text.</p>
    </div>
    <div class="page-header-actions">
        <a href="/docs/" class="button button-secondary">View Docs</a>
        <button class="button button-primary button-prominent">
            Create New
        </button>
    </div>
</div>
```

The header flexes: title on the left, actions on the right. Stacks on mobile.

## Where SmallStack Uses Navigation

- **Sidebar** — all pages (Home, Profile, Help, Admin)
- **Breadcrumbs** — help pages, profile, starter
- **Page headers** — starter page, activity dashboard
