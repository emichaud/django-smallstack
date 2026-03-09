# Skill: Development Workflow

How to develop features, write tests, and maintain code quality in SmallStack.

## Branch Strategy

- `main` — stable, release-ready code. All commits should pass tests and lint.
- `feature/<name>` — for new features and improvements
- `fix/<name>` — for bug fixes

```bash
git checkout -b feature/my-feature
# ... develop, test, commit ...
git checkout main
git merge feature/my-feature
git branch -d feature/my-feature
```

## Fix-Upstream Pattern

SmallStack is an upstream package. Downstream projects (smallstack_web, opshugger, etc.) clone and extend it. When developing:

1. **Generic improvements go in `smallstack/`** — keep them reusable
2. **Project-specific code stays downstream** — don't pollute the base
3. Fix in base first, then pull to derived projects

### Minimizing Downstream Merge Conflicts

- Use thin wrapper templates (`templates/website/`) that extend SmallStack bases
- Add new palettes at the *end* of `palettes.css` and `palettes.yaml`
- Put project CSS in `static/css/`, not `static/smallstack/css/`
- Put project templates in `templates/website/`, not `templates/smallstack/`
- Use `{% block extra_css %}` and `{% block extra_js %}` for additions

## Testing

### Running Tests

```bash
make test                           # All tests with coverage summary
uv run pytest -k "test_name"       # Single test by name
uv run pytest apps/activity/       # Single app
uv run pytest -x                   # Stop on first failure
```

### Coverage

Coverage runs automatically with every `pytest` invocation (configured in `pyproject.toml`).

```bash
make coverage                       # Tests + HTML coverage report
open htmlcov/index.html             # Browse per-file line coverage
```

Configuration in `pyproject.toml`:
- Source: `apps/` directory
- Omits: migrations, test files
- Reports: terminal (skip-covered) + HTML

### Writing Tests

Tests live alongside their apps in `apps/<appname>/tests.py` or `apps/<appname>/tests/`.

```python
import pytest
from django.test import override_settings

@pytest.fixture
def staff_user(db):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(username="staff", password="pass", is_staff=True)

@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client

class TestMyView:
    def test_requires_login(self, client):
        resp = client.get("/my-page/")
        assert resp.status_code == 302

    def test_staff_access(self, staff_client):
        resp = staff_client.get("/my-page/")
        assert resp.status_code == 200
```

Conventions:
- Use `pytest` fixtures, not `unittest.TestCase`
- Use `client.force_login()` for authenticated tests
- Use `@override_settings()` for settings-dependent tests
- Use `tmp_path` fixture for file system tests

## Code Quality

```bash
make lint                           # Check with ruff
make lint-fix                       # Auto-fix lint issues
uv run ruff format .                # Format code
```

Ruff config in `pyproject.toml`: line length 120, Python 3.12, rules E/F/I/W.

## Documentation

SmallStack has three documentation tiers:

| Location | Audience | When to Update |
|----------|----------|----------------|
| `README.md` | Everyone (GitHub visitors) | Feature additions, version bumps |
| `apps/help/smallstack/` | Users (in-app `/help/`) | Feature guides, configuration docs |
| `docs/skills/` | AI agents | Architecture, patterns, conventions |

### Adding Help Pages

1. Create `apps/help/smallstack/<slug>.md` with YAML frontmatter
2. Add entry to `apps/help/smallstack/_config.yaml`
3. See `docs/skills/help-documentation.md` for details

### Screenshots for Documentation

```bash
# Generate auth for staff-only pages
uv run python manage.py screenshot_auth > /tmp/shot-auth.json

# Public pages
shot-scraper http://localhost:8005/ -o apps/help/smallstack/images/page.png --width 1280 --height 900

# Authenticated pages (hide debug toolbar)
shot-scraper http://localhost:8005/backups/ --auth /tmp/shot-auth.json \
  -o apps/help/smallstack/images/backups.png --width 1280 --height 900 \
  --javascript "document.getElementById('djDebug')?.remove()"
```

Store all screenshots in `apps/help/smallstack/images/` — co-located with the markdown docs that reference them.

## Commit Messages

SmallStack is a public repo. Write clear, professional commit messages:

```
<type>: <concise description>

<optional body with context>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:
- `feat: Add screenshot_auth command for headless browser testing`
- `docs: Update Docker commands to Compose V2 syntax`
- `fix: Exclude pruned backups from success count in dashboard`
- `test: Add coverage for backup detail view and stat filtering`
