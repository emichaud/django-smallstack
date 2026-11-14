---
title: Plain Django on SmallStack
description: Write an app the way you would in any Django project. SmallStack stays out of the way.
---

# Plain Django on SmallStack

SmallStack is a Django project, not a replacement for Django. A function view, a `ModelForm`, a template and a pytest test work here exactly as they do anywhere else, and they get SmallStack's login, theme, navigation and security headers for free. This page builds a small app that way: a list of notes, each person seeing only their own.

Nothing below uses `CRUDView`, datasets or MCP. The last section says when those earn their place.

## 1. Make the app

```bash
mkdir apps/notes
uv run python manage.py startapp notes apps/notes
```

Your apps live under `apps/` and are named `apps.<name>`, so set that in `apps/notes/apps.py`. Its `ready()` is also where the app adds itself to the sidebar:

```python
from django.apps import AppConfig


class NotesConfig(AppConfig):
    name = "apps.notes"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(section="main", label="Notes", url_name="notes:list", order=30, auth_required=True)
```

Don't edit SmallStack's `sidebar.html` for this: the registry orders the link, hides it from people who can't open the page, and survives upgrades. See [Navigation](/smallstack/help/smallstack/navigation/).

## 2. The model

```python
# apps/notes/models.py
from django.conf import settings
from django.db import models


class Note(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return self.title
```

Point foreign keys at `settings.AUTH_USER_MODEL`: SmallStack has a custom user model. Register the model with the admin as usual (`admin.site.register(Note)` in `admin.py`) if you want it in `/admin/`.

## 3. The view and the URL

```python
# apps/notes/views.py
from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import Note


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["title", "body"]


@login_required
def note_list(request):
    form = NoteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        note.owner = request.user
        note.save()
        return redirect("notes:list")
    notes = Note.objects.filter(owner=request.user)
    return render(request, "notes/list.html", {"notes": notes, "form": form})
```

```python
# apps/notes/urls.py
from django.urls import path

from . import views

app_name = "notes"
urlpatterns = [
    path("", views.note_list, name="list"),
]
```

## 4. The template

Extend `smallstack/base.html` and fill its `title`, `breadcrumbs` and `content` blocks. Style with SmallStack's classes and CSS variables (`.card`, `.btn-primary`, `var(--body-quiet-color)`), never colour literals, and the page is right on every palette in light and dark.

```django
{# apps/notes/templates/notes/list.html #}
{% extends "smallstack/base.html" %}
{% load theme_tags %}

{% block title %}Notes{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "website:home" %}
{% breadcrumb "Notes" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<h1>Notes</h1>

<form method="post" class="card" style="padding: 1rem; margin-bottom: 1.5rem;">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit" class="btn-primary">Add note</button>
</form>

{% for note in notes %}
<article class="card" style="padding: 1rem; margin-bottom: 0.75rem;">
    <h2 style="margin: 0 0 0.25rem; font-size: 1.05rem;">{{ note.title }}</h2>
    <p style="margin: 0; color: var(--body-quiet-color);">{{ note.body|linebreaksbr }}</p>
</article>
{% empty %}
<p>No notes yet.</p>
{% endfor %}
{% endblock %}
```

One rule differs from a default Django project: **no inline JavaScript.** The Content-Security-Policy refuses `<script>…</script>` blocks and `onclick="…"` in templates. Put scripts in a static file and pass values on `data-` attributes; `docs/skills/templates.md` in the repository has the recipe.

## 5. Wire it in

Add `"apps.notes"` to `INSTALLED_APPS` in `config/settings/base.py`, include the URLs in `config/urls.py`, and migrate:

```python
path("notes/", include("apps.notes.urls")),
```

```bash
uv run python manage.py makemigrations notes
make migrate
make run        # http://localhost:8005/notes/
```

## 6. Test it

Tests are plain pytest with pytest-django. Put them in `apps/notes/tests/` (delete the `tests.py` that `startapp` made, and add an empty `tests/__init__.py`):

```python
# apps/notes/tests/test_views.py
import pytest
from django.urls import reverse

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


def test_list_needs_login(client):
    response = client.get(reverse("notes:list"))
    assert response.status_code == 302


def test_add_and_list_a_note(client, django_user_model):
    user = django_user_model.objects.create_user("ada", password="x")
    client.force_login(user)
    response = client.post(reverse("notes:list"), {"title": "First", "body": "Hello"})
    assert response.status_code == 302
    assert Note.objects.get().owner == user
    assert "First" in client.get(reverse("notes:list")).content.decode()


def test_you_only_see_your_own_notes(client, django_user_model):
    other = django_user_model.objects.create_user("bob", password="x")
    Note.objects.create(owner=other, title="Bob's secret")
    client.force_login(django_user_model.objects.create_user("ada", password="x"))
    assert "Bob's secret" not in client.get(reverse("notes:list")).content.decode()
```

```bash
uv run pytest apps/notes
make lint       # ruff, mypy and the docs index
```

That's a complete app. Class-based views, Django forms, the admin, signals and management commands all work the same way.

## When SmallStack's own layers earn their place

Reach for these when the plain version starts repeating itself, not before:

| You want | Use |
|---|---|
| A staff list / detail / create / edit / delete page per model, with search, filters, CSV and bulk actions | [`CRUDView`](/smallstack/help/smallstack/building-crud-pages/) |
| The same model over a REST API, or to AI clients over MCP | `enable_api = True` / `enable_mcp = True` on that `CRUDView` |
| Keyword search across models, including from the topbar | `enable_search = True` ([Search](/smallstack/help/smallstack/search/)) |
| Charts, KPIs and dashboards over your data | `@dataset`, then Dashboards |
| Work in the background or on a schedule | `django-tasks` (`@task`), then `@scheduled` |

Each is opt-in, and your plain views keep working beside them.
