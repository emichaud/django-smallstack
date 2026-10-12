"""Nothing may resolve a URL while the app registry is still initialising.

The trap, which is easy to fall into and brutal to diagnose: calling
``reverse()`` (or touching ``get_resolver().url_patterns``) during
``AppConfig.ready()`` — or in any code that startup happens to execute, such as
a ModelForm's ``__init__``, since the CRUD/OpenAPI machinery instantiates forms
at boot — forces Django to build the **root URLConf early**. Django caches that
resolver permanently. Every app whose routes are registered later then has
none: Explorer builds its CRUD classes in ``ready()`` and appends them to
``apps/explorer/urls.py`` at import, so an early load leaves it with *zero*
model routes.

The failure surfaces nowhere near its cause — as a pile of ``NoReverseMatch``
errors in unrelated apps' tests — so this file asserts the symptom directly
with a name that points at the cause. If it fails, something new is calling
``reverse()`` too early; make it lazy (``django.utils.functional.lazy`` or
``reverse_lazy``) rather than relaxing the assertion.

Found the hard way: a blog form stamped its preview endpoint into a widget
attribute with ``reverse()`` in ``__init__``, which silently removed every
Explorer route in the project.
"""

from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Run in a FRESH interpreter: by the time the pytest process gets here the
# URLConf is long since built, so an in-process check could never see the bug.
_PROBE = """
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()
from django.urls import get_resolver

names = set()
def walk(patterns):
    for p in patterns:
        if hasattr(p, "url_patterns"):
            walk(p.url_patterns)
        elif p.name:
            names.add(p.name)
walk(get_resolver().url_patterns)

print("EXPLORER_ROUTES=%d" % len([n for n in names if n.startswith("explorer/")]))
print("TOTAL_ROUTES=%d" % len(names))
"""


_CACHE: dict[str, int] = {}


def _probe() -> dict[str, int]:
    # One subprocess for the whole module: Django startup is not cheap and the
    # answer cannot change between two tests in the same run.
    if _CACHE:
        return _CACHE
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stdout}\n{result.stderr}"
    out = {}
    for line in result.stdout.splitlines():
        if "=" in line and line.split("=")[0] in {"EXPLORER_ROUTES", "TOTAL_ROUTES"}:
            key, value = line.split("=", 1)
            out[key] = int(value)
    _CACHE.update(out)
    return out


def test_explorer_routes_survive_startup():
    """The canary. Explorer registers its CRUD classes during ``ready()``, so
    it is the first casualty of an early URLConf load — and the most visible."""
    counts = _probe()
    assert counts["EXPLORER_ROUTES"] > 0, (
        "Explorer has no model routes, which means the root URLConf was built "
        "before the app registry finished loading. Something is calling "
        "reverse() at import/ready() time — in an AppConfig.ready(), at a "
        "module level, or in a ModelForm.__init__ (forms are instantiated at "
        "startup by the CRUD/OpenAPI machinery). Make that call lazy."
    )


def test_the_urlconf_is_substantially_populated():
    """A second, app-agnostic guard, so this still means something in a fork
    that has removed Explorer."""
    counts = _probe()
    assert counts["TOTAL_ROUTES"] > 100, (
        f"only {counts['TOTAL_ROUTES']} named routes resolved — the URLConf "
        "looks truncated, which is the same early-load symptom."
    )
