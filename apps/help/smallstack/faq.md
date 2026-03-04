---
title: FAQ
description: Frequently asked questions
---

# Frequently Asked Questions

## How do I create an admin user?

For local development, use the custom management command:

```bash
uv run python manage.py create_dev_superuser
```

This creates a user with credentials from your `.env` file (`DEV_SUPERUSER_USERNAME` and `DEV_SUPERUSER_PASSWORD`).

For manual creation:

```bash
uv run python manage.py createsuperuser
```

## How do I change the primary color?

Edit `static/smallstack/css/theme.css` and update the `--primary` variable (or add overrides in `static/css/project.css`):

```css
:root {
    --primary: #your-color;
    --primary-hover: #darker-variant;
}
```

Don't forget to update the dark mode version too in `[data-theme="dark"]`.

## How do I add a new page to the sidebar?

Edit `templates/smallstack/includes/sidebar.html`:

```html
<li class="nav-item">
    <a href="{% url 'your_url_name' %}" class="nav-link {% nav_active 'your_url_name' %}">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <!-- Your icon SVG path -->
        </svg>
        <span>Your Page</span>
    </a>
</li>
```

## How do I reset my password?

Click "Forgot your password?" on the login page. If email is configured, you'll receive a reset link.

For local development without email, use the admin panel or:

```bash
uv run python manage.py changepassword username
```

## How do I upload a profile photo?

1. Log in to your account
2. Click your username in the top right
3. Select "Profile" from the dropdown
4. Click "Edit Profile"
5. Upload your photo in the Profile Photo section

Photos must be JPG, PNG, GIF, or WebP format, max 5MB.

## Why isn't dark mode saving?

Dark mode preference is stored in browser `localStorage`. Make sure:

1. You're not in private/incognito mode
2. JavaScript is enabled
3. localStorage isn't being cleared

To manually set the theme:

```javascript
localStorage.setItem('smallstack-theme', 'dark');
location.reload();
```

## How do I run tests?

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Run specific app tests
uv run pytest apps/profile/
```

## How do I deploy to production?

We recommend Docker for simple deployments. See the [Docker Deployment](/help/docker-deployment/) guide.

For production, remember to:

1. Set `DEBUG=False`
2. Use a strong `SECRET_KEY`
3. Configure `ALLOWED_HOSTS`
4. Set up a proper database (PostgreSQL recommended)
5. Configure email for password resets
6. Use HTTPS

## How do I add a new Django app?

1. Create the app directory in `apps/`:
   ```bash
   mkdir apps/myfeature
   ```

2. Add the standard Django app files

3. Register in `config/settings/base.py`:
   ```python
   INSTALLED_APPS = [
       ...
       "apps.myfeature",
   ]
   ```

4. Add URL routing in `config/urls.py`

5. Run migrations

See [Project Structure](/help/project-structure/) for details.

## How do I customize the User model?

The custom User model is in `apps/accounts/models.py`. It already extends `AbstractBaseUser` for maximum flexibility.

To add fields:

1. Add the field to the `User` class
2. Create a migration: `python manage.py makemigrations`
3. Run migration: `python manage.py migrate`

## Where are uploaded files stored?

By default, uploaded files go to the `media/` directory. This is configured in settings:

```python
MEDIA_URL = "/media/"
MEDIA_ROOT = config("MEDIA_ROOT", default=str(BASE_DIR / "media"))
```

In Docker, media files are stored in the `media_data` volume for persistence.

## How do I add a new help page?

See [Using the Help System](/help/help-system/) for complete instructions. Quick steps:

1. Create a `.md` file in `apps/help/content/`
2. Add the page to `_config.yaml`
3. Restart the server

## Can I use a different database?

Yes! The project uses SQLite by default for simplicity, but you can switch to PostgreSQL or MySQL.

For PostgreSQL:

1. Install the driver: `uv add psycopg2-binary`
2. Update settings:
   ```python
   DATABASES = {
       "default": {
           "ENGINE": "django.db.backends.postgresql",
           "NAME": "your_db",
           "USER": "your_user",
           "PASSWORD": "your_password",
           "HOST": "localhost",
           "PORT": "5432",
       }
   }
   ```
3. Run migrations

## How do I contribute?

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

Please follow the existing code style and include tests for new features.
