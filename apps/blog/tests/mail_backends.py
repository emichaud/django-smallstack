"""Test email backends.

The console and locmem backends **never raise**, so in development every send
looks perfectly healthy and the entire failure half of the pipeline — the
bounce classification, the retry budget, the suppression threshold — is
unexercised. These backends exist so those paths are actually tested.

They also count ``open()`` calls, which is how the "one connection per batch,
not per message" property is asserted: that difference is minutes versus hours
on a large send, and nothing else would notice if it regressed.
"""

from __future__ import annotations

import smtplib
from typing import Any

from django.core.mail.backends.base import BaseEmailBackend

# Module-level so a test can read them after the send without threading a
# reference through the service.
STATS: dict[str, Any] = {"opened": 0, "closed": 0, "sent": 0, "messages": []}


def reset() -> None:
    STATS.update({"opened": 0, "closed": 0, "sent": 0, "messages": []})


class CountingBackend(BaseEmailBackend):
    """Succeeds, and records how often a connection was opened."""

    def open(self) -> bool:
        STATS["opened"] += 1
        return True

    def close(self) -> None:
        STATS["closed"] += 1

    def send_messages(self, email_messages: Any) -> int:
        count = 0
        for message in email_messages:
            STATS["messages"].append(message)
            STATS["sent"] += 1
            count += 1
        return count


class HardBounceBackend(CountingBackend):
    """Every recipient is refused with a 5xx — a permanent failure."""

    def send_messages(self, email_messages: Any) -> int:
        recipients = {}
        for message in email_messages:
            for address in message.to:
                recipients[address] = (550, b"5.1.1 unknown user")
        raise smtplib.SMTPRecipientsRefused(recipients)


class SoftFailBackend(CountingBackend):
    """The connection drops — transient, and must NOT suppress the address."""

    def send_messages(self, email_messages: Any) -> int:
        raise smtplib.SMTPServerDisconnected("connection reset by peer")


class FailAfterBackend(CountingBackend):
    """Succeeds for the first ``limit`` messages, then dies.

    Simulates a worker killed mid-batch, which is what the claim/reap
    machinery exists for.
    """

    limit = 2

    def send_messages(self, email_messages: Any) -> int:
        if STATS["sent"] >= self.limit:
            raise RuntimeError("worker died")
        return super().send_messages(email_messages)
