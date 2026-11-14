"""Tests for the api_doctor management command."""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command

from apps.smallstack.autodiscover import has_enable_classvar

pytestmark = pytest.mark.django_db


def _run(args=None, **opts):
    """Invoke api_doctor with capture, return the stdout string."""
    from io import StringIO

    out = StringIO()
    call_command("api_doctor", *(args or []), stdout=out, **opts)
    return out.getvalue()


def test_doctor_runs_without_crashing():
    output = _run(["--no-self-test"])
    assert "SmallStack API — Doctor" in output
    assert "Summary:" in output


def test_doctor_json_emits_valid_json():
    output = _run(["--no-self-test", "--json"])
    parsed = json.loads(output)
    assert isinstance(parsed, list)
    assert all(isinstance(r, dict) for r in parsed)
    assert all({"name", "status", "detail"} <= set(r.keys()) for r in parsed)


def test_doctor_explain_dumps_registry():
    """--explain should dump every endpoint with its model + URL name."""
    output = _run(["--explain"])
    from apps.smallstack.api import _api_registry

    if _api_registry:
        # At least the first model name should appear.
        first = _api_registry[0][0].model.__name__
        assert first in output
    else:
        assert "no endpoints registered" in output


def test_doctor_check_openapi_validity_passes():
    """The bundled OpenAPI builder must produce a valid spec."""
    output = _run(["--no-self-test", "--json"])
    parsed = json.loads(output)
    validity = next(r for r in parsed if r["name"] == "OpenAPI validity")
    assert validity["status"] == "PASS", validity


def test_doctor_lists_custom_registered_paths():
    """Hand-registered (register_api_path) endpoints — which aren't CRUDViews —
    must appear in the doctor's inventory, not just the OpenAPI schema."""
    from apps.smallstack.api import _custom_api_registry

    parsed = json.loads(_run(["--no-self-test", "--json"]))
    card = next(r for r in parsed if r["name"] == "Custom endpoints")
    assert card["detail"]["total"] == len(_custom_api_registry)
    if _custom_api_registry:
        # Every resolvable custom path is listed with its methods.
        assert card["paths"], card
        assert all(" /" in p for p in card["paths"])  # "<METHODS> <path>"
    # Human output surfaces the section too.
    assert "Custom endpoints" in _run(["--no-self-test"])


def test_doctor_check_urls_passes():
    """All canonical API URL names must resolve."""
    output = _run(["--no-self-test", "--json"])
    parsed = json.loads(output)
    urls = next(r for r in parsed if r["name"] == "URL conf")
    assert urls["status"] == "PASS"
    assert "api-schema" in urls["detail"]
    assert "api-docs" in urls["detail"]


def test_doctor_self_test_mints_and_revokes():
    """The self-test must leave no stray APIToken behind (it's deleted in finally)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    User.objects.create_user(username="doctor-test-u", password="p", email="d@example.com")
    from apps.smallstack.models import APIToken

    before = APIToken.objects.count()
    output = _run([])  # default = run self-test
    after = APIToken.objects.count()
    assert before == after, "self-test leaked an APIToken"
    parsed_marker = "Self-test" in output
    assert parsed_marker


def test_doctor_orphan_detection_ignores_explorer_enable_api():
    """The orphan scanner must not match `explorer_enable_api = True`
    (a SmallStack admin-options name that contains the same suffix)."""
    output = _run(["--no-self-test", "--json"])
    parsed = json.loads(output)
    orphans = next(r for r in parsed if r["name"] == "Orphan files")
    # heartbeat/admin.py has `explorer_enable_api = True` — must not surface.
    assert "heartbeat/admin.py" not in str(orphans.get("orphans", []))


def test_doctor_orphan_detection_ignores_test_modules():
    """A CRUDView declared in a test module is a fixture, not an orphan.

    `apps/smallstack/tests/test_bulk_ops.py` declares `enable_api = True` on a
    throwaway view. The scanner excluded a `tests/` package but not the flat
    `test_*.py` layout that app uses, so it was reported as an orphan on every
    run — and the advertised fix (import it from `AppConfig.ready()`) would have
    published a test view as a live API surface.
    """
    output = _run(["--no-self-test", "--json"])
    parsed = json.loads(output)
    orphans = next(r for r in parsed if r["name"] == "Orphan files")
    listed = str(orphans.get("orphans", []))
    assert "test_bulk_ops" not in listed
    assert orphans["status"] == "PASS"


def test_doctor_optin_scan_ignores_docstring_examples():
    """A teaching example in a docstring is not an opt-in.

    The old line-anchored regex matched `enable_api = True` anywhere a line held
    only whitespace before it — i.e. exactly how a code example is indented
    inside a docstring. This codebase documents its own flags that way, so the
    regex was one idiomatic docstring away from a false orphan.
    """
    from apps.api.management.commands.api_doctor import Command

    source = '''
class Docs:
    """Expose a model over REST:

        class TicketView(CRUDView):
            enable_api = True
    """
    pass
'''
    assert has_enable_classvar(source, "enable_api") is False
    # …and the real thing still registers
    assert has_enable_classvar("class V(CRUDView):\n    enable_api = True\n", "enable_api") is True
    assert Command  # scan wiring exercised by the orphan tests below


def test_doctor_scans_management_commands_without_flagging_the_seed_example():
    """AST removed the need to skip `management/`, so it is scanned again.

    The exclusion existed only to dodge the runbook seed command, which embeds
    an `enable_api = True` example in its markdown content. Skipping the whole
    directory also hid genuine opt-ins defined there — a gap `mcp_doctor` never
    had. Both halves are asserted: the directory is in scope, and the seed
    command is still not reported.
    """
    from pathlib import Path

    from apps.api.management.commands.api_doctor import _is_scannable

    seed = (
        Path(__file__).resolve().parents[3]
        / "apps/runbook/management/commands/seed_platform_runbook.py"
    )

    # Half 1 — management/ is genuinely in scope now (this fails if the
    # directory exclusion is reinstated).
    assert _is_scannable(seed) is True
    assert _is_scannable(Path("apps/foo/management/commands/anything.py")) is True
    # …while the exclusions that remain are the ones that can't hold a live opt-in.
    assert _is_scannable(Path("apps/foo/migrations/0001_initial.py")) is False
    assert _is_scannable(Path("apps/smallstack/tests/test_bulk_ops.py")) is False

    # Half 2 — and being in scope, the seed command is still not reported,
    # because AST can tell its markdown example from a class attribute.
    if seed.exists():
        source = seed.read_text(encoding="utf-8")
        assert "enable_api = True" in source  # the substring IS there…
        assert has_enable_classvar(source, "enable_api") is False  # …but not as a class attr

    from apps.api.management.commands.api_doctor import Command

    scanned = [str(p) for p, _display in Command()._scan_for_enable_api_optins()]
    assert not any("seed_platform_runbook" in p for p in scanned)


def test_doctor_check_only_exits_zero_when_all_pass():
    """--check-only does NOT exit when every check passes."""
    _run(["--no-self-test", "--check-only"])  # no SystemExit raised


def test_doctor_check_only_exits_nonzero_on_fail(monkeypatch):
    """--check-only must SystemExit(1) when any check FAILs."""
    from apps.api.management.commands.api_doctor import Command

    def _inject_fail(self, report):
        report.append({"name": "Injected", "status": "FAIL", "detail": "forced failure"})

    monkeypatch.setattr(Command, "_check_dependencies", _inject_fail)
    with pytest.raises(SystemExit) as exc:
        _run(["--no-self-test", "--check-only"])
    assert exc.value.code == 1
