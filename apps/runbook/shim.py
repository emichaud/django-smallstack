"""``rb`` — a console-script shim for the ``runbook`` management command.

Registered via ``[project.scripts]`` in SmallStack's ``pyproject.toml``
(``rb = apps.runbook.shim:main``), so in an installed SmallStack project you can type::

    rb ls
    echo "# Report" | rb write ops/report --title Report

instead of the full ``python manage.py runbook …`` — and the stdin pipe keeps working. The
launcher (find ``manage.py``, inherit stdio) is shared with the ``sc`` shim in
``apps/smallstack/cli_format.py``, so it travels upstream cleanly.
"""

from __future__ import annotations

from typing import Optional, Sequence

# find_manage_py re-exported for back-compat (older callers/tests import it from here).
from apps.smallstack.cli_format import find_manage_py, run_management_command  # noqa: F401


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point: dispatch ``rb <args>`` to ``manage.py runbook <args>``."""
    return run_management_command("runbook", argv)
