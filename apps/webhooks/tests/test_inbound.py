"""Inbound receiver view: signature verify, receipt logging, handler dispatch.

Tasks run immediately in tests (ImmediateBackend), so dispatch_incoming runs the
registered handler synchronously during the POST — letting us assert PROCESSED.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.webhooks import registry, services
from apps.webhooks.models import WebhookReceipt, WebhookReceiver

pytestmark = pytest.mark.django_db

HANDLED: list = []


@pytest.fixture(autouse=True)
def clean_handlers():
    registry.clear_handlers_for_tests()
    HANDLED.clear()
    yield
    registry.clear_handlers_for_tests()
    HANDLED.clear()


@pytest.fixture
def receiver():
    return WebhookReceiver.objects.create(name="Stripe", slug="stripe", secret="shh")


def _post(client, slug, body: bytes, sig: str | None):
    headers = {}
    if sig is not None:
        # The receiver default is services.SIGNATURE_HEADER; the lookup is
        # case-insensitive (F-06).
        headers[services.SIGNATURE_HEADER] = sig
    return client.post(
        f"/webhooks/in/{slug}/",
        data=body,
        content_type="application/json",
        headers=headers,
    )


def test_valid_signature_accepts_and_dispatches(receiver):
    @registry.webhook_handler("stripe")
    def handle(receipt):
        HANDLED.append(receipt.json())

    body = json.dumps({"type": "charge.succeeded"}).encode()
    sig = services.sign("shh", body)
    resp = _post(Client(), "stripe", body, sig)

    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get()
    assert receipt.verified is True
    assert receipt.status == WebhookReceipt.Status.PROCESSED
    assert HANDLED == [{"type": "charge.succeeded"}]
    receiver.refresh_from_db()
    assert receiver.total_received == 1


def test_invalid_signature_rejected(receiver):
    resp = _post(Client(), "stripe", b'{"x":1}', "sha256=bad")
    assert resp.status_code == 401
    receipt = WebhookReceipt.objects.get()
    assert receipt.status == WebhookReceipt.Status.REJECTED
    assert receipt.verified is False


def test_unknown_receiver_404():
    resp = _post(Client(), "nope", b"{}", None)
    assert resp.status_code == 404
    assert WebhookReceipt.objects.count() == 0


def test_disabled_receiver_404(receiver):
    receiver.enabled = False
    receiver.save()
    body = b"{}"
    resp = _post(Client(), "stripe", body, services.sign("shh", body))
    assert resp.status_code == 404


def test_missing_handler_marks_failed(receiver):
    # No handler registered for "stripe".
    body = b"{}"
    resp = _post(Client(), "stripe", body, services.sign("shh", body))
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get()
    assert receipt.status == WebhookReceipt.Status.FAILED
    assert "no handler" in receipt.error


def test_require_signature_off_accepts_unsigned(receiver):
    receiver.require_signature = False
    receiver.save()

    @registry.webhook_handler("stripe")
    def handle(receipt):
        HANDLED.append("ran")

    resp = _post(Client(), "stripe", b"{}", None)
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get()
    assert receipt.verified is False
    assert receipt.status == WebhookReceipt.Status.PROCESSED


# --- public-route hardening (audit 2026-09-13, C6) ---------------------------


def test_rejected_receipt_keeps_an_excerpt_and_digest_not_the_body(receiver):
    body = b'{"pad":"' + b"x" * 50_000 + b'"}'
    assert _post(Client(), "stripe", body, "sha256=bad").status_code == 401
    receipt = WebhookReceipt.objects.get()
    assert len(receipt.body) <= 1024
    assert "sha256" in receipt.error


def test_rejections_stop_being_recorded_after_the_per_minute_cap(receiver, settings):
    settings.SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE = 3
    for _ in range(6):
        assert _post(Client(), "stripe", b"{}", "sha256=bad").status_code == 401
    assert WebhookReceipt.objects.count() == 3


def test_oversized_body_is_refused_before_anything_is_stored(receiver, settings):
    settings.SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES = 100
    body = b"{" + b" " * 200 + b"}"
    assert _post(Client(), "stripe", body, services.sign("shh", body)).status_code == 413
    assert WebhookReceipt.objects.count() == 0


def test_prune_webhook_receipts_drops_old_rows(receiver):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    old = WebhookReceipt.objects.create(receiver=receiver, body="old")
    WebhookReceipt.objects.filter(pk=old.pk).update(received_at=timezone.now() - timedelta(days=40))
    new = WebhookReceipt.objects.create(receiver=receiver, body="new")
    call_command("prune_webhook_receipts", "--keep-days", "30", stdout=__import__("io").StringIO())
    assert list(WebhookReceipt.objects.values_list("pk", flat=True)) == [new.pk]


# --- F-06: a SmallStack↔SmallStack pairing verifies out of the box -----------


def test_default_signature_header_matches_what_smallstack_sends():
    """The model default used to be "X-Signature" while our own sender emits
    "X-SmallStack-Signature", so a receiver created with defaults 401'd every
    delivery from a SmallStack endpoint."""
    r = WebhookReceiver.objects.create(name="paired", slug="paired", secret="shh")
    assert r.signature_header == services.SIGNATURE_HEADER


@pytest.mark.parametrize(
    "spelling",
    ["X-SmallStack-Signature", "X-Smallstack-Signature", "x-smallstack-signature"],
)
def test_signature_header_lookup_is_case_insensitive(receiver, spelling):
    """HTTP header names are case-insensitive; `dict(request.headers)` wasn't.

    Configuring the documented "X-SmallStack-Signature" spelling failed while an
    undocumented "X-Smallstack-Signature" worked, because the plain-dict copy
    froze Django's own canonicalisation.
    """
    receiver.signature_header = spelling
    receiver.save(update_fields=["signature_header"])

    @registry.webhook_handler("stripe")
    def handle(receipt):
        pass

    body = json.dumps({"type": "charge.succeeded"}).encode()
    sig = services.sign("shh", body)
    for sent_as in ("X-SmallStack-Signature", "x-smallstack-signature"):
        resp = Client().post(
            "/webhooks/in/stripe/",
            data=body,
            content_type="application/json",
            headers={sent_as: sig},
        )
        assert resp.status_code == 202, (spelling, sent_as, resp.content)


def test_third_party_verifier_still_sees_its_own_header_casing(receiver):
    """The case-insensitive mapping must not break verifiers written against a
    provider's own spelling (e.g. "Stripe-Signature")."""
    seen = {}

    from apps.webhooks.hooks import webhook_verifier

    @webhook_verifier("peek")
    def peek(body, headers, rec):
        seen["exact"] = headers.get("Stripe-Signature")
        seen["lower"] = headers.get("stripe-signature")
        return True

    receiver.verifier = "peek"
    receiver.save(update_fields=["verifier"])

    @registry.webhook_handler("stripe")
    def handle(receipt):
        pass

    Client().post(
        "/webhooks/in/stripe/",
        data=b"{}",
        content_type="application/json",
        headers={"Stripe-Signature": "t=1,v1=abc"},
    )
    assert seen["exact"] == "t=1,v1=abc"
    assert seen["lower"] == "t=1,v1=abc"


def test_pairing_warns_when_the_target_is_a_blocked_loopback_address(db):
    """The SSRF guard is correct; its silence was not. Pairing two instances on
    one box is the first thing anyone tries, and the block only surfaced in a
    failed delivery's error field."""
    result = services.pair_smallstack(
        target_url="http://127.0.0.1:8065/webhooks/in/peer/", one_way=True
    )
    assert result["warnings"]
    assert "BLOCKED" in result["warnings"][0]
    assert "SMALLSTACK_WEBHOOK_ALLOW_PRIVATE" in result["warnings"][0]


def test_pairing_to_a_public_target_warns_about_nothing(db, settings):
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = True
    result = services.pair_smallstack(
        target_url="http://127.0.0.1:8065/webhooks/in/peer2/", one_way=True
    )
    assert result["warnings"] == []


@pytest.mark.parametrize("one_way", [True, False], ids=["one-way", "two-way"])
def test_pair_command_prints_the_blocked_target_warning_in_both_shapes(db, one_way):
    """The two tests above prove the SERVICE returns a warning; this proves the
    COMMAND prints it. That gap is where F-39 #5 lived: the one-way branch
    `return`ed before the warning loop, so `pair --one-way` was silent while
    still carrying the warning in --json — and --one-way is precisely what the
    docs recommend for the loopback target the warning exists for.
    """
    from io import StringIO

    from django.core.management import call_command

    err = StringIO()
    argv = [
        "webhook",
        "pair",
        "--target",
        "http://127.0.0.1:8065/webhooks/in/peer-cli/",
        "--slug",
        f"peer-cli-{'ow' if one_way else 'tw'}",
    ]
    if one_way:
        argv.append("--one-way")
    call_command(*argv, stdout=StringIO(), stderr=err)

    assert "BLOCKED" in err.getvalue(), (
        f"the blocked-target warning never reached stderr (one_way={one_way})"
    )
    assert "SMALLSTACK_WEBHOOK_ALLOW_PRIVATE" in err.getvalue()


# --- F-37: the verifier's headers argument is still a mutable dict -----------
#
# F-06's fix swapped `dict(request.headers)` for Django's CaseInsensitiveMapping,
# which is IMMUTABLE. The seam had been documented as `dict[str, str]` from the
# start, so a third-party verifier doing the ordinary
# `headers.pop("X-Smallstack-Signature", "")` began raising AttributeError
# *inside* the verifier. The view's bare `except Exception` swallowed it, and a
# perfectly correct credential came back as a bare `401 invalid signature` with
# nothing in the log — a silent, undiagnosable break in a public contract.


def _mutating_verifier_receiver(name, fn):
    from apps.webhooks.hooks import webhook_verifier

    webhook_verifier(name)(fn)
    rec = WebhookReceiver.objects.create(
        name=name, slug=name, secret="shh", verifier=name, require_signature=True
    )
    return rec


def test_a_mutating_verifier_still_verifies_a_correct_signature():
    """The reported repro, with the credential CORRECT. Must be 202, not 401."""

    def popping(body, headers, rec):
        # The documented `dict` contract: take the signature out of the map.
        provided = headers.pop(services.SIGNATURE_HEADER, "")
        return bool(provided) and provided == services.sign(rec.secret, body)

    _mutating_verifier_receiver("mutating", popping)

    @registry.webhook_handler("mutating")
    def handle(receipt):
        HANDLED.append(receipt.pk)

    body = json.dumps({"ok": True}).encode()
    resp = _post(Client(), "mutating", body, services.sign("shh", body))
    assert resp.status_code == 202, (
        f"a verifier that mutates its headers dict 401s on a GOOD signature: {resp.content}"
    )


def test_a_mutating_verifier_still_rejects_a_wrong_signature():
    """Negative control — restoring mutability must not make the gate permissive."""

    def popping(body, headers, rec):
        provided = headers.pop(services.SIGNATURE_HEADER, "")
        return bool(provided) and provided == services.sign(rec.secret, body)

    _mutating_verifier_receiver("mutating2", popping)
    body = json.dumps({"ok": True}).encode()
    assert _post(Client(), "mutating2", body, "deadbeef").status_code == 401
    assert _post(Client(), "mutating2", body, None).status_code == 401


def test_every_dict_operation_the_old_contract_allowed_still_works():
    """Enumerate the mutations rather than trusting one of them."""
    ok = {}

    def exercises(body, headers, rec):
        assert isinstance(headers, dict), "the argument is no longer a dict"
        headers["X-Added"] = "1"
        headers.setdefault("X-Default", "2")
        headers.update({"X-Updated": "3"})
        # Each mutation must ALSO be exercised against a key that already exists
        # in a different casing — the collision path. Asserting only on a
        # brand-new key is how F-48 shipped: `update()` never routed through
        # __setitem__, so a differently-cased key shadowed instead of replacing,
        # and this test passed anyway because "X-Updated" existed in no casing.
        headers["x-added"] = "1b"  # __setitem__ collision
        headers.setdefault("x-default", "2b")  # setdefault collision (must NOT overwrite)
        headers.update({"x-updated": "3b"})  # update collision (MUST overwrite)
        popped = headers.pop(services.SIGNATURE_HEADER, "")
        del headers["x-added"]  # __delitem__ via the other casing
        ok.update(
            {
                "is_dict": True,
                "default": headers["X-Default"],
                "updated": headers["X-Updated"],
                "popped": bool(popped),
                "deleted": "X-Added" not in headers,
                # One key each, not two: the wire spelling is kept and the value
                # replaced. `dict.update` writing straight to C storage would
                # make these 2/2 and leave "updated" reading back the stale "3".
                "updated_keys": sum(1 for k in headers if k.lower() == "x-updated"),
                "default_keys": sum(1 for k in headers if k.lower() == "x-default"),
            }
        )
        return popped == services.sign(rec.secret, body)

    _mutating_verifier_receiver("mutating3", exercises)
    body = b"{}"
    resp = _post(Client(), "mutating3", body, services.sign("shh", body))
    assert resp.status_code == 202, resp.content
    assert ok == {
        "is_dict": True,
        "default": "2",  # setdefault must not clobber an existing differently-cased key
        "updated": "3b",  # update MUST replace it, readable via the original spelling
        "popped": True,
        "deleted": True,
        "updated_keys": 1,
        "default_keys": 1,
    }


def test_constructor_folds_colliding_cases():
    """The same defect one constructor over (F-48): building from a mapping that
    already contains two spellings must collapse to one entry, not keep both."""
    from apps.webhooks.hooks import CaseInsensitiveDict

    d = CaseInsensitiveDict({"X-Foo": "a", "x-foo": "b"})
    assert len(d) == 1
    assert d["X-Foo"] == d["x-foo"] == "b"

    # And via every update() spelling, each against an existing casing.
    for mutate in (
        lambda h: h.update({"x-foo": "z"}),
        lambda h: h.update([("x-foo", "z")]),
        lambda h: h.update(CaseInsensitiveDict({"x-foo": "z"})),
    ):
        h = CaseInsensitiveDict({"X-Foo": "a"})
        mutate(h)
        assert len(h) == 1, f"{mutate} shadowed instead of replacing: {dict(h)}"
        assert h["X-Foo"] == "z"
        assert list(h) == ["X-Foo"], "the original wire spelling must be preserved"


def test_case_insensitivity_survives_mutability():
    """Both halves of the contract at once (F-06 + F-37), all four spellings."""
    seen = {}

    def peek(body, headers, rec):
        seen["exact"] = headers.get(services.SIGNATURE_HEADER)
        seen["lower"] = headers.get(services.SIGNATURE_HEADER.lower())
        seen["upper"] = headers.get(services.SIGNATURE_HEADER.upper())
        seen["in"] = services.SIGNATURE_HEADER.lower() in headers
        # …and a case-different pop finds the same entry.
        seen["popped"] = headers.pop(services.SIGNATURE_HEADER.lower(), None)
        seen["gone_after_pop"] = headers.get(services.SIGNATURE_HEADER) is None
        return True

    _mutating_verifier_receiver("mutating4", peek)
    body = b"{}"
    sig = services.sign("shh", body)
    assert _post(Client(), "mutating4", body, sig).status_code == 202
    assert seen == {
        "exact": sig,
        "lower": sig,
        "upper": sig,
        "in": True,
        "popped": sig,
        "gone_after_pop": True,
    }


def test_a_raising_verifier_fails_closed_AND_logs(caplog):
    """The diagnosability half: failing closed is right, failing silently is not."""
    import logging

    def explodes(body, headers, rec):
        raise RuntimeError("verifier is broken")

    _mutating_verifier_receiver("exploding", explodes)
    body = b"{}"
    with caplog.at_level(logging.ERROR, logger="smallstack.webhooks"):
        resp = _post(Client(), "exploding", body, services.sign("shh", body))

    assert resp.status_code == 401  # still fails closed
    messages = [r.getMessage() for r in caplog.records]
    assert any("verifier" in m and "UNVERIFIED" in m for m in messages), messages
    # The traceback has to be there or it is not a five-minute diagnosis.
    assert any(r.exc_info for r in caplog.records)


def test_the_case_insensitive_dict_in_isolation():
    """Unit-level, so a failure points at the data structure not the view."""
    from apps.webhooks.hooks import CaseInsensitiveDict

    d = CaseInsensitiveDict({"X-Sig": "abc", "Content-Type": "application/json"})
    assert isinstance(d, dict)
    assert d["x-sig"] == d["X-SIG"] == d["X-Sig"] == "abc"
    assert "x-sig" in d and "X-SIG" in d and "nope" not in d
    assert d.get("x-sig") == "abc" and d.get("nope", "d") == "d"
    # Mutation keeps the original casing visible on iteration.
    assert set(d) == {"X-Sig", "Content-Type"}
    d["x-sig"] = "zzz"
    assert set(d) == {"X-Sig", "Content-Type"}, "a case-variant write duplicated the key"
    assert d["X-Sig"] == "zzz"
    assert d.pop("X-SIG") == "zzz"
    assert "x-sig" not in d
    with pytest.raises(KeyError):
        d.pop("x-sig")
    assert d.setdefault("new-key", "v") == "v"
    assert d.setdefault("NEW-KEY", "other") == "v"
    del d["CONTENT-TYPE"]
    assert set(d) == {"new-key"}
    assert isinstance(d.copy(), CaseInsensitiveDict)


# --- F-40: an empty secret must never verify --------------------------------


def test_empty_secret_never_verifies_even_with_a_correctly_computed_hmac(db):
    """`require_signature=True` with `secret=''` read as "locked down" and was
    in fact "anyone who knows the scheme": HMAC keys happily on b"", so a sender
    computing the digest with the empty key passed. `verify()` guarded
    `if not provided` but never `if not secret`."""
    rec = WebhookReceiver.objects.create(
        name="empty-secret", slug="empty-secret", secret="", require_signature=True
    )
    body = b'{"hello": true}'

    # The attack: sign with the empty secret the receiver is holding.
    forged = services.sign("", body)
    assert _post(Client(), rec.slug, body, forged).status_code == 401

    # Controls: no signature is still 401, and the same receiver with a real
    # secret still accepts a correctly-signed delivery.
    assert _post(Client(), rec.slug, body, None).status_code == 401
    WebhookReceiver.objects.filter(pk=rec.pk).update(secret="shh")
    rec.refresh_from_db()
    assert _post(Client(), rec.slug, body, services.sign("shh", body)).status_code == 202

    # And the unsigned mode is unchanged — documented fail-open.
    WebhookReceiver.objects.filter(pk=rec.pk).update(secret="", require_signature=False)
    assert _post(Client(), rec.slug, body, forged).status_code == 202


def test_validation_already_refuses_a_blank_secret(db):
    """Why `verify()` is the fix and not a model `clean()`.

    `secret` is `blank=False`, so every validated path (forms, REST, MCP, `sc`)
    already refuses a blank secret — a `clean()` override for this would be
    shadowed by field validation and never run. The reachable route to the state
    is a raw ORM write, which skips validation entirely, so the guard has to live
    where the signature is actually checked.
    """
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc:
        WebhookReceiver(
            name="no-secret", slug="no-secret", secret="", require_signature=True
        ).full_clean()
    assert "secret" in exc.value.message_dict

    # …and the ORM write that bypasses it succeeds, which is the case verify() covers.
    rec = WebhookReceiver.objects.create(
        name="orm-blank", slug="orm-blank", secret="", require_signature=True
    )
    assert rec.secret == ""
