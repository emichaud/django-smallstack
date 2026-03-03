---
title: Package Management
description: Using UV, pip, and other Python package managers
---

# Package Management

{{ project_name }} uses **UV** as its default package manager. This guide explains why UV was chosen and how to use alternative tools if you prefer.

## Why UV?

[UV](https://github.com/astral-sh/uv) is a modern Python package manager written in Rust that has gained significant traction in the Python community. It was selected as the default for {{ project_name }} because:

- **Speed** - UV is 10-100x faster than pip for most operations
- **Reliability** - Better dependency resolution with fewer conflicts
- **Modern defaults** - Built-in virtual environment management
- **Growing adoption** - Widely embraced by the Python community
- **Drop-in replacement** - Compatible with existing `requirements.txt` and `pyproject.toml`

## Quick Reference: UV Commands

| Task | Command |
|------|---------|
| Install dependencies | `uv sync` |
| Add a package | `uv add package-name` |
| Remove a package | `uv remove package-name` |
| Run a command | `uv run python manage.py runserver` |
| Run tests | `uv run pytest` |
| Update all packages | `uv sync --upgrade` |
| Show installed packages | `uv pip list` |

## Installing UV

### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Windows

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### With pip

```bash
pip install uv
```

### With Homebrew (macOS)

```bash
brew install uv
```

## Using UV with {{ project_name }}

### Initial Setup

```bash
# Clone the project
cd admin_starter

# Install all dependencies (creates .venv automatically)
uv sync

# Run the development server
uv run python manage.py runserver
```

### Adding Dependencies

```bash
# Add a production dependency
uv add django-extensions

# Add a development dependency
uv add --dev pytest-django
```

UV automatically updates both `pyproject.toml` and `uv.lock`.

### Running Commands

Always prefix Django commands with `uv run` to use the project's virtual environment:

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py collectstatic
uv run pytest
```

### The Lock File

UV creates a `uv.lock` file that pins exact versions of all dependencies. This ensures reproducible builds across different machines and deployments.

- **Commit `uv.lock`** to version control
- Run `uv sync` to install exact versions from the lock file
- Run `uv sync --upgrade` to update packages and regenerate the lock

---

## Alternative: Using pip

If you prefer traditional pip, {{ project_name }} works perfectly with it.

### Setup with pip

```bash
# Create a virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows

# Install dependencies from pyproject.toml
pip install -e .

# Or generate and use requirements.txt
pip install -r requirements.txt
```

### Generating requirements.txt

If you need a `requirements.txt` for deployment or compatibility:

```bash
# From UV
uv pip compile pyproject.toml -o requirements.txt

# Or with pip-tools
pip install pip-tools
pip-compile pyproject.toml -o requirements.txt
```

### Running Commands with pip

With an activated virtual environment, run commands directly:

```bash
# Activate first
source .venv/bin/activate

# Then run without prefix
python manage.py runserver
python manage.py migrate
pytest
```

---

## Alternative: Using Poetry

[Poetry](https://python-poetry.org/) is another popular choice with excellent dependency management.

### Converting to Poetry

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Initialize from existing pyproject.toml
poetry install

# Run commands
poetry run python manage.py runserver
```

### Poetry Commands

| Task | Command |
|------|---------|
| Install dependencies | `poetry install` |
| Add a package | `poetry add package-name` |
| Add dev dependency | `poetry add --group dev package-name` |
| Run a command | `poetry run python manage.py runserver` |
| Update packages | `poetry update` |
| Show packages | `poetry show` |

---

## Alternative: Using PDM

[PDM](https://pdm-project.org/) is a modern package manager that follows PEP standards closely.

### Converting to PDM

```bash
# Install PDM
pip install pdm

# Import existing project
pdm import pyproject.toml

# Install dependencies
pdm install

# Run commands
pdm run python manage.py runserver
```

---

## Alternative: Using Conda

For data science projects or when you need non-Python dependencies:

```bash
# Create environment
conda create -n admin_starter python=3.12

# Activate
conda activate admin_starter

# Install pip dependencies
pip install -e .

# Run commands directly
python manage.py runserver
```

---

## Docker Considerations

The included `Dockerfile` uses UV for fast, reproducible builds:

```dockerfile
# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install dependencies
RUN uv sync --frozen --no-cache
```

### Using pip in Docker Instead

If you prefer pip in Docker, modify the `Dockerfile`:

```dockerfile
# Replace UV installation with:
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

Generate `requirements.txt` first:

```bash
uv pip compile pyproject.toml -o requirements.txt
```

---

## Comparison Summary

| Feature | UV | pip | Poetry | PDM |
|---------|-----|-----|--------|-----|
| Speed | Fastest | Slow | Medium | Fast |
| Lock file | Yes | No* | Yes | Yes |
| Virtual env management | Built-in | Manual | Built-in | Built-in |
| pyproject.toml | Yes | Limited | Yes | Yes |
| Maturity | New | Mature | Mature | Medium |
| Community | Growing fast | Universal | Large | Growing |

*pip can use pip-tools for lock files

## Recommendations

- **New projects**: UV is recommended for its speed and modern features
- **Existing pip workflow**: Continue using pip if your team is comfortable with it
- **Complex dependencies**: Poetry or PDM offer robust resolution
- **Data science**: Conda may be better for non-Python packages
- **Maximum compatibility**: pip works everywhere Python runs

## Switching Between Tools

All these tools read `pyproject.toml`, making it easy to switch:

1. Delete the existing virtual environment (`.venv/`)
2. Delete the tool-specific lock file (`uv.lock`, `poetry.lock`, `pdm.lock`)
3. Install with your preferred tool

The project will work the same regardless of which package manager you choose.
