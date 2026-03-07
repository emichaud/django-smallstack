# Philosophy

<div class="two-col" markdown="1">
<div class="col" markdown="1">

- **Use what Django gives you** — before adding a package, check if Django already has it
- **Keep it simple** — add complexity only when needed
- **Stay close to Django** — conventions over invention
- **Production-ready defaults** — secure settings, proper static files, Docker support

</div>
<div class="col" markdown="1">

```toml
dependencies = [
    "django>=6.0",
    "python-decouple>=3.8",
    "pillow>=10.0",
    "gunicorn>=21.0",
    "whitenoise>=6.6",
    "django-extensions>=3.2",
    "django-debug-toolbar>=4.2",
    "markdown>=3.5",
    "pyyaml>=6.0",
    "django-tasks-db>=0.2",
    "django-htmx>=1.19",
]
```

</div>
</div>
