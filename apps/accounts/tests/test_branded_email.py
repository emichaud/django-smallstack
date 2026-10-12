"""``send_branded_email`` — the bulk-send arguments.

The helper was transactional-only (one message, one fresh connection, no
header control). Bulk list mail needs three things it could not express, and
all three default to the previous behaviour so every existing caller is
unaffected:

  * ``headers``    — ``List-Unsubscribe`` / ``List-Unsubscribe-Post``, which
                     are what make RFC 8058 one-click unsubscribe work and
                     cannot be set any other way.
  * ``connection`` — reuse one SMTP connection across a batch instead of one
                     TCP+TLS handshake and one AUTH per message.
  * ``reply_to`` / ``from_email`` — per-publication sender identity.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.core import mail

from apps.accounts.emails import send_branded_email

# A bundled template with a .txt sibling and a tiny context, so these tests
# exercise the send path rather than any particular email's copy. No DB needed.
TEMPLATE = "email/login_code.html"
CONTEXT = {"code": "123456", "ttl_minutes": 10,
           "user": SimpleNamespace(get_username=lambda: "reader")}


class _RecordingConnection:
    """Stands in for an SMTP connection. ``EmailMessage.send()`` routes through
    ``self.connection`` when one is set, so capturing here proves the message
    never touched the default backend."""

    def __init__(self) -> None:
        self.sent: list = []
        self.opens = 0

    def open(self) -> bool:
        self.opens += 1
        return True

    def close(self) -> None:
        pass

    def send_messages(self, messages) -> int:
        self.sent.extend(messages)
        return len(messages)


def _send(**kwargs) -> _RecordingConnection:
    conn = _RecordingConnection()
    send_branded_email(
        subject="Hi",
        template=TEMPLATE,
        context=CONTEXT,
        to="reader@example.test",
        connection=conn,
        **kwargs,
    )
    return conn


def test_connection_is_used_instead_of_the_default_backend():
    mail.outbox.clear()
    conn = _send()
    assert len(conn.sent) == 1
    assert mail.outbox == [], "message leaked to the default backend"


def test_one_connection_serves_many_messages():
    """The point of the parameter: N messages, one connection object."""
    conn = _RecordingConnection()
    for i in range(5):
        send_branded_email(
            subject=f"Issue {i}",
            template=TEMPLATE,
            context=CONTEXT,
            to=f"r{i}@example.test",
            connection=conn,
        )
    assert len(conn.sent) == 5


def test_extra_headers_are_set():
    unsub = "https://example.test/blog/unsubscribe/tok/"
    conn = _send(
        headers={
            "List-Unsubscribe": f"<{unsub}>, <mailto:bye@example.test>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    )
    headers = conn.sent[0].extra_headers
    assert headers["List-Unsubscribe"].startswith(f"<{unsub}>")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_reply_to_accepts_a_string_or_a_list():
    assert _send(reply_to="editor@example.test").sent[0].reply_to == ["editor@example.test"]
    assert _send(reply_to=["a@example.test", "b@example.test"]).sent[0].reply_to == [
        "a@example.test",
        "b@example.test",
    ]


def test_from_email_override():
    msg = _send(from_email="Field Notes <notes@example.test>").sent[0]
    assert msg.from_email == "Field Notes <notes@example.test>"


def test_defaults_are_unchanged_when_the_new_args_are_omitted():
    """Back-compat guard: the pre-existing call shape must behave as before —
    default From, no Reply-To, no extra headers, delivered via the default
    backend, and still multipart with an HTML alternative."""
    mail.outbox.clear()
    sent = send_branded_email(
        subject="Welcome",
        template=TEMPLATE,
        context=CONTEXT,
        to="reader@example.test",
    )
    assert sent == 1
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["reader@example.test"]
    assert msg.reply_to == []
    assert msg.extra_headers == {}
    assert msg.from_email  # DEFAULT_FROM_EMAIL
    assert msg.alternatives and msg.alternatives[0][1] == "text/html"
