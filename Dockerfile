# Dockerfile for Django Admin Starter (Kamal deployment)
# Uses Python 3.12 slim base with UV for dependency management

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1
ENV DJANGO_SETTINGS_MODULE=config.settings.production

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install UV
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv pip install -e .

# Copy the rest of the application
COPY . .

# Create directories for data
RUN mkdir -p /app/data /app/staticfiles /app/media

# Set execute permissions on entrypoint
RUN chmod +x /app/docker-entrypoint.sh

# Expose port 80 (Kamal proxy expects this)
EXPOSE 80

# Health check for Kamal
HEALTHCHECK --interval=10s --timeout=10s --start-period=60s --retries=5 \
    CMD curl --fail http://localhost/health/ || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command
CMD ["gunicorn", "-c", "/app/gunicorn.conf", "config.wsgi:application"]
