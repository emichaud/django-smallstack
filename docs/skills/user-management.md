# Skill: User Management

SmallStack includes a staff-only user management interface with search, profiles, activity stats, and a timezone dashboard. This skill covers the User Manager tool and email/password reset configuration.

## Overview

The User Manager at `/manage/users/` provides a clean interface for managing user accounts. It's built on CRUDView with custom templates for the title bar pattern, stat card drilldowns, HTMX search, and tabbed edit forms.

## File Locations

```
apps/usermanager/
├── views.py               # UserCRUDView, stat detail endpoint
├── tables.py              # UserTable, TimezoneTable
├── forms.py               # UserAccountForm, UserProfileForm
├── timezone_views.py      # Timezone dashboard view
└── urls.py                # URL configuration

apps/accounts/
├── models.py              # Custom User model (AbstractBaseUser)
├── views.py               # SignupView
├── forms.py               # SignupForm
└── backends.py            # EmailOrUsernameBackend (optional)

apps/profile/
├── models.py              # UserProfile (auto-created via signals)
└── signals.py             # Auto-create profile on user creation

templates/
├── usermanager/
│   ├── user_list.html         # List page with title bar, search, stat cards
│   ├── _user_table.html       # Table partial for HTMX search
│   └── timezone_dashboard.html
└── accounts/
    └── user_form.html         # Tabbed edit form (Account, Profile, Activity)

config/settings/
├── base.py                # AUTH_USER_MODEL, SMALLSTACK_SIGNUP_ENABLED
├── development.py         # EMAIL_BACKEND = console
└── production.py          # EMAIL_BACKEND = SMTP
```

## User Manager Features

### User List (`/manage/users/`)

- **Title bar** — "User Manager" with subtitle and breadcrumbs
- **Stat cards** — Recent (30d), Total, Staff, Timezones — clickable with modal drilldowns
- **HTMX search** — filter by username, email, first name, last name
- **Sortable table** — django-tables2 with Username, Email, Name, Timezone, Staff, Active
- **Self-protection** — delete button hidden for your own row

### User Edit (`/manage/users/<pk>/edit/`)

Title bar shows username with summary cards (Status, Member Since, Role). Tabbed layout:

- **Account tab** — username, email, first/last name, staff, active
- **Profile tab** — photos (drag-and-drop), display name, bio, location, website, DOB, timezone
- **Activity tab** — request count, response time, daily sparkline, top pages, status codes

### Timezone Dashboard (`/manage/users/timezones/`)

- **Live clocks** — UTC, Server, Local (updating every second)
- **Filter buttons** — All, Working Hours, Off Hours, Staff Only, by region
- **Sortable table** — user, timezone, local time, UTC offset, status (Working/Off/Night), region

#### Work Hours Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `WORK_HOURS_START` | `8` | Hour (0-23) when work begins |
| `WORK_HOURS_END` | `18` | Hour (0-23) when work ends |
| `WORK_DAYS` | `(0, 1, 2, 3, 4)` | Weekday integers (0=Mon through 6=Sun) |

## CRUDView Architecture

```python
class UserCRUDView(CRUDView):
    model = User
    url_base = "manage/users"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    table_class = UserTable
    form_class = UserAccountForm
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
```

The `_make_view` method is overridden to inject search filtering, profile form handling, and self-delete protection.

## Email Configuration

### Development (Console)

Already configured — emails print to terminal:

```python
# config/settings/development.py
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

### Production (SMTP)

```bash
# .env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
```

### Email Login (Optional)

Allow login with email instead of username:

```python
# apps/accounts/backends.py
class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if "@" in username:
            user = User.objects.get(email__iexact=username)
        else:
            user = User.objects.get(username__iexact=username)
        ...
```

```python
# config/settings/base.py
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]
```

## Auth Feature Flags

| Setting | Default | Description |
|---------|---------|-------------|
| `SMALLSTACK_LOGIN_ENABLED` | `True` | Hide Login/Sign Up buttons from topbar |
| `SMALLSTACK_SIGNUP_ENABLED` | `True` | Hide Sign Up and return 404 on `/accounts/signup/` |

## Password Reset

Already wired up. Requires email settings (see above). Templates in `templates/registration/`.

## UserProfile Model

Auto-created via signals when a user is created:

```python
class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, ...)
    theme_preference = models.CharField(...)   # dark/light
    color_palette = models.CharField(...)      # django, high-contrast, etc.
    display_name = models.CharField(...)
    bio = models.TextField(...)
    profile_photo = models.ImageField(...)
    background_photo = models.ImageField(...)
    # location, website, date_of_birth, timezone
```

Access in templates: `{{ user.profile.bio }}`, `{{ user.profile.theme_preference }}`

## Access Control

All User Manager views require staff status via `StaffRequiredMixin`.

## Extending Downstream

Common extensions:
- Role-based access / permission groups
- Custom profile fields (department, phone)
- Invitation flow (invite-by-email)
- Bulk operations
- User activity detail linking

## API Endpoints

For programmatic user management, SmallStack provides REST endpoints that mirror the UI functionality:

- `GET /api/auth/users/` — list and search users (auth-level token required)
- `GET /api/auth/users/<id>/` — user detail
- `PATCH /api/auth/users/<id>/` — update user fields
- `POST /api/auth/users/<id>/password/` — set password
- `POST /api/auth/users/<id>/deactivate/` — deactivate and revoke tokens

See `api.md` for full details.

## Best Practices

1. **Use `settings.AUTH_USER_MODEL`** — never import User directly
2. **Use `get_user_model()`** for runtime access
3. **Extend with profiles** — keep User model lean
4. **Configure SMTP before launch** — password reset needs it
5. **Set ADMINS** in production for backup failure notifications
