"""search_doctor management command."""

from __future__ import annotations

import json as jsonlib
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _run(args=None):
    out = StringIO()
    call_command("search_doctor", *(args or []), stdout=out)
    return out.getvalue()


def test_doctor_runs_without_crashing():
    output = _run()
    assert "SmallStack Search — Doctor" in output
    assert "Summary:" in output


def test_doctor_json_emits_valid_json():
    output = _run(["--json"])
    parsed = jsonlib.loads(output)
    assert isinstance(parsed, list)
    assert all(isinstance(r, dict) for r in parsed)


def test_doctor_check_backend_present():
    output = _run(["--json"])
    parsed = jsonlib.loads(output)
    names = {r["name"] for r in parsed}
    assert "Search backend" in names
    assert "Search registry" in names
    assert "URL conf" in names


def test_doctor_explain_dumps_indexed_models():
    output = _run(["--explain"])
    # With or without registered views, should not crash.
    assert isinstance(output, str)
