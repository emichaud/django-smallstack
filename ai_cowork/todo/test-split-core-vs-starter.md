# TODO: Split Tests into Core Contract vs Starter Content

Date: 2026-03-19
Source: vedders-smallstack-migration-issues-lessons-learned.md (Issue #4, Action Item #3)

## Problem

When a downstream project customizes the homepage, replaces website URLs, or swaps the theme, ~20 upstream tests fail — not because anything is broken, but because those tests assert starter content (specific text, breadcrumb labels, feature cards) that the downstream intentionally removed.

This makes it hard to distinguish real regressions from expected downstream divergence.

## Objective

Tag or separate tests so downstream projects can run `pytest -m "not starter_content"` and get a clean pass after legitimate customization, while still running all core contract tests (auth, permissions, models, API, middleware).

## Current State: 296 Tests

**~210 core contract** — auth, permissions, models, middleware, API, HTMX, template tags, registry logic. These should pass in any downstream project.

**~20 starter content** — assert specific text, HTML markers, or breadcrumb labels that only exist in the upstream starter. These will break in any customized downstream.

## Tests Identified as Starter Content

### `apps/website/tests.py`
- `TestWebsiteViews::test_home_page` — asserts "SmallStack" text
- `TestWebsiteViews::test_home_page_feature_cards` — asserts "Read docs" text
- `TestWebsiteViews::test_home_page_customize_banner` — asserts "Make it yours"
- `TestWebsiteViews::test_about_page` — about page loads
- `TestWebsiteViews::test_getting_started_page` — getting started page loads
- `TestWebsiteViews::test_starter_page` — starter page loads
- `TestWebsiteViews::test_starter_basic_page` — starter basic page loads
- `TestWebsiteViews::test_starter_forms_page` — starter forms page loads

### `apps/smallstack/tests.py`
- `TestBackupViewPermissions::test_backup_list_has_breadcrumbs` — breadcrumb text
- `TestBackupViewPermissions::test_backup_detail_has_breadcrumbs` — breadcrumb text
- `TestLegalPages::test_privacy_page_loads` — "Privacy Policy" text
- `TestLegalPages::test_terms_page_loads` — "Terms of Service" text
- `TestLegalPages::test_footer_contains_legal_links` — footer link text
- `TestLegalPages::test_cookie_banner_present` — cookie banner HTML marker
- `TestLegalPages::test_signup_terms_notice` — signup page text
- `TestTopbarNav::test_topbar_nav_renders` — topbar nav HTML marker
- `TestTopbarNav::test_enabled_with_items` — "Home" text in nav

### `apps/activity/tests.py`
- `TestRequestListView::test_title_bar_has_breadcrumbs` — breadcrumb text
- `TestUserActivityView::test_title_bar_has_breadcrumbs` — breadcrumb text

### `apps/usermanager/tests.py`
- `TestUserListView::test_breadcrumbs_in_title_bar` — breadcrumb text

## Gray Areas

Some tests check both content and contract in the same assertion:
- `TestHomePageAuthenticated::test_quick_links_for_staff` — checks permission logic BUT also asserts specific link text. The permission check is core; the text is starter.
- `TestLegalPages::test_privacy_page_is_public` — checks public access (core) but relies on legal page existing (starter). The route exists in `config/urls.py` so this is actually core.

## Implementation Options

### Option A: Pytest Markers (Recommended)

Add a custom marker and tag the ~20 starter tests:

```python
# conftest.py
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "starter_content: tests that assert upstream starter content")

# In test files:
@pytest.mark.starter_content
def test_home_page_feature_cards(self):
    ...
```

Downstream usage:
```bash
pytest -m "not starter_content"   # skip starter tests
pytest                             # run everything (upstream default)
```

**Pros:** Minimal churn, no file moves, easy to understand.
**Cons:** Markers are invisible unless you grep for them. Easy to forget on new tests.

### Option B: Separate Test Files

Move starter content tests to `test_starter_content.py` in each app:

```
apps/website/tests/
    test_core.py              # route contract tests
    test_starter_content.py   # homepage text, feature cards
apps/smallstack/tests/
    test_core.py              # models, middleware, permissions
    test_starter_content.py   # breadcrumbs, legal text, topbar nav text
```

Downstream usage:
```bash
pytest --ignore-glob="**/test_starter_content.py"
```

**Pros:** Very obvious separation. Hard to miss.
**Cons:** Significant file churn. Some test classes would need splitting (half core, half starter). Shared fixtures may need restructuring.

### Option C: Conftest Fixture + Skip

A fixture that auto-skips starter tests when an env var is set:

```python
# conftest.py
STARTER_CONTENT = pytest.mark.skipif(
    os.environ.get("SMALLSTACK_DOWNSTREAM") == "1",
    reason="Starter content test — skipped in downstream projects"
)
```

**Pros:** Zero config for upstream. One env var for downstream.
**Cons:** Less explicit than markers. Env var is easy to forget.

## Recommendation

**Option A (markers)** with a documentation note in CLAUDE.md and a brief section in the downstream migration guide. It's the lowest-risk change, doesn't reorganize files, and pytest markers are a well-understood pattern.

## Effort Estimate

- Tag ~20 tests with `@pytest.mark.starter_content`: ~30 min
- Add marker registration to `conftest.py`: 2 min
- Add `pytest.ini` / `pyproject.toml` marker config: 2 min
- Document in migration guide: 10 min
- Split gray-area tests that mix content + contract assertions: ~30 min (the harder part)

## Risks

1. **Miscategorization** — tagging a core contract test as starter means downstreams miss a real regression. Conservative approach: when in doubt, keep it as core.
2. **Breadcrumb tests** — breadcrumb text is starter content, but breadcrumb *rendering* is core. Some tests assert both. These need splitting into two tests: one checking the breadcrumb mechanism works, another checking the specific text.
3. **New tests** — contributors may forget to add the marker. Add a note to CLAUDE.md and the test conventions section.
