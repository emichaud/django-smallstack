---
title: Webhooks
description: Signed outbound delivery on model change + verified inbound receivers, with four extension seams for Zapier/n8n/Stripe/Slack
---

# Webhooks

> **Building this?** Read the agent-facing skill first: [`docs/skills/webhooks.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/webhooks.md). It's prescriptive (what to do); this page is the reference (why + worked examples).

Every other SmallStack surface — the CRUDView admin, REST, MCP, the `sc` CLI — is **inbound**: something calls into your app. Webhooks add the **outbound** half (your app POSTs out when data changes) and a matching **inbound** receiver (external systems POST in to trigger a handler). It's a solid, foundational engine that reliably **signs, delivers, retries, dead-letters, and monitors** — specific integrations are built on top of it, not forked into it.

Admin lives at `/smallstack/webhooks/`.

## Outbound — notify other systems when data changes

Opt a model in with one flag, exactly like `enable_search`:

```python
# apps/support/views.py
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_webhooks = True
    webhook_events = ["created", "updated", "deleted"]  # optional; this is the default
```

A create/update/delete of `Ticket` through **any** surface — HTML, REST, MCP, `sc`, or the raw ORM — now emits a `support.ticket.created` event. The payload reuses the same `serialize()` the REST API emits, wrapped in an envelope with a stable **`event_id`** (dedupe on it, survives replay), an **`origin`** (loop-guard), and an absolute **`resource.url`** so a consumer can act on the record without reconstructing the path.

Register destinations as data — in the UI at `/smallstack/webhooks/endpoints/`, via REST, via the `create_webhook` MCP tool, or the CLI (`sc new webhook …`). Deliveries are signed, retried with `Retry-After`, and dead-lettered; failed batches can be **bulk-replayed**.

## Choosing which events an endpoint receives

An endpoint's **event filter** decides which events it gets. In the endpoint form and the pairing panel you pick events from a **checkbox list of everything this instance can emit**, each annotated in plain English ("when a Ticket is created") — no need to know the `app.model.action` naming to subscribe safely.

Under the hood each selection is an fnmatch pattern: event names are `app.model.action` (`support.ticket.created`), and `*` wildcards any part — `*.created` means every model's creates, `support.*` a whole app, `*` everything. Hand-written **custom patterns** live behind a collapsed *Advanced* disclosure (it opens automatically when patterns were set programmatically, so nothing configured over REST or the CLI is ever hidden). A **?** help popup next to the box explains the pattern grammar in place.

Patterns are **validated on every surface** — the web form, REST, MCP, and the CLI all run the same check — so a malformed pattern (spaces, quotes, a pasted JSON fragment) is rejected as a form error instead of being saved as a filter that silently never matches. A well-formed pattern that matches nothing *currently* emitted is allowed (it may target a future or custom event), but the UI warns you about it.

## Inbound — receive & verify events from others

Register a `WebhookReceiver` and a `@webhook_handler` to accept events (Stripe, GitHub, an internal service). Provider signatures verify at a `@webhook_verifier` seam and handshakes at a `@webhook_challenge` seam, so a receiver validates authenticity before your handler runs.

## The four extension seams

Shaping a payload for a picky destination or verifying a bespoke signature happens at a **seam**, not by forking core:

| Seam | Purpose |
|---|---|
| `@webhook_transform` | reshape the outbound payload for a specific destination |
| `@webhook_auth` | attach destination-specific auth to outbound requests |
| `@webhook_verifier` | verify an inbound provider's signature |
| `@webhook_challenge` | answer an inbound subscription handshake |

These seams are what make **Zapier, n8n, Stripe, Slack, and Azure Event Grid** small plug-ins rather than core changes. A reference Event Grid adapter ships using all four with zero core edits.

## SmallStack ↔ SmallStack pairing

Two SmallStack apps pair in one step (`sc webhook pair`), loop-safe by default, with `event_id` dedupe and a round-tripping envelope — the foundation for federating a fleet of small services.

## Health

Run `manage.py webhook_doctor` (or `sc doctor`) to health-check endpoints, receivers, unresolved origins, and the dead-letter queue.

## Related

- [REST API](/smallstack/help/smallstack/explorer-rest-api/) — the `serialize()` shape that outbound payloads reuse
- [Custom API Endpoints](/smallstack/help/smallstack/custom-api-endpoints/) — non-CRUD endpoints
- [MCP](/smallstack/help/smallstack/mcp/) — the `create_webhook` tool and the inbound/outbound distinction
