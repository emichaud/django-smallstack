# Webhooks

<div class="two-col" markdown="1">
<div class="col" markdown="1">

The seam between your systems — both directions, signed, replayable.

- **Outbound** — `enable_webhooks = True` emits signed `created / updated / deleted` events with retries, `Retry-After` and dead-letter replay
- **Inbound** — `@webhook_handler` receivers; provider signatures via `@webhook_verifier`, handshakes via `@webhook_challenge`
- **SmallStack ↔ SmallStack pairing** — `sc webhook pair`, loop-safe, stable `event_id` dedupe
- **Collect external feeds** — `register_feed_source` pulls an RSS/Atom source into a model on a schedule, for the systems that only speak RSS

</div>
<div class="col" markdown="1">

```python
@webhook_handler("stripe", verifier="stripe")
def on_stripe_event(event):
    if event.type == "invoice.paid":
        mark_paid(event.data["object"]["id"])

@webhook_transform(Ticket)
def ticket_payload(ticket, event):
    return {"id": ticket.pk, "status": ticket.status}
```

</div>
</div>
