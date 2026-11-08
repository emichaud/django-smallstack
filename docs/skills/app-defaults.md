# Shipping dashboard defaults with your app

An app can ship its own **metrics, saved cards, dashboards, reports, goal lists and
playlists**, so they're there as soon as the app is installed. People then use them,
edit them in place, or duplicate them. The app keeps improving its defaults, but never
overwrites what someone has changed.

The pieces an app ships as code are covered elsewhere: its data in `datasets.md`
(`@dataset`), its calendars in `calendar.md`, and its card designs in `card-types.md`.
This file covers the rows that sit on top of them.

## The short version

```python
# apps/support/dashboard_defaults.py   (found at startup, like datasets.py)
from apps.dashboards.defaults import Defaults, register_defaults

register_defaults(Defaults(
    app="support",                                       # the app's label
    metrics=[
        {"key": "support_open", "name": "Open tickets", "dataset": "support_tickets",
         "filter_tree": {"field": "status", "op": "=", "value": "open"},
         "description": "Tickets nobody has closed yet."},
        {"key": "support_new", "name": "New tickets", "dataset": "support_tickets",
         "period_field": "created_at"},
    ],
    dashboards=[
        {"slug": "support-overview", "name": "Support", "default_period": "last_7",
         "layout": [
             {"id": "open", "type": "metric", "metric": "support_open", "x": 0, "y": 0, "w": 3, "h": 2},
             {"id": "new", "type": "metric", "metric": "support_new", "x": 3, "y": 0, "w": 3, "h": 2},
         ]},
    ],
    goal_lists=[
        {"slug": "support-weekly", "name": "Support weekly",
         "sections": [{"title": "Queue", "goals": [
             {"id": "open", "metric": "support_open", "target": {"op": "<", "value": 20}}]}]},
    ],
))
```

Then run `migrate`, or `manage.py dashboard_defaults`. The rows appear in the Dashboards
and Goals pages, shared (everyone signed in can open them; staff edit them), each
marked **From Support**.

## What you can declare

Each list holds plain dicts in the same shape the REST API and agents write. Each dict
names its row by `key` (metrics, saved cards) or `slug` (everything else), and may set
these fields:

| `Defaults` list | Model | Fields |
|---|---|---|
| `metrics` | `Metric` | `name`, `description`, `source`, `dataset`, `numerator`, `denominator`, `filter_tree`, `agg`, `measure`, `period_field`, `format`, `unit`, `thresholds`, `tags` |
| `components` | `Component` (saved card) | `name`, `description`, `type`, `metric`, `dataset`, `filter_tree`, `agg`, `measure`, `period_field`, `options`, `tags` |
| `dashboards` | `Dashboard` | `name`, `description`, `layout`, `default_period`, `refresh_seconds`, `tags` |
| `reports` | `Report` | `name`, `description`, `items`, `periods`, `tags` |
| `goal_lists` | `GoalList` | `name`, `description`, `default_period`, `sections`, `tags` |
| `playlists` | `Playlist` | `name`, `description`, `items`, `seconds`, `loop`, `auto_start`, `tags` |

- **Fields you leave out** take the model's default, so dropping a field from a later
  version clears it.
- **Order within a bundle doesn't matter.** Rows are applied metrics first (rates
  after plain metrics), then cards, dashboards, reports, goal lists and playlists.
  Bundles apply in `INSTALLED_APPS` order, so a row may name another app's default
  only when that app is listed first (otherwise the first migrate reports an `error`
  and the next one fixes it).
- **Give goals an `id`.** A goal's history is kept by its id, so a stable one keeps
  the history attached when the list is updated.
- **Validation is the usual one.** Every row goes through the model's `full_clean()`,
  exactly as from the page, REST or MCP. A row that doesn't apply (a dataset that
  isn't there, a filter on a column it doesn't have) is reported and skipped, and
  the rest still apply.

**Names are prefixed.** Keys must start with `<app>_` and slugs with `<app>-` (an
underscore in the label becomes a hyphen), so two apps can't collide. Set
`prefix="other"` to use another, or `prefix=""` to turn the check off. Registering
checks this, and a bad declaration raises `ImproperlyConfigured` at startup, naming
each problem.

## How the sync treats a row

`defaults.sync_defaults()` runs after every `migrate`, and on demand from
`manage.py dashboard_defaults`. Each row remembers who shipped it (`provided_by`,
`provided_key`) and two fingerprints: the declaration last applied (`provided_spec`)
and the row as it was then (`provided_hash`).

| The row… | The sync |
|---|---|
| doesn't exist | creates it, shared |
| exists, nobody changed it, and the app's declaration changed | updates it |
| exists, someone changed it | keeps their version. A newer default shows **Reset to default** on the row's page |
| was deleted by someone | leaves it deleted (`RemovedDefault`); `--restore` brings it back |
| has its name taken by a row made here | reports a conflict; `--adopt` takes that row over and makes it match |
| belongs to an app that's no longer installed | archives it (`provided_parked`); it comes back when the app does |

"Changed" means any of the fields above. Archiving a row, sharing it or moving it in
a playlist doesn't count. A dashboard's placed saved cards count by placement only, so
editing the card isn't an edit to the dashboard.

## What people see

- **The badge.** A page's header shows **From Support** on a default, adding
  **· customised** once someone has changed it.
- **Reset to default.** It appears when the row differs from what the app ships now,
  either because someone changed it or because the app shipped a newer version over
  their change. It confirms in the modal, then puts the row back as the app ships it
  now. Who can see it, whether it's archived, and where it's used don't change.
- **Duplicate** is the way to keep your own version and still take the app's updates.
- **REST and MCP** carry `provided_by` (read-only) on every row.

## Commands

```bash
uv run python manage.py dashboard_defaults                       # apply every app's defaults
uv run python manage.py dashboard_defaults --dry-run             # what it would do
uv run python manage.py dashboard_defaults --app support         # one app
uv run python manage.py dashboard_defaults --app support --restore   # and bring back deleted ones
uv run python manage.py dashboard_defaults --app support --adopt     # take over same-named rows made here
```

## Opt-in bundles

`Defaults(auto=False)` stays out of the after-migrate sync. It's applied only when
named: `dashboard_defaults --app <label>`, or `sync_defaults([label])` from your own
command. The framework's demo is one (`apps/dashboards/dashboard_defaults.py`, applied
by `manage.py seed_dashboards`), and it's the working example to copy.

`SMALLSTACK_DASHBOARD_DEFAULTS_SYNC = False` turns the after-migrate sync off
entirely. The command still works.

## Testing your defaults

The test settings turn the after-migrate sync off
(`SMALLSTACK_DASHBOARD_DEFAULTS_SYNC = False` in `config/settings/test.py`), so
every test starts with no app-shipped rows; the framework's own tests count
rows and would fail on yours. A test that wants your defaults syncs them:

```python
from apps.dashboards.defaults import sync_defaults

def test_support_defaults_apply(db):
    report = sync_defaults(["support"])
    assert not [line for line in report.lines if line[3] in ("error", "conflict")]
```

`apps/dashboards/tests/test_app_defaults.py` covers the sync itself: creation,
updates, kept edits, reset, deletes, conflicts, parking, and the page.

## Don't

- **Seed with a data migration.** Historical models can't see the dataset registry,
  so the rows can't be validated. Declare them instead.
- **Write rows directly in `ready()`, or in a command that saves them every run.**
  That overwrites people's edits, which is the problem this solves.
- **Rename a default's key or slug.** The new name is a new default and the old row
  stays behind as a row made here. Keep names stable, as you would a URL.
