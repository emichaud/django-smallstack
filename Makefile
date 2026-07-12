# Makefile for Django SmallStack
# Run 'make help' to see available commands

.PHONY: help run services migrate migrations superuser shell test coverage collectstatic docker-up docker-down lint clean deploy logs backup screenshot-auth optimize-images mcp-doctor mcp-test api-test

# Default port for development server
PORT ?= 8005

help:
	@echo "Django SmallStack - Available commands:"
	@echo ""
	@echo "  make run          - Start development server on port $(PORT)"
	@echo "  make services     - Run worker + heartbeat locally (utils/dev_services.sh; ARGS=... to pass flags)"
	@echo "  make migrate      - Run database migrations"
	@echo "  make migrations   - Create new migrations"
	@echo "  make superuser    - Create development superuser"
	@echo "  make shell        - Open Django shell_plus"
	@echo "  make test         - Run pytest with coverage summary"
	@echo "  make coverage     - Run tests and open HTML coverage report"
	@echo "  make collectstatic - Collect static files"
	@echo "  make docker-up    - Start Docker containers"
	@echo "  make docker-down  - Stop Docker containers"
	@echo "  make backup       - Create a database backup"
	@echo "  make mcp-doctor   - Diagnose the MCP server (settings, URLs, registry, self-test)"
	@echo "  make mcp-test     - End-to-end MCP smoke test (requires \`make run\` in another shell)"
	@echo "  make api-test     - End-to-end REST API smoke test (requires \`make run\` in another shell)"
	@echo "  make lint         - Run ruff linter"
	@echo "  make screenshot-auth - Generate shot-scraper auth JSON"
	@echo "  make optimize-images - Optimize PNG images with pngquant"
	@echo "  make clean        - Clean up generated files"
	@echo ""
	@echo "Kamal Deployment (requires Kamal to be configured):"
	@echo "  make deploy       - Deploy to production via Kamal"
	@echo "  make logs         - View production app logs"
	@echo ""

run:
	uv run python manage.py runserver 0.0.0.0:$(PORT)

# Simulate the production background processes (db_worker + heartbeat) locally.
# Pass flags via ARGS, e.g.  make services ARGS="--interval 5 --smoke"
services:
	./utils/dev_services.sh $(ARGS)

migrate:
	uv run python manage.py migrate

migrations:
	uv run python manage.py makemigrations

superuser:
	uv run python manage.py create_dev_superuser

shell:
	uv run python manage.py shell_plus

test:
	uv sync --extra dev --quiet
	uv run pytest

coverage:
	uv sync --extra dev --quiet
	uv run pytest --cov-report=html
	@echo ""
	@echo "HTML report: open htmlcov/index.html"

collectstatic:
	uv run python manage.py collectstatic --noinput

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

backup:
	uv run python manage.py backup_db

# MCP diagnostics. mcp-doctor is offline (in-process self-test); mcp-test
# hits a real HTTP server, so the server must be running in another shell.
mcp-doctor:
	uv run python manage.py mcp_doctor

mcp-test:
	uv run python manage.py mcp_smoke --url http://localhost:$(PORT)/mcp

# REST API end-to-end smoke (mirrors mcp-test). The server must be running.
api-test:
	uv run python manage.py api_smoke --base-url http://localhost:$(PORT)

screenshot-auth:
	@uv run python manage.py screenshot_auth 2>/dev/null

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

optimize-images:
	@command -v pngquant >/dev/null 2>&1 || { echo "Install pngquant: brew install pngquant"; exit 1; }
	find apps/help -name "*.png" -exec pngquant --force --quality=65-80 --skip-if-larger {} \;
	find static/smallstack/brand -name "*.png" -exec pngquant --force --quality=65-80 --skip-if-larger {} \;
	@echo "Images optimized."

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
	uv run python manage.py check
	@echo ""
	@echo "Setup complete! Run 'make run' to start the development server."
