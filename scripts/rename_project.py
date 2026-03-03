#!/usr/bin/env python3
"""
Project Rename Script

This script helps you rename the Django Admin Starter project to your own project name.
It will update references throughout the codebase.

Usage:
    python scripts/rename_project.py <new_project_name>

Example:
    python scripts/rename_project.py my_awesome_app

The script will:
1. Rename references in pyproject.toml
2. Update the site name in templates
3. Update CSS comments and documentation
4. Provide guidance on manual steps

WARNING: Always backup your project before running this script!
"""

import re
import sys
from pathlib import Path


def snake_case(name: str) -> str:
    """Convert a name to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower().replace("-", "_").replace(" ", "_")


def title_case(name: str) -> str:
    """Convert a name to Title Case."""
    return " ".join(word.capitalize() for word in name.replace("_", " ").replace("-", " ").split())


def replace_in_file(filepath: Path, replacements: list[tuple[str, str]]) -> bool:
    """Replace text in a file. Returns True if any changes were made."""
    try:
        content = filepath.read_text(encoding="utf-8")
        original = content
        for old, new in replacements:
            content = content.replace(old, new)
        if content != original:
            filepath.write_text(content, encoding="utf-8")
            return True
        return False
    except Exception as e:
        print(f"  Warning: Could not process {filepath}: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/rename_project.py <new_project_name>")
        print("Example: python scripts/rename_project.py my_awesome_app")
        sys.exit(1)

    new_name = sys.argv[1]
    new_name_snake = snake_case(new_name)
    new_name_title = title_case(new_name)

    project_root = Path(__file__).parent.parent.absolute()

    print(f"\nRenaming project to: {new_name}")
    print(f"  Snake case: {new_name_snake}")
    print(f"  Title case: {new_name_title}")
    print(f"  Project root: {project_root}")
    print()

    # Define replacements
    replacements = [
        ("admin-starter", new_name_snake.replace("_", "-")),
        ("admin_starter", new_name_snake),
        ("Admin Starter", new_name_title),
        ("AdminStarter", new_name.replace("-", "").replace("_", "").title()),
    ]

    # Files to process
    files_to_process = [
        "pyproject.toml",
        "Makefile",
        "README.md",
        "docker-compose.yml",
        "Dockerfile",
        "docs/theming.md",
        "docs/renaming.md",
        "templates/admin_theme/base.html",
        "templates/home.html",
        "templates/registration/login.html",
        "templates/registration/logged_out.html",
        "templates/registration/signup.html",
        "templates/registration/password_reset_form.html",
        "templates/registration/password_reset_done.html",
        "templates/registration/password_reset_confirm.html",
        "templates/registration/password_reset_complete.html",
        "static/css/theme.css",
        "static/js/theme.js",
    ]

    changed_files = []

    for file_path in files_to_process:
        full_path = project_root / file_path
        if full_path.exists():
            if replace_in_file(full_path, replacements):
                changed_files.append(file_path)
                print(f"  Updated: {file_path}")
        else:
            print(f"  Skipped (not found): {file_path}")

    print(f"\nUpdated {len(changed_files)} files.")
    print("\n" + "=" * 60)
    print("MANUAL STEPS REQUIRED:")
    print("=" * 60)
    print("""
1. Update .env file with new SECRET_KEY for your project

2. If you want to rename the 'config' folder:
   - Rename the folder: mv config <new_name>
   - Update manage.py: change 'config.settings.development'
   - Update wsgi.py: change 'config.wsgi.application'
   - Update asgi.py: change references
   - Update pyproject.toml pytest section

3. If you want to rename the apps folder:
   - Update all app imports in settings, urls, etc.

4. Delete unused files:
   - rm -rf .git  (to start fresh)
   - git init

5. Create new migrations if you renamed models:
   - python manage.py makemigrations

See docs/renaming.md for more details.
""")


if __name__ == "__main__":
    main()
