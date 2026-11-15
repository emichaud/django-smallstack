"""The shipped gunicorn access log redacts one-time tokens (E-dec 6,
2026-11-14 access-control round).

G3-1 redacted reset and invite tokens from the activity log and the captured
logs, but the production server's own access line (``gunicorn.conf``, stdout,
read by ``kamal app logs`` and any log shipper) still printed
``GET /accounts/reset/MQ/<token>/``, and the referer of the next request
carried the same link. These tests load the real ``gunicorn.conf`` into
gunicorn's own ``Config``, build the logger class it names, write an access
line to a file and read it back.
"""

from __future__ import annotations

import datetime
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings
from gunicorn import util
from gunicorn.config import Config

CONF = Path(settings.BASE_DIR) / "gunicorn.conf"
TOKEN = "cz8k4f-0123456789abcdef0123456789abcdef"
RESET = f"/smallstack/accounts/reset/MQ/{TOKEN}/"
INVITE = f"/accounts/invite/Mg/{TOKEN}/"


def _shipped_config(tmp_path: Path) -> Config:
    cfg = Config()
    for key, value in runpy.run_path(str(CONF)).items():
        if key in cfg.settings:
            cfg.set(key, value)
    cfg.set("accesslog", str(tmp_path / "access.log"))
    cfg.set("errorlog", str(tmp_path / "error.log"))
    return cfg


def _access_line(tmp_path: Path, *, path: str, query: str = "", referer: str = "-") -> str:
    cfg = _shipped_config(tmp_path)
    logger = cfg.logger_class(cfg)
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": path + (f"?{query}" if query else ""),
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "203.0.113.9",
        "HTTP_REFERER": referer,
        "HTTP_USER_AGENT": "pytest",
    }
    resp = SimpleNamespace(status="200 OK", sent=12, headers=[])
    req = SimpleNamespace(headers=[("REFERER", referer)])
    logger.access(resp, req, environ, datetime.timedelta(seconds=0, microseconds=1500))
    for handler in logger.access_log.handlers:
        handler.flush()
    return (tmp_path / "access.log").read_text()


def test_the_shipped_config_names_the_redacting_logger(tmp_path):
    cfg = _shipped_config(tmp_path)
    from apps.smallstack.gunicorn_logging import RedactingLogger

    assert cfg.logger_class is RedactingLogger
    assert util.load_class(runpy.run_path(str(CONF))["logger_class"], section="gunicorn.loggers") is RedactingLogger


@pytest.mark.parametrize("path", [RESET, INVITE, f"/blog/unsubscribe/{TOKEN}/", f"/blog/subscribe/confirm/{TOKEN}/"])
def test_a_token_path_is_redacted_in_the_access_line(tmp_path, path):
    line = _access_line(tmp_path, path=path)
    assert TOKEN not in line
    assert "/***/" in line
    assert '"GET ' in line and " 200 " in line  # still a usable access line


def test_the_referer_is_redacted(tmp_path):
    line = _access_line(
        tmp_path, path="/smallstack/accounts/reset/MQ/set-password/", referer=f"https://example.com{RESET}"
    )
    assert TOKEN not in line
    assert "/smallstack/accounts/reset/MQ/set-password/" in line  # Django's placeholder isn't a secret


def test_a_credential_query_is_redacted_in_any_format(tmp_path):
    from apps.smallstack.gunicorn_logging import redact_atom

    assert redact_atom("q", f"token={TOKEN}&page=2") == "token=***&page=2"
    assert TOKEN not in redact_atom("r", f"GET /feed/blog.rss?token={TOKEN} HTTP/1.1")
    assert TOKEN not in redact_atom("{raw_uri}e", f"{RESET}?x=1")
    assert redact_atom("U", "/smallstack/") == "/smallstack/"
    assert redact_atom("B", 12) == 12


def test_guard_an_ordinary_path_is_unchanged(tmp_path):
    line = _access_line(tmp_path, path="/smallstack/activity/requests/")
    assert '"GET /smallstack/activity/requests/ HTTP/1.1" 200 12' in line
