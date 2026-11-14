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
│   └── pages/                 # SmallStack's home content (upstream)
│       └── home_content.html
├── website/
│   ├── base.html              # The public site's base
│   └── home.html              # Thin wrapper → includes pages/home_content.html
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

`apps/smallstack/templates/smallstack/base.html` (abridged):

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{% endblock %} | {{ brand.name }}</title>

    <!-- Blocking theme/sidebar/palette script: prevents a flash of the wrong theme -->
    <script src="{% static 'smallstack/js/theme-init.js' %}"
            data-user-theme="{% if user.is_authenticated and user.profile %}{{ user.profile.theme_preference }}{% endif %}"
            data-user-palette="{% if user.is_authenticated and user.profile %}{{ user.profile.color_palette }}{% endif %}"
            data-palette="{{ color_palette }}" data-default-palette="django" data-sidebar-no-transition></script>

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

    <!-- Theme configuration, read by theme.js. data-theme-url / data-palette-url
         are where the toggle saves a signed-in user's choice: without them it
         changes only this browser, and the profile's theme wins on the next load. -->
    <script src="{% static 'smallstack/js/config.js' %}"
            data-user-theme="{% if user.is_authenticated and user.profile %}{{ user.profile.theme_preference }}{% endif %}"
            data-user-palette="{% if user.is_authenticated and user.profile %}{{ user.profile.color_palette }}{% endif %}"
            data-color-palette="{{ color_palette }}"
            data-authenticated="{% if user.is_authenticated %}true{% else %}false{% endif %}"
            data-sidebar-enabled="{{ smallstack_sidebar_enabled|yesno:'true,false' }}"
            data-sidebar-default="{{ smallstack_sidebar_default }}"
            data-topbar-nav-enabled="{{ smallstack_topbar_nav_enabled|yesno:'true,false' }}"
            data-theme-url="{% url 'theme_preference' %}"
            data-palette-url="{% url 'palette_preference' %}"></script>
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
| `page_header` | Full-bleed colored header bar (outside `.content-wrapper`) | Before content wrapper |
| `content` | Main page content (inside `.content-wrapper`) | Main area |
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

**Sidebar active-state gotcha for help sections:**
The "Help & Docs" link uses path-based matching (`'/smallstack/help/' in request.path`) and must explicitly exclude any help section that has its own sidebar link. When adding a new sidebar link that points to a help path, add a `not in request.path` exclusion to the "Help & Docs" link so both don't highlight at once.

Similarly, the "SmallStack" link matches all `/smallstack/help/smallstack` paths. The "Components" sidebar link points to `/smallstack/help/smallstack/components` — so SmallStack excludes that path to avoid double-highlighting.

```html
<!-- Help & Docs excludes /smallstack/help/smallstack -->
<a class="nav-link {% if '/smallstack/help/' in request.path and '/smallstack/help/smallstack' not in request.path %}active{% endif %}">

<!-- SmallStack excludes /smallstack/help/smallstack/components -->
<a class="nav-link {% if '/smallstack/help/smallstack' in request.path and '/smallstack/help/smallstack/components' not in request.path %}active{% endif %}">

<!-- Components matches only its own page -->
<a class="nav-link {% if '/smallstack/help/smallstack/components' in request.path %}active{% endif %}">
```

When adding a new sidebar link to a page within SmallStack docs, follow this pattern: add an exclusion to the parent link and a specific path check on the new link.

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

{% block page_header %}
<div class="page-header-bleed">
    <div class="page-header-content">
        <h1>Create Item</h1>
        <p class="page-subtitle">Add a new item</p>
    </div>
</div>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-body">
        <form method="post" class="crud-form" enctype="multipart/form-data">
            {% csrf_token %}
            {% for field in form %}
            <div class="crud-field{% if field.errors %} has-error{% endif %}">
                <label class="crud-label">
                    {{ field.label }}
                    {% if field.field.required %}<span class="required">*</span>{% endif %}
                </label>
                {{ field }}
                {% if field.help_text %}<div class="crud-help">{{ field.help_text }}</div>{% endif %}
                {% if field.errors %}<div class="crud-error">{{ field.errors.0 }}</div>{% endif %}
            </div>
            {% endfor %}
            <div class="crud-actions">
                <button type="submit" class="btn-save">Save</button>
                <a href="{% url 'item_list' %}" class="btn-cancel">Cancel</a>
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

{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>Items</h1>
        <p class="page-subtitle">All items</p>
    </div>
    <div class="page-header-actions">
        <a href="{% url 'item_create' %}" class="btn-primary">+ Add Item</a>
    </div>
</div>
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-body">
        {% if items %}
        <table class="crud-table">
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Created</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for item in items %}
                <tr>
                    <td><a href="{% url 'item_detail' item.pk %}">{{ item.title }}</a></td>
                    <td>{{ item.created_at|date:"M d, Y" }}</td>
                    <td><span class="badge badge-success">Active</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color: var(--body-quiet-color); padding: 2rem 0; text-align: center;">
            No items yet. <a href="{% url 'item_create' %}" style="color: var(--primary);">Create one</a>.
        </p>
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

{% block page_header %}
<div class="page-header-bleed page-header-with-actions">
    <div class="page-header-content">
        <h1>{{ item.title }}</h1>
        <p class="page-subtitle">Item detail</p>
    </div>
    <div class="page-header-actions">
        <a href="{% url 'item_edit' item.pk %}" class="btn-primary">Edit</a>
        <button type="button" class="btn-danger"
            data-delete-url="{% url 'item_delete' item.pk %}"
            onclick="crudDeleteModal(this, '{{ item }}')">Delete</button>
    </div>
</div>
{% endblock %}

{% block content %}
<div class="card" data-list-url="{% url 'item_list' %}">
    <div class="card-body">
        <p>{{ item.description }}</p>
        <p style="color: var(--body-quiet-color);">Created: {{ item.created_at|date:"F d, Y" }}</p>
    </div>
</div>
{% include "smallstack/crud/includes/delete_modal.html" %}
{% endblock %}
```

> **Tip:** For a full copy-paste starter with all page sections, copy `apps/showcase/templates/showcase/includes/starter_content.html` (the page at `/starter/`, from the deletable `apps/showcase`). See [admin-page-styling.md](admin-page-styling.md) for the complete CSS class reference.

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

## Behaviour without inline JavaScript

**The CSP's `script-src` is `'self'` with no `'unsafe-inline'`.** The browser runs no inline
`<script>` block and no `onclick="…"`; it logs the blocked line in the console instead.

### Moving an existing project onto the policy

**Size it first:** `uv run python manage.py template_hygiene` lists every inline `<script>`, `on…=`
handler and `<style>` block, by file and line (`--summary` gives counts per file, `--check` exits 1
while any script or handler is left, `--framework` limits it to SmallStack's own templates).

**The stopgap:** add `"'unsafe-inline'"` back to `CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"]`
and your inline code runs again while you move it. The hygiene tests follow the policy in force
(the rules live in `apps/smallstack/template_hygiene.py`):

| `script-src` | Script + handler sweeps cover | `test_csp_script_src_allows_no_inline_script` |
|---|---|---|
| no `'unsafe-inline'` | every template, yours included, since the browser blocks them all | passes |
| `'unsafe-inline'` (stopgap) | SmallStack's own templates only | skips, naming how many of yours remain |

The `<style>` sweep covers SmallStack's own templates only, under either policy. `style-src` allows
inline styles, so yours break nothing.

**A step between the two: nonces.** Rather than reopen every inline script, keep a block you can't
move yet and give it django-csp's per-request nonce:

```python
from csp.constants import NONCE

CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"] = ["'self'", NONCE]
```
```django
<script nonce="{{ request.csp_nonce }}">…</script>
```

A browser that sees a nonce in `script-src` ignores `'unsafe-inline'` there, so it's one route or the
other, not both. A nonce can't cover an `on…=` handler, so move the handlers to data- attributes
(below) first. Under a nonce policy the script sweep doesn't count a block that carries `nonce=`.

### Scripts are static files

Put page JavaScript in the app's `static/`. SmallStack mirrors the template tree, so
`apps/runbook/templates/runbook/dashboard.html` loads `runbook/js/templates/dashboard.js`. Load it
with a plain `<script src="{% static '…' %}"></script>` where the block used to be. Without
`defer`, it runs at the same point in parsing as the inline code did.

**Server values ride on the script's own tag:**

```django
<script src="{% static 'myapp/js/templates/widget_form.js' %}"
        data-save-url="{% url 'myapp:save' object.pk %}"
        data-csrf-token="{{ csrf_token }}"></script>
```
```js
var widgetFormConfig = document.currentScript.dataset;   // read once, at load
fetch(widgetFormConfig.saveUrl, { headers: { 'X-CSRFToken': widgetFormConfig.csrfToken } });
```

- **Name the config after the file** (`widgetFormConfig`, not `config`). Two scripts on one page
  share the global scope.
- **Read `document.currentScript` at the top level**, not inside a later callback, because it's
  only set while the script runs.
- **Lists and objects go in a JSON data block:** `{{ rows|json_script:"widget-rows" }}`, or a
  hand-rendered `<script type="application/json" id="…">` using `|escapejs` for values. Read it
  with `JSON.parse(document.getElementById('widget-rows').textContent)`. The CSP doesn't block
  non-executable types.
- **Theme before first paint:** a new page shell loads `smallstack/js/theme-init.js` in `<head>`
  (`data-palette="{{ color_palette }}" data-default-palette="django"`), not a copy of the snippet.

`test_no_template_has_an_inline_script_block` fails on an inline executable block.

### Page CSS is a static file too

A page's own CSS goes in a stylesheet, not a `<style>` block: `apps/<app>/static/<app>/css/templates/<template>.css`,
mirroring the template tree. Link it from `{% block extra_css %}` (or where the block was, for
an include). `test_no_template_has_an_inline_style_block` enforces this; the only exceptions
are `500.html`, which must render without static files, and the Swagger page. The CSP's
`style-src` still allows inline `style="…"` attributes. Prefer the theme's classes and
`var(--…)` tokens over long `style` attributes anyway (see `modern-dark-theme.md`).

**A new app `static/` directory needs a dev-server restart:** Django's app static finder lists
those directories at startup. `collectstatic` (production) always sees them.

### Event handlers

Never write `onclick="…"`, `onsubmit="…"` or any other inline handler. `make test` fails on
one (`test_no_template_has_an_inline_event_handler`), and the CSP blocks it anyway. Declare the behaviour with a data- attribute instead;
`smallstack/js/theme.js` (on every page) carries it out:

| Instead of | Write |
|---|---|
| `onsubmit="return confirm('Delete it?')"` | `<form data-confirm="Delete it?">` (also on an `<a>` or `<button>`) |
| `onchange="this.form.submit()"` | `<select data-autosubmit>` |
| `onclick="openStatModal('Title', this)"` | `data-stat-modal="Title"` (with `hx-get` + `hx-target="#stat-modal-body"`) |
| `onclick="closeStatModal()"` | `data-stat-modal-close` |
| copy a value to the clipboard | `data-copy="element-id"` or `data-copy-text="literal"` |
| `scrollIntoView` | `data-scroll-to="#id"` |
| toggle a class on a container | `data-toggle-class="open" data-toggle-on=".panel"` |
| make one tab/button `.active` | `data-activate-in=".tab-bar"` on each button |
| Enter/Space on a `role="button"` div | `data-keyclick` |
| `onclick="myFunction('x', this)"` | `data-ss-action="myFunction" data-ss-args='["x", "$this"]'` |

**Page actions are an allow-list.** `data-ss-action` only calls a function a script registered:

```html
<button type="button" data-ss-action="openPanel" data-ss-args='["settings", "$this"]'>Settings</button>
<script>
function openPanel(name, button) { … }
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { openPanel: window.openPanel });
</script>
```

- **The arguments are a JSON array.** `"$this"` is the clicked element and `"$event"` is the
  event.
- **A template value inside the JSON gets `|escapejs`**, as in
  `data-ss-args='["$this", "{{ obj.name|escapejs }}"]'`. Its `\uXXXX` output is valid JSON and
  survives attribute decoding; autoescape's `&quot;` would break the JSON. A test checks this.
- **Optional modifiers:**
  - `data-ss-on="change"` runs the action on change instead of click.
  - `data-ss-self` runs it only when the click is on the element itself (a modal backdrop).
  - `data-ss-prevent` stops a link from navigating (keep a real `href` as the no-JS fallback).
- **A test fails on any `data-ss-action` name that no script registers.**
- **The `data-ss-` prefix is deliberate.** A project's own `data-action` (Stimulus, or the blog
  studio's submit buttons) never collides with it.

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
