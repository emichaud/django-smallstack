---
title: Feeds and the events API
order: 3
---

# Feeds and the events API

Everything the calendar page shows is available to scripts, calendar
applications and AI agents in the same shape. One event looks like this
everywhere:

```json
{
  "calendar": "smallstack_maintenance_windows",
  "id": 42,
  "title": "DB upgrade",
  "subtitle": "site",
  "start": "2026-04-03T08:00:00-04:00",
  "end": "2026-04-04T11:00:00-04:00",
  "all_day": false,
  "status": null,
  "url": "/smallstack/maintenance/42/"
}
```

`all_day` is true when the start column is a plain date. `status` is one of
`success`, `warning`, `danger` or `null`. `url` is the record's own page, when
the dataset knows one.

## Subscribe from a calendar app

The **Subscribe (.ics)** link under the picker is an iCalendar feed of the
calendars you have selected, covering last month through three months ahead.
Paste its URL into Apple Calendar, Google Calendar or Outlook as a
subscription and the events appear beside your own. Ranged events keep their
span; all-day events stay all-day; each event carries its calendar as a
category and a link back to the record.

```
GET /smallstack/calendar/api/events.ics?ds=<key>&ds=<key>
GET /smallstack/calendar/api/events.ics?view=<saved view id>
```

The feed is authenticated like the rest of the API — a session, or a Bearer
token. Calendar applications cannot send a header, so mint a token and let the
app ask for it as a password, or subscribe from a signed-in browser.

## The JSON routes

```
GET /smallstack/calendar/api/                     the calendars you may see
GET /smallstack/calendar/api/events/              merged events  ?ds=&ds=&start=&end=
GET /smallstack/calendar/api/<key>/events/        one calendar   ?start=&end=
```

`start` and `end` are ISO dates and `end` is exclusive; omit both for the
current month. `?view=<id>` substitutes one of your saved views for the `ds`
list. A key you may not see is reported as unknown, never as forbidden. The
widest window one request may ask for is `SMALLSTACK_CALENDAR_MAX_WINDOW_DAYS`
(366 by default).

The merged route returns `{start, end, calendars, counts, capped, count,
results}` — `counts` is per calendar and `capped` names any calendar whose
window hit the per-calendar row cap.

## Saved views over REST

Saved views are an ordinary SmallStack CRUD resource at
`/smallstack/api/calendar/views/`: list, create, read, update, delete, scoped
to the signed-in user. `datasets` is a JSON list of calendar keys; a key you
may not see is rejected as "not a valid choice".

## MCP

Two tools let an agent read the calendar:

- `list_calendars` — the calendars the token's user may see.
- `calendar_events` — `{calendars: [...], start, end, limit}` → the merged
  events above.

The saved-view resource also publishes the generated `list_calendar_views`,
`create_calendar_view`, `update_calendar_view` and `delete_calendar_view`
tools. All follow the calling user's access.

A saved view is plain data — a name and a list of calendar keys — so an agent
can build one from a sentence like "save a view of token expiry and approval
deadlines as my default":

```json
list_calendars → pick the keys
create_calendar_view {"name": "Deadlines",
                      "datasets": ["smallstack_api_tokens", "smallstack_approval_requests"],
                      "is_default": true}
```

`datasets` accepts a JSON array, a comma-separated string, or a single key; a
key the user may not see is rejected as "not a valid choice".
