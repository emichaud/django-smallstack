# utils/

Local developer utilities (not shipped to the running container — these are for
your workstation).

## `dev_services.sh` — exercise the background backends locally

In production SmallStack runs two background processes next to the web server:

1. **`db_worker`** drains the `django-tasks-db` queue.
2. A **per-minute heartbeat** records uptime (`scripts/smallstack-cron` POSTs to
   `/heartbeat/ping/`).

Local dev has neither, so there's no quick way to confirm "is the task queue
actually draining, and is the heartbeat recording?" This script runs both in one
foreground process. Ctrl-C stops everything (the worker child is reaped).

```bash
# Typical: run the dev server in window 1, this in window 2
make run                       # window 1
./utils/dev_services.sh        # window 2   (or: make services)
```

Useful for a fast end-to-end check:

```bash
# Fire heartbeats every 5s and enqueue one example task to watch the worker drain it
./utils/dev_services.sh --interval 5 --smoke
```

You should see `[worker] … process_data_task` reach `SUCCESSFUL` and `[heartbeat]`
lines recording each check. The task result is also visible at
`/smallstack/explorer/` (System → Task results); heartbeats at `/status/dashboard/`.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--interval N` | `60` | Seconds between heartbeats. |
| `--port N` | `8005` | Dev server port (for `--http` mode). |
| `--queue NAME` | `*` | Queue the worker drains (`*` = all). |
| `--http` | off | Fire the heartbeat by POSTing `/heartbeat/ping/` (mirrors the prod cron path; needs `make run`). Default runs `manage.py heartbeat` directly, no server required. |
| `--smoke` | off | Enqueue one example task on startup to prove the queue end-to-end. |
| `-h`, `--help` | | Show usage. |

> In the default (non-`--http`) mode the worker and queue work without a running
> web server, but the *site* and endpoint monitors only go green if `make run` is
> also up — otherwise you'll see `Connection refused` FAILs for the HTTP checks,
> which is expected.
