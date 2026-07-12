#!/usr/bin/env bash
#
# dev_services.sh — simulate SmallStack's production background processes locally.
#
# In production two things run alongside the web server:
#   1. db_worker  — drains the django-tasks-db queue (worker inline in the web
#                   container, or a separate worker container)
#   2. a per-minute heartbeat — scripts/smallstack-cron POSTs to /heartbeat/ping/
#
# Local dev has neither, so there's no quick way to confirm the task queue is
# draining or the heartbeat is recording. Run this in a second terminal to get
# both. Ctrl-C tears everything down (the worker child is reaped).
#
# Usage:
#   ./utils/dev_services.sh [options]
#
# Options:
#   --interval N   seconds between heartbeats (default: 60)
#   --port N       dev server port for --http mode (default: 8005)
#   --queue NAME   queue the worker drains (default: "*" = all)
#   --http         fire the heartbeat by POSTing /heartbeat/ping/ (mirrors the
#                  prod cron path; requires `make run` in another terminal).
#                  Default runs `manage.py heartbeat` directly (no server needed).
#   --smoke        enqueue one example task on startup so you can watch the
#                  worker drain it (proves the tasks backend end-to-end).
#   -h, --help     show this help.
#
# Tip: run `make run` in window 1, this in window 2.

set -u

# Resolve project root (the directory containing this utils/ folder).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# Defaults
INTERVAL=60
PORT=8005
QUEUE="*"
USE_HTTP=0
SMOKE=0

# Colors (disabled when not a TTY)
if [ -t 1 ]; then
  C_WORKER=$'\033[36m'; C_HEART=$'\033[32m'; C_INFO=$'\033[35m'; C_WARN=$'\033[33m'; C_RST=$'\033[0m'
else
  C_WORKER=''; C_HEART=''; C_INFO=''; C_WARN=''; C_RST=''
fi

usage() { sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --interval) INTERVAL="$2"; shift 2 ;;
    --port)     PORT="$2"; shift 2 ;;
    --queue)    QUEUE="$2"; shift 2 ;;
    --http)     USE_HTTP=1; shift ;;
    --smoke)    SMOKE=1; shift ;;
    -h|--help)  usage ;;
    *) echo "Unknown option: $1 (use --help)" >&2; exit 2 ;;
  esac
done

info()  { echo "${C_INFO}[dev-services]${C_RST} $*"; }
warn()  { echo "${C_WARN}[dev-services]${C_RST} $*"; }

# Recursively kill a pid and its descendants (reaps the uv → python worker).
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null
}

WORKER_PID=""
cleanup() {
  echo
  if [ -n "$WORKER_PID" ]; then
    info "Stopping worker (pid $WORKER_PID)…"
    kill_tree "$WORKER_PID"
  fi
  info "Stopped."
}
trap cleanup EXIT
trap 'exit 0' INT TERM

info "Project: $PROJECT_ROOT"
info "Worker queue: $QUEUE   Heartbeat: every ${INTERVAL}s ($([ "$USE_HTTP" -eq 1 ] && echo "HTTP :$PORT" || echo "manage.py"))"

# Optional: enqueue one example task so the worker has something to drain.
if [ "$SMOKE" -eq 1 ]; then
  info "Enqueuing smoke task (process_data_task)…"
  uv run python manage.py shell -c \
    "from apps.tasks.tasks import process_data_task; r = process_data_task.enqueue([1, 2, 3], operation='sum'); print('  enqueued task', r.id)" \
    2>/dev/null || warn "Could not enqueue smoke task (is the app importable?)"
fi

# Start the worker, prefixing its output. Process substitution keeps WORKER_PID
# pointed at the uv/python process so kill_tree can reap it on exit.
info "Starting db_worker…"
PYTHONUNBUFFERED=1 uv run python manage.py db_worker --queue-name "$QUEUE" \
  > >(sed "s/^/${C_WORKER}[worker]${C_RST} /") 2>&1 &
WORKER_PID=$!

# Heartbeat loop.
heartbeat_once() {
  if [ "$USE_HTTP" -eq 1 ]; then
    if curl -sf -X POST "http://localhost:${PORT}/heartbeat/ping/" >/dev/null; then
      echo "${C_HEART}[heartbeat]${C_RST} ping OK (:$PORT)"
    else
      echo "${C_HEART}[heartbeat]${C_RST} ${C_WARN}ping failed${C_RST} — is \`make run\` up on :$PORT?"
    fi
  else
    uv run python manage.py heartbeat 2>&1 | sed "s/^/${C_HEART}[heartbeat]${C_RST} /"
  fi
}

info "Running. Press Ctrl-C to stop."
while true; do
  heartbeat_once
  sleep "$INTERVAL"
done
