# htmx Patterns in SmallStack

SmallStack uses [htmx](https://htmx.org/) for progressive enhancement — adding partial page updates without a build step or heavy JavaScript framework.

## Setup

### Dependencies

- `django-htmx>=1.19` in `pyproject.toml`
- `django_htmx.middleware.HtmxMiddleware` in `MIDDLEWARE` (after `MessageMiddleware`)

### Static Asset

htmx is vendored at `static/smallstack/js/htmx.min.js` (no CDN dependency). It's loaded with `defer` in `base.html`.

### CSRF

The `<body>` tag in `base.html` includes:

```html
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
```

This automatically sends the CSRF token with every htmx request — no per-form setup needed.

## Template Conventions

### Partial Templates

Place htmx partials in `templates/<app>/partials/` or `templates/smallstack/partials/`:

```
templates/
  smallstack/
    includes/     # Full-page includes (sidebar, topbar, etc.)
    partials/     # htmx swap fragments
      messages.html
  myapp/
    partials/
      item_row.html
```

### OOB (Out-of-Band) Messages

`templates/smallstack/partials/messages.html` uses `hx-swap-oob="true"` to update the messages container on any htmx response:

```html
<div id="messages-container" class="messages-container" hx-swap-oob="true">
    {% for message in messages %}
    <div class="message {{ message.tags }}" role="alert">
        <span class="message-text">{{ message }}</span>
        <button type="button" class="message-close" aria-label="Close">&times;</button>
    </div>
    {% endfor %}
</div>
```

Include this in any htmx partial response to show messages without a full page reload.

## View Patterns

### Dual-Response Views

Use `request.htmx` (provided by django-htmx middleware) to return either a full page or a partial:

```python
from django.shortcuts import render

def my_view(request):
    context = {"items": Item.objects.all()}

    if request.htmx:
        return render(request, "myapp/partials/item_list.html", context)

    return render(request, "myapp/item_list.html", context)
```

### htmx-Only Endpoints

For endpoints that only serve htmx (like the theme preference save), return minimal responses:

```python
from django.http import HttpResponse
from django.views.decorators.http import require_POST

@require_POST
def save_preference(request):
    # ... save data ...
    return HttpResponse(status=204)  # No content needed
```

## Converting a Form to htmx

### Before (Full POST/redirect/GET)

```html
<form method="post" action="{% url 'myapp:create' %}">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit">Save</button>
</form>
```

### After (htmx partial update)

```html
<form hx-post="{% url 'myapp:create' %}"
      hx-target="#item-list"
      hx-swap="innerHTML">
    {{ form.as_p }}
    <button type="submit">Save</button>
</form>
```

No `{% csrf_token %}` needed in the form — it's handled by `hx-headers` on `<body>`.

## JavaScript Integration

### Re-initializing After Swaps

`theme.js` listens for `htmx:afterSettle` to re-initialize message auto-dismiss on swapped content:

```javascript
document.addEventListener('htmx:afterSettle', function() {
    initMessages();
});
```

Use this pattern for any JS that needs to bind to dynamically inserted DOM elements.

### Triggering htmx from JS

The theme toggle saves preferences via:

```javascript
htmx.ajax('POST', '/profile/theme/', {
    values: { theme: theme },
    swap: 'none'
});
```

## Existing htmx Features

| Feature | Endpoint | Method |
|---------|----------|--------|
| Theme preference save | `POST /profile/theme/` | htmx.ajax from theme.js |
| Palette preference save | `POST /profile/palette/` | htmx.ajax from theme.js |
