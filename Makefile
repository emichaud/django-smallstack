# Makefile for Django SmallStack
# Run 'make help' to see available commands

.PHONY: help run migrate migrations superuser shell test collectstatic docker-up docker-down lint clean deploy logs

# Default port for development server
PORT ?= 8005

help:
	@echo "Django SmallStack - Available commands:"
	@echo ""
	@echo "  make run          - Start development server on port $(PORT)"
	@echo "  make migrate      - Run database migrations"
	@echo "  make migrations   - Create new migrations"
	@echo "  make superuser    - Create development superuser"
	@echo "  make shell        - Open Django shell_plus"
	@echo "  make test         - Run pytest tests"
	@echo "  make collectstatic - Collect static files"
	@echo "  make docker-up    - Start Docker containers"
	@echo "  make docker-down  - Stop Docker containers"
	@echo "  make lint         - Run ruff linter"
	@echo "  make clean        - Clean up generated files"
	@echo ""
	@echo "Kamal Deployment (requires Kamal to be configured):"
	@echo "  make deploy       - Deploy to production via Kamal"
	@echo "  make logs         - View production app logs"
	@echo ""

run:
	uv run python manage.py runserver 0.0.0.0:$(PORT)

migrate:
	uv run python manage.py migrate

migrations:
	uv run python manage.py makemigrations

superuser:
	uv run python manage.py create_dev_superuser

shell:
	uv run python manage.py shell_plus

test:
	uv run pytest

collectstatic:
	uv run python manage.py collectstatic --noinput

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

# Kamal deployment (optional - requires Kamal to be installed and configured)
# See /help/smallstack/kamal-deployment/ for setup guide
deploy:
	kamal deploy

logs:
	kamal app logs

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov staticfiles 2>/dev/null || true

# Initial setup helper
setup:
	uv sync --all-extras
	uv run python manage.py migrate
	uv run python manage.py create_dev_superuser
	@echo ""
	@echo "Setup complete! Run 'make run' to start the development server."
