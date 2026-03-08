# Screenshot Workflow with shot-scraper

Use `shot-scraper` to capture screenshots of running pages during development. This enables visual verification of UI changes, comparing before/after states, and documenting features.

## Prerequisites

`shot-scraper` is installed system-wide via `uv tool install shot-scraper`. It is available as a bare command from any directory — do NOT add it to project dependencies.

```bash
# Already installed. Verify with:
shot-scraper --version
```

If not installed:
```bash
uv tool install shot-scraper
shot-scraper install  # downloads Chromium browser
```

## Basic Usage

```bash
# Screenshot a URL (auto-names the file)
shot-scraper http://localhost:8005/

# Specify output file
shot-scraper http://localhost:8005/ -o screenshots/home.png

# Set viewport dimensions
shot-scraper http://localhost:8005/ -o home.png --width 1280 --height 900

# Full-page screenshot (captures entire scrollable content)
shot-scraper http://localhost:8005/activity/ -o activity-full.png --width 1280

# Screenshot a specific CSS selector
shot-scraper http://localhost:8005/ -s ".main-content" -o content-only.png

# Screenshot just a card
shot-scraper http://localhost:8005/activity/ -s ".card:first-child" -o first-card.png
```

## Development Workflow

### 1. Before/After Comparisons

When making UI changes, capture the current state first:

```bash
# Before changes
shot-scraper http://localhost:8005/activity/users/ -o before.png --width 1280 --height 900

# ... make your changes ...

# After changes
shot-scraper http://localhost:8005/activity/users/ -o after.png --width 1280 --height 900
```

### 2. Dark and Light Mode

The default theme is dark. To capture light mode, use JavaScript to toggle:

```bash
# Dark mode (default)
shot-scraper http://localhost:8005/ -o dark.png --width 1280 --height 900

# Light mode — set theme before screenshot
shot-scraper http://localhost:8005/ -o light.png --width 1280 --height 900 \
  --javascript "document.documentElement.setAttribute('data-theme', 'light')"
```

### 3. Multiple Pages at Once

Create a YAML file for batch screenshots:

```yaml
# screenshots.yml
- url: http://localhost:8005/
  output: screenshots/home.png
  width: 1280
  height: 900
- url: http://localhost:8005/blog/
  output: screenshots/blog.png
  width: 1280
  height: 900
- url: http://localhost:8005/activity/
  output: screenshots/activity.png
  width: 1280
  height: 900
```

```bash
shot-scraper multi screenshots.yml
```

### 4. Authenticated Pages

Pages behind login (profile, activity dashboard, admin sections) require authentication. Use `shot-scraper auth` to save a browser session:

```bash
# Interactive login — opens a browser, you log in, it saves the session
shot-scraper auth http://localhost:8005/accounts/login/ auth.json

# Then use the session for screenshots
shot-scraper http://localhost:8005/activity/ -o activity.png --auth auth.json --width 1280 --height 900
```

**Do not commit auth.json** — add it to `.gitignore`.

### 5. Responsive Testing

```bash
# Desktop
shot-scraper http://localhost:8005/ -o desktop.png --width 1280 --height 900

# Tablet
shot-scraper http://localhost:8005/ -o tablet.png --width 768 --height 1024

# Mobile
shot-scraper http://localhost:8005/ -o mobile.png --width 375 --height 812
```

## Using with Claude Code

Claude can take screenshots and read them to visually verify UI work. This is useful for:

- **Verifying changes render correctly** — after modifying templates or CSS, Claude takes a screenshot and confirms the result matches intent.
- **Spotting visual bugs** — contrast issues, layout breaks, missing elements, wrong colors in dark/light mode.
- **Iterating on design** — capture the current state, discuss what to change, implement, screenshot again.

**Typical Claude workflow:**

1. Start the dev server: `make run` (or `uv run python manage.py runserver 0.0.0.0:PORT`)
2. Take screenshot: `shot-scraper http://localhost:PORT/page/ -o screenshot.png --width 1280 --height 900`
3. Read the screenshot to see the rendered result
4. Make changes based on what's visible
5. Screenshot again to verify

**Important:** The dev server must be running for screenshots to work. If running in a sandbox project, use the appropriate port (e.g., 8008 for sandbox, 8005 for base).

## Port Reference

| Project | Default Port |
|---------|-------------|
| smallstack (base) | 8005 |
| smallstack_web | 8005 |
| opshugger | 8005 |
| sandbox | 8008 |

## File Organization

Store screenshots in a `screenshots/` directory at the project root. Add it to `.gitignore` unless you intentionally want to commit them (e.g., for documentation).

```bash
echo "screenshots/" >> .gitignore
```
