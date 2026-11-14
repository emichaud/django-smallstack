"""Django 6.1 MAILERS migration — config shape + no deprecation regressions."""

from __future__ import annotations

import pytest

from config.settings._email import (
    CONSOLE_BACKEND,
    SMTP_BACKEND,
    build_mailers,
)


def test_console_mailer_carries_no_options():
    mailers = build_mailers(CONSOLE_BACKEND)
    default = mailers["default"]
    # Console/file backends must not receive smtp kwargs (6.1 warns on unknowns).
    if default["BACKEND"].endswith("console.EmailBackend"):
        assert default["OPTIONS"] == {}


def test_smtp_mailer_maps_env_to_connection_options():
    mailers = build_mailers(SMTP_BACKEND)
    default = mailers["default"]
    if not default["BACKEND"].endswith("smtp.EmailBackend"):
        pytest.skip("EMAIL_BACKEND env overrides the smtp default in this environment")
    # OPTIONS keys map directly to smtp.EmailBackend.__init__ parameters.
    assert {"host", "port", "username", "password", "use_tls", "use_ssl"} <= set(default["OPTIONS"])
    assert isinstance(default["OPTIONS"]["port"], int)


def test_test_settings_use_locmem_mailer(settings):
    assert "locmem" in settings.MAILERS["default"]["BACKEND"]


def test_send_mail_emits_no_removed_in_django70_warning(recwarn):
    """Guards against reintroducing fail_silently / connection= on send paths."""
    from django.core import mail

    mail.outbox.clear()
    mail.send_mail("subject", "body", "from@example.com", ["to@example.com"])
    assert len(mail.outbox) == 1
    removed = [w for w in recwarn.list if type(w.message).__name__.startswith("RemovedInDjango")]
    assert not removed, [str(w.message) for w in removed]


def test_smtp_mailer_times_out_by_default(monkeypatch):
    """No EMAIL_TIMEOUT must still mean a bounded socket, never "wait forever"."""
    monkeypatch.setenv("EMAIL_BACKEND", SMTP_BACKEND)
    monkeypatch.delenv("EMAIL_TIMEOUT", raising=False)
    assert build_mailers(SMTP_BACKEND)["default"]["OPTIONS"]["timeout"] == 10


def test_smtp_mailer_timeout_zero_turns_it_off(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", SMTP_BACKEND)
    monkeypatch.setenv("EMAIL_TIMEOUT", "0")
    assert "timeout" not in build_mailers(SMTP_BACKEND)["default"]["OPTIONS"]
