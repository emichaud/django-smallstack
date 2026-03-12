---
title: "TL;DR — Clone to Deploy"
description: "The shortest path from zero to a running site"
---

# TL;DR — Clone to Deploy

The fewest steps to get a SmallStack site live. One page, your content, deployed.

---

**Step 1 — Clone and setup**

```bash
git clone https://github.com/emichaud/django-smallstack myapp
cd myapp
make setup
```

This installs dependencies, creates the database, and sets up a dev admin account (`admin` / `admin`).

---

**Step 2 — Start the dev server and verify**

```bash
make run
```

Open `http://localhost:8005`. You should see the default homepage. Log in with `admin` / `admin`.

---

**Step 3 — Edit your homepage**

Open `templates/website/home.html` and replace the content:

```html
{% extends "smallstack/base.html" %}
{% load static %}

{% block title %}My App{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header"><h2>Welcome</h2></div>
    <div class="card-body">
        <p>This is my app. There are many like it, but this one is mine.</p>
    </div>
</div>
{% endblock %}
```

Save. The dev server auto-reloads — refresh the browser.

---

**Step 4 — Update branding**

In `config/settings/base.py`, find the `BRAND_*` settings and change the name:

```python
BRAND_NAME = "My App"
```

---

**Step 5 — Run tests**

```bash
make test
```

All green? Good.

---

**Step 6 — Configure deployment**

Edit `config/deploy.yml`:

```yaml
service: myapp

servers:
  web:
    - YOUR_VPS_IP

volumes:
  - /root/myapp_data/media:/app/media
  - /root/myapp_data/db:/app/data

proxy:
  ssl: true
  hosts:
    - myapp.com
```

---

**Step 7 — Set your secrets**

Create `.kamal/secrets`:

```bash
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=myapp.com,www.myapp.com,YOUR_VPS_IP
CSRF_TRUSTED_ORIGINS=https://myapp.com,https://www.myapp.com
```

---

**Step 8 — Deploy**

```bash
kamal setup    # First time only — provisions the server
kamal deploy   # Every time after
```

Your site is live at `https://myapp.com` with SSL, dark mode, auth, analytics, backups, and background tasks — all included.

---

## What you get out of the box

No extra configuration needed. These just work:

- **Authentication** — login, signup, password reset
- **User profiles** — photo, bio, color palette preference
- **Dark/light mode** — 5 color palettes, user-selectable
- **Activity tracking** — request logging with staff dashboard
- **Database backups** — on-demand + scheduled, with email alerts
- **Background tasks** — no Redis or Celery required
- **Help system** — the docs you're reading right now
- **Admin panel** — Django's built-in admin, themed to match

## What's next

- [Make Commands](/help/smallstack/make-commands/) — all the shortcuts
- [Customization Guide](/help/smallstack/customization/) — make it yours
- [Kamal Deployment](/help/smallstack/kamal-deployment/) — detailed deploy guide
- [About](/help/smallstack/about/) — everything that's included
