"""The entrypoint's inline worker must come back after it exits non-zero.

Downstream-reported (2026-11-07, a Postgres restart): `docker-entrypoint.sh`
runs under `set -e`, and `run_inline_worker` called `db_worker` bare inside its
`while true` loop. A non-zero exit ended the loop's background subshell, the
"restarting" line never ran, and the container kept serving web requests with
no worker behind them.

This runs the shipped function itself under `set -e`, with `python` replaced
by a stub that fails twice and then stops the script.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _shipped_function() -> str:
    text = (REPO_ROOT / "docker-entrypoint.sh").read_text()
    assert text.splitlines()[1] == "set -e", "the entrypoint no longer runs under set -e — revisit this test"
    match = re.search(r"^run_inline_worker\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert match, "docker-entrypoint.sh no longer defines run_inline_worker()"
    return match.group(0)


def test_a_failing_worker_is_restarted(tmp_path):
    calls = tmp_path / "calls"
    script = f"""set -e
{_shipped_function()}
python() {{
    echo "$*" >> {calls}
    [ "$(wc -l < {calls})" -ge 3 ] && exit 0
    return 1
}}
sleep() {{ :; }}
run_inline_worker web --queue-name "*"
"""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls.read_text().splitlines()) == 3, "the worker was not started again after it failed"
    assert result.stdout.count("exited (code 1), restarting") == 2
    assert "--worker-id web" in calls.read_text()
