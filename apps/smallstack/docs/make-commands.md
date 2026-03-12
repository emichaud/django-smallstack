# Make Commands

SmallStack includes a `Makefile` that turns long, hard-to-remember commands into simple shortcuts. The goal is to make your developer experience easier and get you on a quicker path to success — you shouldn't have to memorize `uv run python manage.py runserver 0.0.0.0:8005` when `make run` does the same thing.

## What is Make?

`make` is a task runner that ships with macOS and Linux. It reads a `Makefile` in your project root and maps short names to shell commands. There's nothing to install — it's already on your system.

To see all available commands at any time:

```bash
make help
```

Or just `make` by itself (help is the default target).

## Available Commands

### Getting Started

| Command | What it does |
|---------|-------------|
| `make setup` | **One-time setup** — installs all dependencies (including dev tools like pytest and ruff), runs migrations, creates dev superuser |
| `make run` | Starts the dev server on port 8005 |

After cloning SmallStack, these two commands are all you need:

```bash
make setup    # Install everything and set up the database
make run      # Start developing
```

That's it. Open `http://localhost:8005` and you're up and running.

### Day-to-Day Development

| Command | What it does |
|---------|-------------|
| `make run` | Start the development server (default port 8005) |
| `make test` | Run the test suite with pytest |
| `make coverage` | Run tests and generate an HTML coverage report |
| `make shell` | Open an interactive Django shell (with shell_plus extras) |
| `make lint` | Check code style with ruff |
| `make lint-fix` | Auto-fix lint issues |

These are the commands you'll use most often. A typical workflow looks like:

```bash
make run          # Start the server, work on your feature
# ... make changes ...
make test         # Verify nothing broke
make lint-fix     # Clean up code style
```

### Database & Backups

| Command | What it does |
|---------|-------------|
| `make migrate` | Apply pending database migrations |
| `make migrations` | Generate new migration files after model changes |
| `make superuser` | Create the development superuser account |
| `make backup` | Create a database backup (saved to `BACKUP_DIR`) |

When you change a model, the two-step process is:

```bash
make migrations   # Generate the migration file
make migrate      # Apply it to the database
```

### Production & Deployment

| Command | What it does |
|---------|-------------|
| `make collectstatic` | Gather static files for production serving |
| `make docker-up` | Build and start Docker containers |
| `make docker-down` | Stop Docker containers |
| `make clean` | Remove `__pycache__`, `.pyc` files, and test caches |
| `make screenshot-auth` | Generate shot-scraper auth JSON for authenticated screenshots |

### Kamal Deployment (Optional)

| Command | What it does |
|---------|-------------|
| `make deploy` | Deploy to production via Kamal |
| `make logs` | View production app logs |

> **Note:** These commands require [Kamal](https://kamal-deploy.org/) to be installed and configured before use. Kamal is an optional deployment utility included with SmallStack — it is not required. See the [Kamal Deployment](/help/smallstack/kamal-deployment/) guide for setup instructions.

A typical deploy workflow:

```bash
make test         # Verify everything passes
make deploy       # Ship it
make logs         # Confirm it's running
```

### Changing the Port

The dev server defaults to port 8005. To use a different port:

```bash
make run PORT=3000
```

## Adding Your Own Commands

One of the best things about the Makefile is how easy it is to extend. If you find yourself running a command repeatedly, add it as a make target.

### Example: Resetting the Database

If you frequently need to wipe and rebuild your dev database:

```makefile
resetdb:
	rm -f db.sqlite3
	uv run python manage.py migrate
	uv run python manage.py create_dev_superuser
	@echo "Database reset complete."
```

Now `make resetdb` handles the whole process.

### Example: Running a Specific Test File

```makefile
test-app:
	uv run pytest apps/$(APP)/tests.py -v

# Usage: make test-app APP=profile
```

### Example: Opening the Project in Your Browser

```makefile
open:
	open http://localhost:$(PORT)

# Usage: make open (opens http://localhost:8005)
```

### Tips for Writing Make Targets

- Add your new target name to the `.PHONY` line at the top of the Makefile
- Indent commands with a **tab character** (not spaces) — this is required by make
- Use `@echo` to print status messages (the `@` hides the command itself from output)
- Use `$(VARIABLE)` to reference variables defined at the top of the Makefile

## Why This Matters

SmallStack is built around the idea that getting started should be fast and staying productive should be easy. The Makefile is a small but important part of that:

- **Onboarding** — A new developer clones the repo, runs `make setup`, then `make run`. Done.
- **Consistency** — Everyone on the team runs the exact same commands with the same flags.
- **Discoverability** — `make help` shows everything available. No digging through docs to find the right incantation.
- **Short memory** — You don't need to remember `uv run python manage.py makemigrations` when `make migrations` works.

The less time you spend remembering commands, the more time you spend building your app.
