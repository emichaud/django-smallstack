# Skill: Template System

This skill describes the template structure, inheritance, blocks, and includes in SmallStack.

## Overview

SmallStack uses Django's template system with a single base template that all pages extend. Templates are organized by app in the `templates/` directory.

## File Structure

```
templates/
├── smallstack/
│   ├── base.html              # Master layout (all pages extend this)
│   ├── includes/
│   │   ├── topbar.html        # Top navigation bar
│   │   ├── sidebar.html       # Left sidebar navigation
│   │   ├── messages.html      # Flash messages display
│   │   └── breadcrumbs.html   # Breadcrumb navigation
│   ├── partials/              # htmx swap fragments
│   │   └── messages.html      # OOB messages partial for htmx responses
│   └── pages/                 # SmallStack marketing content (upstream)
│       ├── home_content.html
│       ├── about_content.html
│       ├── starter_content.html
│       ├── starter_css.html
│       └── starter_js.html
├── website/
│   ├── home.html              # Thin wrapper → includes pages/home_content.html
│   └── about.html             # Thin wrapper → includes pages/about_content.html
├── starter.html               # Thin wrapper → includes pages/starter_*.html
├── profile/
│   ├── profile.html
│   ├── profile_edit.html
│   └── profile_detail.html
├── help/
│   ├── help_index.html
│   ├── help_detail.html
│   └── includes/
│       └── help_sidebar.html
└── registration/
    ├── login.html
    ├── logout.html
    ├── signup.html
    └── password_*.html
```

## Base Template Structure

`templates/smallstack/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{% endblock %} | {{ brand.name }}</title>

    <!-- Blocking script prevents theme/sidebar/palette flash -->
    <script>
    (function() {
        var THEME_KEY = 'smallstack-theme';
        var SIDEBAR_KEY = 'smallstack-sidebar-closed';
        var PALETTE_KEY = 'smallstack-palette';
        var theme = localStorage.getItem(THEME_KEY) || 'dark';
        document.documentElement.setAttribute('data-theme', theme);
        var palette = localStorage.getItem(PALETTE_KEY) || '{{ color_palette }}';
        if (palette && palette !== 'django') {
            document.documentElement.setAttribute('data-palette', palette);
        }
        if (window.innerWidth > 768 && localStorage.getItem(SIDEBAR_KEY) === 'true') {
            document.documentElement.classList.add('sidebar-will-close');
        }
    })();
    </script>

    <!-- CSS -->
    <link rel="stylesheet" href="{% static 'admin/css/base.css' %}">
    <link rel="stylesheet" href="{% static 'smallstack/css/theme.css' %}">
    <link rel="stylesheet" href="{% static 'smallstack/css/palettes.css' %}">
    {% block extra_css %}{% endblock %}
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
    <div class="wrapper">
        <!-- Top Navigation -->
        {% include "smallstack/includes/topbar.html" %}

        <div class="main-container">
            <!-- Sidebar -->
            {% include "smallstack/includes/sidebar.html" %}

            <!-- Main Content -->
            <main class="main-content">
                <!-- Breadcrumbs -->
                {% block breadcrumbs %}{% endblock %}

                <!-- Messages -->
                {% include "smallstack/includes/messages.html" %}

                <!-- Page Content -->
                <div class="content-wrapper">
                    {% block content %}{% endblock %}
                </div>
            </main>
        </div>
    </div>

    <!-- Theme configuration -->
    <script>
        window.SMALLSTACK = {
            userTheme: {% if user.is_authenticated and user.profile %}'{{ user.profile.theme_preference }}'{% else %}null{% endif %},
            userPalette: {% if user.is_authenticated and user.profile %}'{{ user.profile.color_palette }}'{% else %}null{% endif %},
            colorPalette: '{{ color_palette }}',
            isAuthenticated: {% if user.is_authenticated %}true{% else %}false{% endif %}
        };
    </script>
    <!-- JavaScript -->
    <script src="{% static 'smallstack/js/htmx.min.js' %}" defer></script>
    <script src="{% static 'smallstack/js/theme.js' %}"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

## Template Blocks

| Block | Purpose | Location |
|-------|---------|----------|
| `title` | Page title (before " \| SmallStack") | `<title>` |
| `extra_css` | Additional stylesheets | `<head>` |
| `breadcrumbs` | Breadcrumb navigation | Before content |
| `content` | Main page content | Main area |
| `extra_js` | Additional scripts | Before `</body>` |

## Thin Wrapper + Include Pattern

SmallStack's marketing pages (`home`, `about`, `starter`) use a pattern to prevent merge conflicts in downstream projects:

- **Wrapper templates** (`templates/website/home.html`, etc.) are ~10-line files that `{% extend %}` the base and `{% include %}` a content fragment
- **Content fragments** (`templates/smallstack/pages/`) contain the actual SmallStack marketing markup

Downstream projects replace the wrapper's `{% include %}` with their own content. SmallStack marketing updates land in `smallstack/pages/` — a directory downstream never touches — so no conflicts.

**Default wrapper:**
```html
{% extends "smallstack/base.html" %}
{% load theme_tags static %}
{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}
{% block content %}
{% include "smallstack/pages/home_content.html" %}
{% endblock %}
```

**Customized wrapper (downstream):**
```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}
{% block title %}Home{% endblock %}
{% block breadcrumbs %}{% endblock %}
{% block content %}
<h1>My Custom Homepage</h1>
{% endblock %}
```

**Important:** Each `{% include %}` fragment has its own `{% load static theme_tags %}` at the top, since `{% include %}` doesn't inherit parent template loads.

## Extending Base Template

Every page template should extend `base.html`:

```html
{% extends "smallstack/base.html" %}
{% load static theme_tags %}

{% block title %}My Page Title{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{% static 'app_myapp/css/myapp.css' %}">
{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "home" %}
{% breadcrumb "My Page" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h1>My Page</h1>
    </div>
    <div class="card-body">
        <p>Page content here</p>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{% static 'app_myapp/js/myapp.js' %}"></script>
{% endblock %}
```

## Template Tags

Load with `{% load theme_tags %}`:

### Breadcrumbs

```html
{% breadcrumb "Label" "url_name" %}     {# With link #}
{% breadcrumb "Label" "url_name" pk %}  {# With URL argument #}
{% breadcrumb "Label" %}                 {# No link (current page) #}
{% render_breadcrumbs %}                 {# Output the breadcrumbs #}
```

**Example:**
```html
{% breadcrumb "Home" "home" %}
{% breadcrumb "Users" "user_list" %}
{% breadcrumb user.username "profile_detail" user.username %}
{% breadcrumb "Edit" %}
{% render_breadcrumbs %}
```

### Navigation Active State

```html
{% nav_active "url_name" %}              {# Single URL #}
{% nav_active "url_name1" "url_name2" %} {# Multiple URLs #}
```

**Example:**
```html
<a href="{% url 'home' %}" class="nav-link {% nav_active 'home' %}">Home</a>
<a href="{% url 'help:index' %}" class="nav-link {% nav_active 'help:index' 'help:detail' %}">Help</a>
```

## Include Templates

### Topbar (`includes/topbar.html`)

Contains:
- Mobile menu toggle
- Site logo/name
- Theme toggle (dark/light)
- User menu (login/signup or user dropdown)

### Sidebar (`includes/sidebar.html`)

Contains:
- Navigation links
- Section titles
- Admin link (for staff)

**Adding a link:**
```html
<li class="nav-item">
    <a href="{% url 'myapp:list' %}" class="nav-link {% nav_active 'myapp:list' %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="..."/>
        </svg>
        <span>My Feature</span>
    </a>
</li>
```

**Adding a section:**
```html
<li class="nav-section-title">My Section</li>
```

### Messages (`includes/messages.html`)

Displays Django messages framework alerts:

```html
{% if messages %}
<div class="messages-container">
    {% for message in messages %}
    <div class="message {{ message.tags }}">
        {{ message }}
    </div>
    {% endfor %}
</div>
{% endif %}
```

**Using in views:**
```python
from django.contrib import messages

def my_view(request):
    messages.success(request, "Operation completed!")
    messages.error(request, "Something went wrong.")
    messages.warning(request, "Please check your input.")
    messages.info(request, "FYI: Something happened.")
```

## Common Patterns

### Card Layout

```html
<div class="card">
    <div class="card-header">
        <h2>Card Title</h2>
    </div>
    <div class="card-body">
        Content here
    </div>
</div>
```

### Form Template

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Create Item{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "home" %}
{% breadcrumb "Items" "item_list" %}
{% breadcrumb "Create" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h1>Create Item</h1>
    </div>
    <div class="card-body">
        <form method="post" enctype="multipart/form-data">
            {% csrf_token %}

            {% for field in form %}
            <div class="form-group">
                <label for="{{ field.id_for_label }}">{{ field.label }}</label>
                {{ field }}
                {% if field.help_text %}
                <span class="helptext">{{ field.help_text }}</span>
                {% endif %}
                {% if field.errors %}
                <ul class="errorlist">
                    {% for error in field.errors %}
                    <li>{{ error }}</li>
                    {% endfor %}
                </ul>
                {% endif %}
            </div>
            {% endfor %}

            <div class="form-actions">
                <button type="submit" class="button button-primary">Save</button>
                <a href="{% url 'item_list' %}" class="button">Cancel</a>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

### List Template

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Items{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "home" %}
{% breadcrumb "Items" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h1>Items</h1>
        <a href="{% url 'item_create' %}" class="button button-primary">Add Item</a>
    </div>
    <div class="card-body">
        {% if items %}
        <table class="table">
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Created</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for item in items %}
                <tr>
                    <td>{{ item.title }}</td>
                    <td>{{ item.created_at|date:"M d, Y" }}</td>
                    <td>
                        <a href="{% url 'item_detail' item.pk %}">View</a>
                        <a href="{% url 'item_edit' item.pk %}">Edit</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p>No items yet. <a href="{% url 'item_create' %}">Create one</a>.</p>
        {% endif %}
    </div>
</div>
{% endblock %}
```

### Detail Template

```html
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}{{ item.title }}{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "home" %}
{% breadcrumb "Items" "item_list" %}
{% breadcrumb item.title %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h1>{{ item.title }}</h1>
        <a href="{% url 'item_edit' item.pk %}" class="button">Edit</a>
    </div>
    <div class="card-body">
        <p>{{ item.description }}</p>
        <p class="text-muted">Created: {{ item.created_at|date:"F d, Y" }}</p>
    </div>
</div>
{% endblock %}
```

## Conditional Content

### Authentication

```html
{% if user.is_authenticated %}
    <p>Welcome, {{ user.username }}</p>
{% else %}
    <p>Please <a href="{% url 'login' %}">log in</a>.</p>
{% endif %}
```

### Staff/Admin

```html
{% if user.is_staff %}
    <a href="{% url 'admin:index' %}">Admin Panel</a>
{% endif %}
```

### Permissions

```html
{% if perms.app_label.can_edit %}
    <a href="{% url 'item_edit' item.pk %}">Edit</a>
{% endif %}
```

## Static Files

Core SmallStack assets are namespaced under `static/smallstack/`. Project-specific assets go in `static/brand/`, `static/css/`, `static/js/`.

```html
{% load static %}

<!-- Core SmallStack assets (upstream) -->
<link rel="stylesheet" href="{% static 'smallstack/css/theme.css' %}">
<script src="{% static 'smallstack/js/theme.js' %}"></script>

<!-- Project assets (downstream) -->
<link rel="stylesheet" href="{% static 'css/project.css' %}">
<img src="{% static 'brand/my-logo.svg' %}">
```

## URL Generation

```html
{% url 'home' %}                          {# Named URL #}
{% url 'item_detail' item.pk %}           {# With argument #}
{% url 'help:detail' slug='getting-started' %}  {# Namespaced with kwarg #}
```

## htmx Integration

SmallStack includes [htmx](https://htmx.org/) for progressive enhancement. htmx is loaded in `base.html` with `defer`, and CSRF is handled automatically via `hx-headers` on `<body>`.

### htmx Form Example

Convert any form to use htmx by replacing `method="post"` with `hx-post`:

```html
<form hx-post="{% url 'myapp:create' %}"
      hx-target="#item-list"
      hx-swap="innerHTML">
    {{ form.as_p }}
    <button type="submit" class="button button-primary">Save</button>
</form>
```

No `{% csrf_token %}` needed — it's handled by `hx-headers` on `<body>`.

### Partial Templates

Place htmx response fragments in `templates/<app>/partials/`:

```
templates/myapp/
├── item_list.html           # Full page
└── partials/
    └── item_table.html      # htmx fragment (just the table)
```

### Dual-Response Views

Return full pages or partials based on `request.htmx`:

```python
def item_list(request):
    items = Item.objects.filter(user=request.user)
    if request.htmx:
        return render(request, "myapp/partials/item_table.html", {"items": items})
    return render(request, "myapp/item_list.html", {"items": items})
```

See [htmx-patterns.md](../skills/htmx-patterns.md) for the full reference including OOB messages and JS integration.

## Best Practices

1. **Always extend base.html** - Maintains consistent layout
2. **Use blocks appropriately** - Don't put CSS in content block
3. **Load tags at top** - `{% load static theme_tags %}`
4. **Use {% url %}** - Never hardcode URLs
5. **Use {% static %}** - Never hardcode static paths
6. **Include CSRF token** - In standard forms: `{% csrf_token %}` (htmx forms get it automatically)
7. **Escape user content** - Django auto-escapes, use `|safe` only when needed
8. **Use includes** - For reusable components
9. **Use htmx for interactions** - Partial updates instead of full page reloads
