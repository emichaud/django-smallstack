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
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Checking for superuser..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists():
    User.objects.create_superuser(
        username='$DJANGO_SUPERUSER_USERNAME',
        email='${DJANGO_SUPERUSER_EMAIL:-admin@example.com}',
        password='$DJANGO_SUPERUSER_PASSWORD'
    )
    print('Superuser created.')
else:
    print('Superuser already exists.')
"
fi

# Always set up cron for scheduled tasks (heartbeat, backups, etc.)
echo "Setting up scheduled tasks..."
echo "export PATH=$PATH" > /app/.env.cron
printenv | grep -E '^(DATABASE_|SECRET_KEY|DJANGO_|BACKUP_|EMAIL_|ALLOWED_|HEARTBEAT_)' | sed 's/^/export /' >> /app/.env.cron
chmod 600 /app/.env.cron
crontab /app/scripts/smallstack-cron
cron
echo "Cron scheduler started."

echo "Starting application..."
# Execute the main container command
exec "$@"
