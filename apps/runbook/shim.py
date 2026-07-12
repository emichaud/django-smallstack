"""``rb`` — a console-script shim for the ``runbook`` management command.

Registered via ``[project.scripts]`` in SmallStack's ``pyproject.toml``
(``rb = apps.runbook.shim:main``), so in an installed SmallStack project you can type::

    rb ls
    echo "# Report" | rb write ops/report --title Report

instead of the full ``python manage.py runbook …`` — and the stdin pipe keeps working.

The shim finds the project's ``manage.py`` by walking up from the current
directory, then execs ``python manage.py runbook <args>`` with stdio inherited.
Keeping the launcher inside the package (rather than a stray ``scripts/rb`` in the
consumer) means it travels with the code when the app is merged upstream.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


def find_manage_py(start: Path) -> Optional[Path]:
    """Return the nearest ``manage.py`` at or above ``start`` (else ``None``)."""
    for directory in (start, *start.parents):
        candidate = directory / "manage.py"
        if candidate.is_file():
            return candidate
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point: dispatch ``rb <args>`` to ``manage.py runbook <args>``."""
    args = list(sys.argv[1:] if argv is None else argv)
    manage_py = find_manage_py(Path.cwd())
    if manage_py is None:
        sys.stderr.write("rb: no manage.py found in this directory or any parent.\n")
        return 2
    # Inherit stdio (no capture) so `some_cmd | rb write …` piping still works.
    return subprocess.run([sys.executable, str(manage_py), "runbook", *args]).returncode
