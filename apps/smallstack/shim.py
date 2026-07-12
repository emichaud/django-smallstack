"""``sc`` — a console-script shim for the ``sc`` management command (SmallStack's framework CLI).

Registered via ``[project.scripts]`` in ``pyproject.toml`` (``sc = apps.smallstack.shim:main``),
so in an installed SmallStack project you can type::

    sc ls
    sc get user 3
    echo "..." | sc new note --stdin-field=body

instead of the full ``python manage.py sc …`` — and the stdin pipe keeps working. The launcher
lives inside the framework app so it travels upstream to every derived project.
"""

from __future__ import annotations

from typing import Optional, Sequence

from apps.smallstack.cli_format import run_management_command


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point: dispatch ``sc <args>`` to ``manage.py sc <args>``."""
    return run_management_command("sc", argv)
