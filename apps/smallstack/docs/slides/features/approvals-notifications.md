# Approvals & notifications

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Human-in-the-loop for your code — and for AI agents.

- **`@approval_kind` + `request_approval()`** — any app or MCP agent files a request
- **Decision console** at `/smallstack/approvals/requests/`, or the `{% approval_card %}` embed in your own page
- **React your way** — per-kind callback, signal, webhook event, or polling
- **Notifications** — `notify()` with a topbar bell, unread badge and inbox; approvals fan out to it and to branded email by default

</div>
<div class="col" markdown="1">

```python
@approval_kind("refund", label="Issue a refund")
def on_refund_decided(request, decision):
    if decision.approved:
        issue_refund(request.payload["order_id"])

request_approval(
    "refund",
    payload={"order_id": order.pk, "amount": 120},
    requested_by=agent_user,
)
```

</div>
</div>
