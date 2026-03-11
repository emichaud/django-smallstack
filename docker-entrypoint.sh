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

# Create superuser if environment variables are set and user doesn't exist
python manage.py ensure_superuser

# Start scheduled tasks (heartbeat, backups, etc.) via supercronic
# supercronic runs as non-root and inherits the current environment
echo "Starting scheduled tasks..."
supercronic -passthrough-logs /app/scripts/smallstack-cron &

echo "Starting application..."
# Execute the main container command
exec "$@"
