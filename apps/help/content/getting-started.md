---
title: Getting Started
description: Quick start guide for Django SmallStack
---

# Getting Started with {{ project_name }}

Welcome to **{{ project_name }}** v{{ version }}! This is a Django {{ django_version }}+ starter project that provides a solid foundation for building admin-style web applications.

## What's Included

- **Custom User Model** - Flexible user authentication out of the box
- **User Profiles** - Profile management with photo uploads
- **Admin Theme** - Clean, modern UI with dark/light mode
- **Help System** - Built-in documentation with markdown support
- **Background Tasks** - Django 6's task framework pre-configured
- **Starter Template** - [Copy-paste template](/starter/) for creating new pages
- **Responsive Design** - Works on desktop and mobile
- **Docker Ready** - Deploy anywhere with Docker

## Quick Start

### Prerequisites

- Python {{ python_version }}+
- [UV](https://github.com/astral-sh/uv) package manager (recommended)
- Docker Desktop (for containerized deployment)

### Local Development

1. **Clone and enter the project:**
   ```bash
   cd django-smallstack
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Run migrations:**
   ```bash
   uv run python manage.py migrate
   ```

5. **Create a superuser:**
   ```bash
   uv run python manage.py create_dev_superuser
   ```

6. **Start the development server:**
   ```bash
   uv run python manage.py runserver
   ```

7. **Open your browser:**
   - Homepage: [http://localhost:8000](http://localhost:8000)
   - Admin: [http://localhost:8000/admin](http://localhost:8000/admin)

## Project Structure Overview

```
django-smallstack/
├── apps/                  # Django applications
│   ├── accounts/          # User model & authentication
│   ├── admin_theme/       # Theme helpers (pure presentation)
│   ├── profile/           # User profiles
│   ├── help/              # This help system
│   └── tasks/             # Background tasks
├── config/                # Project settings
├── templates/             # HTML templates
├── static/                # CSS, JS, images
└── docs/                  # Additional documentation
```

## Creating New Pages

The easiest way to add a new page is to use the **Starter Page** as a template. Visit [/starter/](/starter/) to see all available components in action.

### Step-by-Step Guide

1. **Copy the starter template:**
   ```bash
   cp templates/starter.html templates/my_page.html
   ```

2. **Create a view** in `config/views.py`:
   ```python
   def my_page_view(request):
       context = {'items': Item.objects.all()}
       return render(request, 'my_page.html', context)
   ```

3. **Add a URL** in `config/urls.py`:
   ```python
   from .views import my_page_view

   urlpatterns = [
       path('my-page/', my_page_view, name='my_page'),
       # ... existing urls
   ]
   ```

4. **Add to sidebar** (optional) in `templates/admin_theme/includes/sidebar.html`:
   ```html
   <li class="nav-item">
       <a href="{% url 'my_page' %}" class="nav-link {% nav_active 'my_page' %}">
           <svg><!-- icon --></svg>
           <span>My Page</span>
       </a>
   </li>
   ```

### Available Components

The starter page demonstrates:

- **Page headers** with action buttons
- **Cards** for content containers
- **Forms** with validation styling
- **Buttons** (primary, secondary, with icons)
- **Quick links** icon navigation
- **Messages** for user feedback
- **Grid layouts** for multi-column pages

All components support both light and dark themes automatically.

## Next Steps

- [View the Starter Page](/starter/) - See all components in action
- [Customize the theme](/help/theming/) - Colors, dark mode, components
- [Deploy with Docker](/help/docker-deployment/) - Run in containers
- [Explore the structure](/help/project-structure/) - Understand the codebase

## Getting Help

If you run into issues:

1. Check the [FAQ](/help/faq/) for common questions
2. Review the [project structure](/help/project-structure/)
3. Open an issue on GitHub
