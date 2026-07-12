"""Shared CLI plumbing for SmallStack's console-script shims and management-command CLIs.

Two concerns, both dependency-free (stdlib only) so a ``[project.scripts]`` shim can import
this **before** Django is configured:

- **Console-script launcher** — ``find_manage_py`` + ``run_management_command`` find the
  project's ``manage.py`` by walking up from the cwd and exec ``manage.py <command> <args>``
  with stdio inherited (so ``cmd | sc write …`` piping survives). Used by ``apps/smallstack/shim.py``
  (``sc``) and ``apps/runbook/shim.py`` (``rb``).
- **Output formatters** — ``table`` / ``json_dump`` / ``asdict``, the monospace-table + JSON
  renderers the runbook and ``sc`` CLIs share.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

# -- Console-script launcher --------------------------------------------------

def find_manage_py(start: Path) -> Optional[Path]:
    """Return the nearest ``manage.py`` at or above ``start`` (else ``None``)."""
    for directory in (start, *start.parents):
        candidate = directory / "manage.py"
        if candidate.is_file():
            return candidate
    return None


def run_management_command(command: str, argv: Optional[Sequence[str]] = None) -> int:
    """Dispatch ``<shim> <args>`` to ``manage.py <command> <args>``.

    Finds ``manage.py`` by walking up from the cwd, then runs it with stdio inherited
    (no capture) so ``some_cmd | <shim> …`` piping still works. Returns the child exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    manage_py = find_manage_py(Path.cwd())
    if manage_py is None:
        sys.stderr.write(f"{command}: no manage.py found in this directory or any parent.\n")
        return 2
    return subprocess.run([sys.executable, str(manage_py), command, *args]).returncode


# -- Output formatters --------------------------------------------------------

def json_dump(payload: Any) -> str:
    """Machine-readable JSON: indented, ``default=str`` for dates/UUIDs/etc."""
    return json.dumps(payload, indent=2, default=str)


def asdict(obj: Any) -> dict[str, Any]:
    """``dataclasses.asdict`` shorthand for the frozen result dataclasses the CLIs return."""
    return dataclasses.asdict(obj)


def table(rows: list[list[str]], headers: list[str]) -> str:
    """Render a simple left-aligned monospace table (headers + rows)."""
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(cell)) for cell in col) for col in cols]
    line = lambda cells: "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))  # noqa: E731
    out = [line(headers)]
    if rows:
        for row in rows:
            out.append(line(row))
    return "\n".join(out)
