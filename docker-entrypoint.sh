#!/bin/bash
set -e

# Auto-generate SECRET_KEY if not provided via environment
# The key is persisted to the data volume so it survives container rebuilds
if [ -z "$SECRET_KEY" ]; then
    KEY_FILE="/app/data/.secret_key"
    if [ ! -f "$KEY_FILE" ]; then
        echo "Generating new SECRET_KEY..."
        python -c "import secrets; print(secrets.token_urlsafe(50))" > "$KEY_FILE"
        chmod 600 "$KEY_FILE"
    fi
    export SECRET_KEY=$(cat "$KEY_FILE")
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Refresh Postgres planner stats for the search tables (cheap, fast, safe on
# every deploy). This keeps FTS queries on the GIN index instead of seq-scanning
# after a bulk vector write. No-op on SQLite.
#
# NOTE: the initial search backfill (`manage.py rebuild_search_index --all`) is
# deliberately NOT run here — it's a one-off, not a per-deploy step. Run it once
# after enabling search on existing data (or in a data migration). Putting it on
# the hot deploy path thrashes the DB and gets killed by the next redeploy.
python manage.py analyze_search_index || echo "analyze_search_index skipped/failed (non-fatal)"

# Create superuser if environment variables are set and user doesn't exist
python manage.py ensure_superuser

# Start scheduled tasks (heartbeat, backups, etc.) via supercronic
# supercronic runs as non-root and inherits the current environment
echo "Starting scheduled tasks..."
supercronic -passthrough-logs /app/scripts/smallstack-cron &

# Run db_worker inline by default (single-container deployment)
# Set WORKER_INLINE=false to disable when using a separate worker container.
#
# --worker-id is the operator's LABEL, not an identity: db_worker mints a
# per-process incarnation (`<label>#<token>`) and hands that to the queue, so
# reusing one label across restarts is safe and the heartbeat table stays
# readable. Without it the label is upstream's 32-char random id, which tells
# an operator nothing. "web" is accurate here — this worker runs inside the web
# container. Override with SMALLSTACK_WORKER_ID when you run several (per host,
# per queue); a separate worker container sets its own on its command line.
#
# WORKER_WEBHOOKS (default 1) adds that many workers for the outbound webhook
# queue alone, and the main worker skips it. Each delivery can wait up to
# SMALLSTACK_WEBHOOK_TIMEOUT on a slow endpoint, so a fan-out or a retry burst
# on a shared worker held up sign-in emails and scheduled jobs behind it. Each
# extra worker is one more Python process (roughly 60-80 MB). WORKER_WEBHOOKS=0
# runs everything on the one worker, as before.
run_inline_worker() {
    local label="$1"
    shift
    while true; do
        # `|| rc=$?` keeps set -e from ending this loop's subshell on a non-zero
        # exit (a database restart, say), which would leave no worker running.
        local rc=0
        python manage.py db_worker "$@" --worker-id "$label" || rc=$?
        echo "Inline worker $label exited (code $rc), restarting in 5s..."
        sleep 5
    done
}

if [ "${WORKER_INLINE:-true}" = "true" ]; then
    WORKER_LABEL="${SMALLSTACK_WORKER_ID:-web}"
    WEBHOOK_QUEUE="${SMALLSTACK_WEBHOOK_QUEUE:-webhooks}"
    WEBHOOK_WORKERS="${WORKER_WEBHOOKS:-1}"
    WORKER_PIDS=""
    if [ "$WEBHOOK_WORKERS" -gt 0 ]; then
        echo "Starting inline db_worker (all queues but $WEBHOOK_QUEUE) + $WEBHOOK_WORKERS for $WEBHOOK_QUEUE..."
        run_inline_worker "$WORKER_LABEL" --queue-name "*" --exclude-queues "$WEBHOOK_QUEUE" &
        WORKER_PIDS="$!"
        for i in $(seq 1 "$WEBHOOK_WORKERS"); do
            run_inline_worker "$WORKER_LABEL-webhooks-$i" --queue-name "$WEBHOOK_QUEUE" &
            WORKER_PIDS="$WORKER_PIDS $!"
        done
    else
        echo "Starting inline db_worker..."
        run_inline_worker "$WORKER_LABEL" --queue-name "*" &
        WORKER_PIDS="$!"
    fi
    trap "kill $WORKER_PIDS 2>/dev/null; wait $WORKER_PIDS 2>/dev/null" EXIT
fi

echo "Starting application..."
# Execute the main container command
exec "$@"
