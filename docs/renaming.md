# Renaming Your Project

This guide explains how to rename Django SmallStack to your own project name.

## Quick Start

Run the automated rename script:

```bash
python scripts/rename_project.py my_project_name
```

This will update most references automatically. However, some manual steps are required.

## What the Script Does

The script automatically updates:
- `pyproject.toml` - project name
- `Makefile` - help text
- Template titles and branding
- CSS/JS comments
- Docker configuration
- Documentation files

## Manual Steps After Running the Script

### 1. Update Environment Variables

Edit `.env` and generate a new `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 2. Rename the Config Folder (Optional)

If you want to rename the `config` folder to match your project:

```bash
# Rename the folder
mv config my_project

# Update these files with the new path:
# - manage.py: DJANGO_SETTINGS_MODULE = "my_project.settings.development"
# - config/wsgi.py: os.environ.setdefault("DJANGO_SETTINGS_MODULE", "my_project.settings.development")
# - config/asgi.py: os.environ.setdefault("DJANGO_SETTINGS_MODULE", "my_project.settings.development")
# - pyproject.toml: DJANGO_SETTINGS_MODULE = "my_project.settings.development"
# - Dockerfile: Update DJANGO_SETTINGS_MODULE
```

### 3. Rename the Apps Folder (Optional)

If you want to rename or restructure the `apps` folder:

1. Rename the folder
2. Update `apps.py` in each app with the new path
3. Update `INSTALLED_APPS` in `config/settings/base.py`
4. Update URL imports in `config/urls.py`
5. Update any template paths

### 4. Initialize a New Git Repository

```bash
rm -rf .git
git init
git add .
git commit -m "Initial commit: Project renamed from SmallStack"
```

### 5. Regenerate Migrations (If Needed)

If you renamed models or changed app names:

```bash
# Remove old migrations
find . -path "*/migrations/*.py" -not -name "__init__.py" -delete
find . -path "*/migrations/*.pyc" -delete

# Remove database
rm db.sqlite3

# Create new migrations
python manage.py makemigrations
python manage.py migrate
```

## Risks and Considerations

### Database Migrations
- If you rename apps after running migrations, Django may not recognize the existing tables
- Consider exporting data before renaming, then re-importing after

### Third-Party Integrations
- Update any external services that reference your project name
- OAuth configurations may need updating

### Import Paths
- Python imports are case-sensitive
- Use snake_case for folder and file names
- Avoid spaces or special characters

## File Reference

Files that typically need updating when renaming:

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package name and metadata |
| `manage.py` | Default settings module |
| `config/settings/base.py` | App references |
| `config/urls.py` | App URL includes |
| `config/wsgi.py` | WSGI application path |
| `config/asgi.py` | ASGI application path |
| `Dockerfile` | Environment variables |
| `docker-compose.yml` | Service configuration |
| `Makefile` | Help text |
| `templates/*.html` | Site name/branding |

## Troubleshooting

### Import Errors After Renaming

```
ModuleNotFoundError: No module named 'old_name'
```

Check that all imports have been updated. Search for the old name:

```bash
grep -r "old_name" --include="*.py" .
```

### Migration Errors

```
django.db.utils.ProgrammingError: relation "app_model" does not exist
```

This usually means migrations reference old app names. Regenerate migrations as described above.

### Template Not Found Errors

```
TemplateDoesNotExist: old_name/template.html
```

Update template paths in views or ensure template folder names match app names.
