"""SmallStack's apps keep their tests in a ``tests/`` package, as AGENTS.md says.

Only SmallStack's own apps are checked: a project's apps may keep Django's
``startapp`` layout (a ``tests.py`` beside the code) if it likes.

A ``test_*.py`` or ``tests.py`` beside the app's code splits one app's tests
across two places, and a ``tests_*.py`` there isn't even collected (pytest's
``python_files`` doesn't match it): ``apps/help/tests_llms.py`` held five tests
that never ran.
"""

from __future__ import annotations

from pathlib import Path

from apps.smallstack.template_hygiene import FRAMEWORK_APPS

APPS = Path(__file__).resolve().parents[2]


def test_no_test_modules_at_an_apps_root():
    stray = sorted(
        str(p.relative_to(APPS.parent))
        for app in (APPS / name for name in FRAMEWORK_APPS)
        if app.is_dir()
        for pattern in ("test_*.py", "tests.py", "tests_*.py", "*_test.py")
        for p in app.glob(pattern)
    )
    assert not stray, "move these into the app's tests/ package:\n" + "\n".join(stray)


def test_every_tests_package_is_a_package():
    """Without __init__.py, two apps' test_views.py collide under pytest's default import mode."""
    missing = sorted(
        str(d.relative_to(APPS.parent))
        for d in (APPS / name / "tests" for name in FRAMEWORK_APPS)
        if d.is_dir() and not (d / "__init__.py").exists()
    )
    assert not missing, missing
