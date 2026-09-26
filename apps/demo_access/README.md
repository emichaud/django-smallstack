# demo_access — Scenario C: REST-first filing + webhooks

A remote client (SPA, service, CI job) files an elevated-access request over
REST, a human decides it, and a remote system reacts through a webhook. Built to
stress-test the *API* consumer of `apps/approvals/`: the whole loop with nothing
but a Bearer token.

**Status:** Demo / scenario app. Safe to delete in a downstream project.

## What it demonstrates

| Claim under test | Where |
|---|---|
| A time-bound grant armed only on approval, disarmed on everything else | `approvals.on_access_decision` |
| `notify=[...]` adds an extra email recipient to the fan-out | `approvals.AUDIT_MAILBOX` |
| A remote client can file an approval **pointing at a business row** | `api.api_file_access_request` (see the caveat) |
| Token tiers: a readonly token cannot file | `api_view` enforces it structurally |
| An unknown kind is a 400 that lists the registered kinds | `services.request_approval(require_known_kind=True)` |
| The outbound `approvalrequest.created` / `.updated` fan-out is observable | `enable_webhooks` + `webhook_handlers.py` |
| The `.updated` payload carries `data.status` for every transition | harness checks C19–C21 |
| An inbound receiver can turn deliveries into inspectable rows | `WebhookEcho` |

## The models

`AccessRequest`: `resource` (`dataset:payroll`), `scope` (read/write/admin),
`reason`, `duration_hours`, `state` (pending → granted | rejected | expired |
revoked | canceled), `approval`, `granted_until`, `requester`.

`granted_until` is the armed thing: `now + duration_hours` on approval, `None` on
every other terminal status.

`WebhookEcho`: one row per approval webhook this instance delivered to itself —
the receiver's inbox, so the fan-out can be read without parsing raw receipts.

## The kind

`access.grant` — `default_expires_in=timedelta(hours=12)`,
`notify=["access-audit@example.com"]`. The context card resolves from the kind
key (`approvals/kinds/access-grant.html`).

## Users and tokens

| Login | Staff? | Role here |
|---|---|---|
| `svcbot` / `svcbot` | yes | the REST client: files, polls, holds the tokens |
| `admin` / `admin` | superuser | decides over REST |
| `opslead` / `opslead` | yes | another eligible decider |
| `analyst` / `analyst` | no | the ineligible-decider control |

`manage.py seed_approval_scenarios` mints and prints:

* `demo: svcbot write` (access level `staff`) — file + poll + decide
* `demo: svcbot readonly` (access level `readonly`) — the refused-write control
* `demo: admin` (access level `staff`) — the decider

> `svcbot` is **staff** on purpose: the approvals CRUD/REST surface is
> staff-gated, so a non-staff service account can file but cannot poll. Same
> limitation as Scenario B — see the caveat below.

## Endpoints

| Call | Who |
|---|---|
| `POST /api/demo/access/requests/file/` | any write token — files the row **and** an approval pointing at it |
| `GET /api/demo/access/requests/` | staff token — the business rows |
| `POST /smallstack/api/approvals/requests/create/` | any write token — the generic filing endpoint (no target) |
| `GET /smallstack/api/approvals/requests/?status=pending` | staff token — the queue |
| `POST /smallstack/api/approvals/requests/<id>/decide/` | any **eligible** user, staff or not |
| `GET /smallstack/notifications/api/` · `POST …/mark-read/` | the token's own user |
| `/demo/access/requests/` · `/demo/access/webhook-echoes/` | staff web |

## The local webhook loop

`seed_approval_scenarios` wires this instance to itself so the fan-out is
observable end to end:

* an outbound `WebhookEndpoint` filtered on
  `smallstack_approvals.approvalrequest.*` → `http://127.0.0.1:8065/webhooks/in/access-grants/`
* an inbound `WebhookReceiver` with slug `access-grants`, whose
  `@webhook_handler` writes a `WebhookEcho` row.

Two things are deliberate, and both are sharp edges worth knowing:

1. `signature_header` is set to **`X-Smallstack-Signature`**. SmallStack signs
   outbound deliveries with `X-SmallStack-Signature`, but WSGI header
   normalization lowercases the inner capitals before the default verifier looks
   the header up — and the model default is `X-Signature`. Leave it at the
   default and every self-delivery is rejected 401.
2. The receiver is **not** created via `sc webhook pair`, because pairing sets
   `ignore_origin` to our own origin, which would drop exactly the
   self-originated events this demo wants to observe.

Delivery needs a worker (`uv run python manage.py db_worker`) or
`manage.py run_due_deliveries`; the handler itself is enqueued too. The harness
sidesteps both by POSTing a signed copy of the real payload to the receiver and
running `dispatch_incoming` inline.

## How to drive it

```bash
uv run python manage.py create_dev_superuser
uv run python manage.py seed_approval_scenarios      # prints the tokens
uv run python manage.py approval_scenario c --check   # 32 assertions, no server needed
```

By hand against `make run PORT=8065`:

```bash
WRITE=<demo: svcbot write key>; DECIDE=<demo: admin key>
# 1. file
curl -s localhost:8065/api/demo/access/requests/file/ -H "Authorization: Bearer $WRITE" \
  -H 'Content-Type: application/json' \
  -d '{"resource":"dataset:payroll","scope":"read","duration_hours":6,"reason":"QBR"}'
# → {"access_request_id":1,"approval_id":9,"poll":"…","decide":"…"}
# 2. poll
curl -s localhost:8065/smallstack/api/approvals/requests/9/ -H "Authorization: Bearer $WRITE"
# 3. decide
curl -s localhost:8065/smallstack/api/approvals/requests/9/decide/ -H "Authorization: Bearer $DECIDE" \
  -H 'Content-Type: application/json' -d '{"approved":true,"note":"6h granted"}'
# 4. the grant + the echo
curl -s localhost:8065/api/demo/access/requests/1/ -H "Authorization: Bearer $WRITE"
```

## Caveat: the generic filing endpoint cannot attach a target

`POST /smallstack/api/approvals/requests/create/` accepts only `kind`, `title`,
`description`, `context` and `expires_in_minutes` — there is no way to point the
new approval at a business object, even though `services.request_approval` takes
a `target=` and the console renders it. That is why `api.py` exists here. Harness
check **C03** is left FAILing to record the gap; see
`test_smallstack_frontends/docs/findings/2026-09-25-approvals-notifications.md`.
