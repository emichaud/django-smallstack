# Dockerfile for Django SmallStack (Kamal deployment)
# Uses Python 3.12 slim base with UV for dependency management

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1
ENV DJANGO_SETTINGS_MODULE=config.settings.production

# Set work directory
WORKDIR /app

# Install system dependencies + supercronic (cron for non-root containers)
ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-amd64
ENV SUPERCRONIC_SHA1SUM=71b0d58cc53f6bd72cf2f293e09e294b79c666d8
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSLO "$SUPERCRONIC_URL" \
    && echo "$SUPERCRONIC_SHA1SUM  supercronic-linux-amd64" | sha1sum -c - \
    && chmod +x supercronic-linux-amd64 \
    && mv supercronic-linux-amd64 /usr/local/bin/supercronic

# Install UV
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv pip install -e .

# Copy the rest of the application
COPY . .

# Create non-root user and set up directories
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash app \
    && mkdir -p /app/data /app/staticfiles /app/media \
    && chown -R app:app /app \
    && chmod +x /app/docker-entrypoint.sh

# Expose port 8000 (Kamal proxy maps external traffic here)
EXPOSE 8000

# Run as non-root
USER app

# Health check for Kamal
HEALTHCHECK --interval=10s --timeout=10s --start-period=60s --retries=5 \
    CMD curl --fail http://localhost:8000/health/ || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command
CMD ["gunicorn", "-c", "/app/gunicorn.conf", "config.wsgi:application"]
