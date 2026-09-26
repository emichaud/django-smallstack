# Skill: Webhooks (outbound + inbound)

Webhooks are the HTTP glue in the direction the rest of SmallStack doesn't cover.
Every built-in surface (CRUDView admin, REST, MCP, `sc`) is **inbound** — something
calls into the app. Webhooks add the **outbound** half (the app POSTs out when data
changes) and a matching **inbound** receiver (external systems POST in to trigger a
handler). Lives in `apps/webhooks/`.

SmallStack ships a *solid, foundational* webhook engine that specific integrations are
built **on top of**. Two things make it more than a raw POST-out:

1. **SmallStack↔SmallStack is first-class** — [one-step pairing](#smallstacksmallstack-first-class),
   loop-safe by default, dedupe-able on a stable `event_id`, envelope round-trips.
2. **It's extensible** — [four documented seams](#the-four-extension-seams) let a
   Zapier/n8n/Azure/AWS integration be a small plug-in, not a core fork.

> **Integration-platform framing (F-013).** Think of webhooks as *plumbing*: the engine
> reliably signs, delivers, retries, dead-letters, and monitors. Shaping a payload for a
> picky destination or verifying a provider's bespoke signature is done at a **seam**
> (below) — either in your own code or via a reference adapter — not by forking core.

## When to use which

| The user wants… | Use |
|---|---|
| "Notify Zapier / our other service when a `Ticket` changes" | **Outbound**: `enable_webhooks = True` on the CRUDView + register an endpoint |
| "Only fire on create, not update/delete" | Outbound: `webhook_events = ["created"]` on the CRUDView |
| "Stripe / GitHub should be able to POST events to us" | **Inbound**: a `WebhookReceiver` + a `@webhook_handler` |

## Outbound — 3 steps

### 1. Opt the model in (one line, like `enable_search`)

```python
# apps/support/views.py
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_webhooks = True
    # optional — default is all three:
    webhook_events = ["created", "updated", "deleted"]
```

That's it for the *source*. A create/update/delete of `Ticket` through **any** surface
(HTML, REST, MCP, `sc`, or raw ORM) now emits an event
`support.ticket.created` (`<app_label>.<model>.<action>`). The payload reuses the same
`serialize()` the REST API emits, wrapped in an envelope:

```json
{ "event": "support.ticket.created", "action": "created",
  "model": "support.ticket", "id": 42, "occurred_at": "...",
  "event_id": "5f3b…-uuid",                         // stable, survives replay (dedupe on it)
  "origin": "https://your-site.example.com",        // who sent it (loop-guard filter)
  "resource": { "type": "support.ticket", "id": 42,
                "url": "https://your-site.example.com/smallstack/api/support/tickets/42/" },
  "data": { "id": 42, "title": "...", ... } }
```

The `event_id`, `origin`, and `resource` keys were **added** in the foundation reshape
(the original keys are unchanged, so existing consumers keep working). `resource.url` is
**absolute** so a consumer can act on the record without reconstructing the path — set
`SMALLSTACK_WEBHOOK_ORIGIN` (or `SITE_URL`) so it's a real base URL rather than a hostname.
Outbound FK **names** (not just ids) appear when the CRUDView sets `api_expand_fields`.

### 2. Register an endpoint (the destination)

Endpoints are just data — create them in the UI at `/smallstack/webhooks/endpoints/`,
via REST (`POST /smallstack/api/webhooks/endpoints/`), MCP (`create_webhook`), or the CLI:

```bash
sc new webhook --name Zapier --target_url https://hooks.zapier.com/... \
   --event_filter '["support.ticket.*", "*.created"]' --user admin
```

`event_filter` holds fnmatch patterns (`[]` = inert). Event names are
`app.model.action` (e.g. `support.ticket.created`); `*` wildcards any part and
crosses dots, so `*.created` matches every model's creates and `support.*`
matches a whole app. **Patterns are shape-validated on every surface** (HTML
form, REST, MCP, CLI — all through the same form): dot-separated tokens of word
characters and fnmatch wildcards only. A malformed pattern (spaces, quotes, a
pasted JSON fragment) is a validation error, not a silently-never-matching
filter. A *well-formed* pattern matching nothing this instance currently emits
is accepted — it may target future or custom events — but the pairing UI warns
about it. In the web UI, `event_filter` renders as a checkbox picker built from
`services.available_events()` (each option annotated in plain English via
`services.describe_event_pattern()`), with custom patterns behind a collapsed
"advanced" disclosure that auto-expands whenever patterns were set
programmatically. JSON fields accept native JSON on
every surface (a real array in REST/MCP payloads, a quoted JSON string on the CLI).
Omitted fields use the model defaults — a new endpoint is **enabled** with an
auto-generated signing secret. Pass `--secret <value>` (or `"secret"` in REST/MCP
payloads) to set a known secret; the field is **write-only** — it is never returned by
any read, only by the staff-gated Reveal action on the endpoint detail page.

Every enabled endpoint whose `event_filter` matches gets one `WebhookDelivery`, POSTed
with an HMAC-SHA256 signature the receiver verifies:

```
X-SmallStack-Signature: sha256=<hex>   # HMAC(endpoint.secret, raw_body)
X-SmallStack-Event: support.ticket.created
X-SmallStack-Delivery: 123
```

### 3. Make sure the retry tick runs

Delivery failures retry with exponential backoff (`SMALLSTACK_WEBHOOK_BACKOFF`), driven
by a tick — **the framework has no automatic task retry, this is ours**. Pick exactly
one trigger per deployment (same choices as the scheduler). **The Docker image ships
`POST /webhooks/tick/` every minute in `scripts/smallstack-cron`**; wire one of the others
only if you don't deploy with that crontab:

- cron/systemd: `* * * * * python manage.py run_due_deliveries`
- localhost POST inside gunicorn: `POST /webhooks/tick/`
- fold `services.run_due_deliveries()` into your existing scheduler beat

Delivery honors a **`Retry-After`** header on a `429`/`503` (delta-seconds or HTTP-date),
overriding the backoff table for that attempt, clamped to `SMALLSTACK_WEBHOOK_MAX_BACKOFF`
(F-022) — so a real rate-limiter isn't hammered.

After N consecutive failures (`SMALLSTACK_WEBHOOK_AUTO_DISABLE_AFTER`) an endpoint
auto-disables. Replay a dead delivery from its detail page or the `replay_delivery` MCP
tool; replay **all** dead deliveries after an outage with the “Replay all dead” dashboard
action, `sc webhook replay --status dead`, or the `replay_dead_deliveries` MCP tool (each
reuses the original `event_id` so a consumer dedupes — F-023).

> **Delivery ordering / head-of-line (F-024).** Deliveries are **at-least-once** with a
> stable `X-SmallStack-Delivery` per attempt and a stable `X-SmallStack-Event-Id` per event
> (survives replay). One `db_worker` processes deliveries **serially**, so a slow/timing-out
> endpoint delays other pending deliveries behind it (up to `SMALLSTACK_WEBHOOK_TIMEOUT`
> each). The timeout bounds the stall; for high throughput run multiple workers or a
> dedicated queue. Ordering across retries is **not** guaranteed — consumers must be
> idempotent (dedupe on `event_id`).

## Inbound — 2 steps

### 1. Register a receiver

```bash
sc new webhookreceiver --name Stripe --slug stripe --secret "whsec_..." --user admin
# → external systems POST to /webhooks/in/stripe/
```

(Or the UI at `/smallstack/webhooks/receivers/`, REST, or the `create_webhook_receiver`
MCP tool — same fields everywhere.) Omitted fields use the model defaults:
`require_signature=True`, `signature_header="X-SmallStack-Signature"` (the header
SmallStack's own sender emits, so a SmallStack↔SmallStack pairing verifies with no
configuration), `enabled=True`, and an
auto-generated `secret`. Set `--secret` when the provider hands you one (Stripe's
`whsec_…`); read a generated one back with the Reveal button on the receiver detail
page (staff-only, POST).

The view verifies the signature (constant-time) against `secret`, using the header named
by `signature_header` (default `X-SmallStack-Signature`, **matched
case-insensitively** like any HTTP header — set it to `X-Signature`,
`X-Hub-Signature-256`, … for a third party), records a `WebhookReceipt`, and returns
`202` fast (`401` on bad signature, `404` for unknown/disabled slug).

> Verifiers receive a **case-insensitive mapping** of the request headers, so a
> custom verifier can look up whatever spelling its provider documents
> (`"Stripe-Signature"`, `"stripe-signature"` — both hit).

### 2. Write the handler

Put it in `apps/<yourapp>/webhook_handlers.py` (autodiscovered, like `mcp_tools.py`):

```python
from apps.webhooks.registry import webhook_handler

@webhook_handler("stripe")            # matches the receiver slug (or its `handler` field)
def on_stripe(receipt):
    event = receipt.json()            # parsed body, or None
    if event["type"] == "charge.succeeded":
        ...                           # do real work — runs in a background task
```

Raising inside a handler marks the receipt `failed` (recorded, not fatal).
Receipts are pruned by `manage.py prune_webhook_receipts` after
`SMALLSTACK_WEBHOOK_RECEIPT_RETENTION_DAYS` (default 30; `0` keeps them forever).

**Loop-safe by default (F-020).** A handler runs inside `suppress_webhooks()` — a write it
makes into an `enable_webhooks` model emits **no** outbound event, so a write-back can't
run away. If a handler genuinely *should* re-fire events, opt out:
`@webhook_handler("slug", cascade=True)` (you own the loop safety then).

## The loop guard (F-020)

The outbound observer fires on every write, so an inbound handler (or a paired SmallStack)
writing back could re-trigger the event and run away. Three primitives stop it:

- **`suppress_webhooks()`** — a context manager (public: `from apps.webhooks import
  suppress_webhooks`). Writes inside it emit no outbound events. Wrap an import, a backfill,
  or a handler write-back:
  ```python
  from apps.webhooks import suppress_webhooks
  with suppress_webhooks():
      ticket.status = "closed"; ticket.save()     # fires no webhook
  ```
  Inbound dispatch applies it automatically (above).
- **`X-SmallStack-Origin`** — every delivery is stamped with this deployment's origin
  (`SMALLSTACK_WEBHOOK_ORIGIN`, default from `SITE_URL`/hostname). Recorded on the receipt.
- **`WebhookReceiver.ignore_origin`** — set it to your own origin and a self-originated
  event echoed back by a peer is dropped (receipt status `ignored`), not dispatched.

## SmallStack↔SmallStack, first-class

> **Prerequisite: set an origin.** S2S/pairing needs `SITE_URL` (or
> `SMALLSTACK_WEBHOOK_ORIGIN`) set to this deployment's absolute base URL. Without it the
> origin falls back to the bare hostname, so `resource.url` degrades to `null` and the
> `origin`-based loop-guard **dedupe** loses its base. `webhook_doctor` WARNs when the
> origin is unresolved.

**`sc webhook pair` configures THIS instance's half** of a loop-safe two-way link — an
outbound endpoint **and** an inbound receiver here, `transform="smallstack"`, loop guard on.
It **does not reach the peer**: it stands up the local half and hands you the exact command
to run on the peer. A full link is two runs (one per instance).

```bash
sc webhook pair --target https://peer.example.com/webhooks/in/paired/ --events '["*"]'
```

Output (abridged) — the local half, then the **mirror command** for the peer:

```
Configured (created) THIS instance's half of a two-way link. HALF 1 of 2.
  outbound endpoint #7 → https://peer.example.com/webhooks/in/paired/
  inbound receiver #7 at https://a.example.com/webhooks/in/paired-1a2b3c4d/
  ── SECRETS (copy now — shown once) ──
    send secret (we sign outbound with) : <SEND>
    recv secret (we verify inbound with): <RECV>
  ⇒ HALF 2 of 2 — run THIS on the peer to finish (secrets already swapped):
    sc webhook pair --target https://a.example.com/webhooks/in/paired-1a2b3c4d/ \
        --send-secret <RECV> --recv-secret <SEND> --events '["*"]'
  This configured OUR instance only — the link is not live until the peer runs it.
```

(Or the **“Connect a SmallStack”** action on the webhooks dashboard, which shows the same
block once.) Key points:

- **Two per-direction secrets, not one.** The direction we *send* (endpoint A→B) and the
  direction we *receive* (receiver B→A) use **independent** secrets, so a leak in one
  direction doesn't expose the other. `--send-secret` / `--recv-secret` set them
  explicitly; `--secret` is a convenience alias that sets both the same; omitted secrets
  are generated. The printed **mirror command swaps them** (the peer's send = our recv, the
  peer's recv = our send), so the operator runs one command on B and the two-secret detail
  is handled automatically.
- **Secrets shown once.** Copy them from the block above; retrieve later via the staff
  **Reveal** action on the endpoint/receiver detail page; **Rotate** there to roll a secret
  (the other side must re-sync). Secrets are never written to the server or activity/audit
  log in plaintext.
- **Idempotent.** The default receiver slug is a stable hash of the target, so re-running
  `pair` with the same `--target` **updates** the existing endpoint+receiver in place
  (config refreshed, secrets preserved unless you supply new ones) — no duplicates.
- **`--one-way`** creates only the outbound endpoint (no local receiver) — for a link where
  the peer only consumes our events.
- **`--verify`** (after both halves exist) fires a signed test delivery through the paired
  endpoint; check its status (`sc webhook deliveries --status success`) to confirm the peer
  accepted the local→peer direction.

> **Pairing two instances on one box needs one extra setting.** A loopback or
> private target (`http://127.0.0.1:8065/webhooks/in/…`) is refused by the SSRF
> guard *before the request is sent*, so the delivery is recorded as failed and
> nothing reaches the peer. Set `SMALLSTACK_WEBHOOK_ALLOW_PRIVATE=true` (dev
> only) in the environment of **the process that sends** — i.e. the `db_worker`,
> not just the web server. `sc webhook pair` prints a warning when the target is
> blocked (both the two-way and `--one-way` shapes), and `sc doctor webhook`
> reports it under "Endpoint URLs".

> **Inbound dispatch needs a worker.** The receiver returns `202` immediately and
> runs the handler in `apps.webhooks.tasks.dispatch_incoming`, so a paired
> SmallStack does nothing until a `db_worker` runs.

Because both sides run the loop guard and set `ignore_origin`, an event one side originates
can't echo back and re-fire. The upgraded envelope (`event_id`, absolute `resource.url`)
means the receiving side can dedupe and act without a second fetch.

## The four extension seams

All four are **named-registry** hooks, discovered from an app's `webhook_*.py` at
`ready()` (like `@webhook_handler` / `mcp_tools.py`). Each ships a built-in default so core
behavior is unchanged; you select one per endpoint/receiver by name. An unknown name falls
back to the default (logged), never a dropped delivery. `webhook_doctor --explain` lists
every registered seam.

| Seam | Decorator (module) | Model field (default) | Replaces / enables |
|---|---|---|---|
| Outbound transform (F-019) | `@webhook_transform` (`webhook_transforms.py`) | `endpoint.transform` (`smallstack`) | Slack `{text}`, CloudEvents, Event Grid schema |
| Outbound auth (F-025) | `@webhook_auth` (`webhook_auths.py`) | `endpoint.auth_scheme` (`hmac`) | Azure SAS key, SigV4, OIDC bearer |
| Inbound verifier (F-016) | `@webhook_verifier` (`webhook_verifiers.py`) | `receiver.verifier` (`hmac`) | Stripe `t.body`, GitHub `sha256=`, SNS RSA |
| Inbound challenge (F-026) | `@webhook_challenge` (`webhook_challenges.py`) | `receiver.challenge` (none) | Event Grid validation, SNS SubscribeURL |

```python
# apps/myapp/webhook_transforms.py — reshape the outbound body for Slack
from apps.webhooks import webhook_transform, Transformed
import json

@webhook_transform("slack")
def to_slack(event):                       # event = the envelope dict
    return Transformed(body=json.dumps({"text": f"{event['event']} fired"}).encode())
```

```python
# apps/myapp/webhook_verifiers.py — Stripe's t.body scheme (constant-time inside)
from apps.webhooks import webhook_verifier
import hmac, hashlib

@webhook_verifier("stripe")
def verify_stripe(body, headers, receiver):
    parts = dict(p.split("=", 1) for p in headers.get("Stripe-Signature", "").split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    expected = hmac.new(receiver.secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
```

Then select it: `sc set webhookreceiver <pk> --verifier=stripe`. This is the **first-class
replacement** for the old `require_signature=False` escape hatch — a Stripe receiver is now
*verifying* (with a different scheme), not *failing open*.

### Verifier vs. `require_signature=False` (F-017)

- **`receiver.verifier`** picks *how* the signature is checked. Default `hmac` is the raw-body
  HMAC over `signature_header` (GitHub-compatible, accepts the `sha256=` prefix). A custom
  verifier expresses any other scheme.
- **`require_signature=False`** still means *fail open* — accept unsigned/bad-signature
  POSTs. Use it only while onboarding a sender that doesn't sign yet. For a provider that
  signs *differently*, write a `@webhook_verifier` instead — don't fail open.
- `webhook_doctor` now distinguishes the two: a custom-verifier receiver reports PASS
  (“verified, not fail-open”); only default-verifier + `require_signature=False` WARNs.

### Reference adapter: Azure Event Grid

`apps/webhooks/contrib/eventgrid.py` is a complete two-way Event Grid integration built
**purely on the four seams, with zero core edits** — proof the seams are enough. It maps
the envelope to the Event Grid schema (`@webhook_transform`), adds the `aeg-sas-key`
(`@webhook_auth`), answers the subscription-validation handshake (`@webhook_challenge`),
and verifies the key (`@webhook_verifier`). Copy its decorators into your app's
`webhook_*.py` (or call `eventgrid.register()` from `ready()`), then set
`transform="eventgrid"`, `auth_scheme="eventgrid-sas"`, `verifier="eventgrid"`,
`challenge="eventgrid"` on the relevant endpoint/receiver.

### Recipes per service

Which seam(s)/setting to reach for per destination, and the one gotcha each. Only
**Azure Event Grid** ships an adapter (`contrib/eventgrid.py`) — it's the **copy-me
template** for the others. AWS SNS and Google Pub/Sub are **pattern-only** (no shipped
adapter): write the seam yourself following the Event Grid file.

| Service | Direction | Use | The one gotcha |
|---|---|---|---|
| **Zapier** | outbound | Endpoint, default `smallstack` transform (or a small `@webhook_transform` to flatten `data.*` to the top level) | Zapier's Catch Hook **ignores** the signature and 200s everything — the `X-SmallStack-Signature` header is harmless; map off the (upgraded) envelope keys or a flatten transform. |
| **n8n** | both (S2S pattern) | Outbound endpoint → n8n; n8n calls back into `/smallstack/api/…` with a Bearer token | The write-back is an ORM/API write into a webhooks-enabled model — rely on the **loop guard** (`suppress_webhooks()` around the write, or a paired receiver with `ignore_origin`) so it doesn't re-fire. This is the [S2S pattern](#smallstacksmallstack-first-class). |
| **Slack / Discord** | outbound | `@webhook_transform` → `{"text": …}` (or a Slack blocks object); set `endpoint.transform` to it | The destination **rejects the raw envelope** (`400 invalid_payload`) — it accepts only its own shape, so the transform is mandatory, not optional. |
| **Stripe** | inbound | `@webhook_verifier("stripe")` for the compound `Stripe-Signature: t=…,v1=…` (HMAC over `"<t>.<body>"`); set `receiver.verifier` | The signed content is **`timestamp + "." + body`**, not the raw body — the default `hmac` verifier can't express it. **Don't** reach for `require_signature=False` (that's fail-open); write the verifier. |
| **GitHub** | inbound | Default `hmac` verifier works as-is; set `receiver.signature_header = "X-Hub-Signature-256"` | GitHub sends `sha256=<hex>` — the default verifier already **accepts the `sha256=` prefix** and hashes the raw body, which is exactly GitHub's scheme. Zero custom code. |
| **Azure Event Grid** | both | The shipped `contrib/eventgrid.py` adapter — all four seams (`transform=eventgrid`, `auth_scheme=eventgrid-sas`, `verifier=eventgrid`, `challenge=eventgrid`) | Event Grid opens with a `SubscriptionValidationEvent` handshake — the `@webhook_challenge` echoes the `validationCode` **before** verify/dispatch, so it must run unsigned. |
| **AWS SNS** *(pattern-only)* | inbound | `@webhook_challenge` to confirm the `SubscribeURL` on `SubscriptionConfirmation` + `@webhook_verifier` for the **X.509/RSA** message signature (fetch the cert, verify the canonical string) | Not HMAC — SNS signs with RSA over a canonicalized field list; the challenge must GET the `SubscribeURL` to activate the subscription. Follow the Event Grid template. |
| **Google Pub/Sub** *(pattern-only)* | inbound | `@webhook_verifier` for the **OIDC bearer JWT** (verify against Google's public keys + audience), then base64-decode `message.data` in the handler | The event body wraps the payload as base64 in `message.data` — verify the JWT at the verifier seam, unwrap the data in the `@webhook_handler`. Follow the Event Grid template. |

## CLI

CRUD on endpoints/receivers uses the **generic** `sc` verbs (they're CRUDViews);
webhook-specific **ops** live under `sc webhook` (fronting `manage.py webhook`):

```bash
# create / manage endpoints (generic CRUD — audited + validated like the web UI)
sc new webhook --name Zapier --target_url https://hooks.zapier.com/... \
   --event_filter '["support.ticket.*"]' --user admin      # enabled by default
sc ls webhook                              # list endpoints ('sc ls' flags column: w = enable_webhooks)
sc set webhook 3 --enabled=false --user admin
sc rm  webhook 3 --force --user admin

# ops (report / test / replay / retry / pair)
sc webhook status                          # counts by delivery status + retry backlog
sc webhook list                            # endpoints with health (last status, fail-streak)
sc webhook test Zapier                     # fire a signed test delivery
sc webhook deliveries --status dead --limit 20
sc webhook replay 42                       # re-send one dead delivery (reuses its event_id)
sc webhook replay --status dead            # BULK re-send every dead delivery (F-023)
sc webhook replay --status dead --endpoint Zapier --since 2026-07-01T00:00:00
sc webhook pair --target https://peer/webhooks/in/x/ --events '["*"]'  # configure our half + emit peer cmd
sc webhook pair --target … --one-way       # outbound endpoint only (no local receiver)
sc webhook pair --target … --verify        # + fire a probe to test the local->peer round-trip
sc webhook tick                            # run the retry tick once (interactive)
```

`sc webhook …` == `manage.py webhook …`; every subcommand takes `--json`.

**Test deliveries don't retry.** Every test path (`sc webhook test`, the detail-page
button, the `test_webhook` MCP tool) creates the delivery with `max_attempts=1`, so a
failed test goes **straight to `dead`** — it's a reachability probe, not a retry demo.
To watch retry/backoff, fire a real signal-driven event (save a model with
`enable_webhooks = True`) while the destination is down. Test and replay both print a
note when the target endpoint is disabled (test/replay sends still go out; signal
events don't).

## Validate

```bash
python manage.py webhook_doctor            # outbound registry, endpoint URLs, stuck retries, inbound handlers
python manage.py webhook_doctor --explain  # every enable_webhooks model + every handler
sc doctor webhook                          # same, via the framework CLI (also part of `sc doctor all`)
```

## Gotchas

1. **Empty `event_filter` is inert, not a firehose.** An endpoint with `[]` matches
   nothing — set `["*"]` deliberately for catch-all.
2. **The signing secret is stored recoverably, not hashed.** Unlike `APIToken`, an HMAC
   secret must be read back to sign every payload. Reveal/rotate it from the endpoint
   or receiver detail page (staff-only POST actions); set a known one at create/update
   time via the write-only `secret` field. It's never *returned* by REST/MCP/`sc` reads.
3. **SSRF guard.** Outbound targets can't be loopback/private IPs unless
   `SMALLSTACK_WEBHOOK_ALLOW_PRIVATE=true` (dev), and `SMALLSTACK_WEBHOOK_ALLOWLIST`
   restricts hosts. Checked at save time *and* send time.
4. **No opt-in ⇒ no fan-out.** A model without `enable_webhooks = True` fires nothing,
   even with a `["*"]` endpoint.
5. **Scripted creates honor model defaults.** `sc new` / REST `POST` / MCP `create_*`
   fill omitted fields from the model defaults, exactly like an ORM `.create()` —
   so a new endpoint/receiver is **enabled**, and a receiver keeps
   `require_signature=True` and `signature_header="X-SmallStack-Signature"` unless you say
   otherwise. Pass `--enabled=false` to create something switched off.
6. **`require_signature=False` fails open — prefer a verifier.** An enabled receiver with
   signature verification off accepts unsigned/bad-signature POSTs. For a provider that
   signs *differently* (Stripe, Event Grid) write a `@webhook_verifier` instead; that's
   *verifying*, not failing open. `webhook_doctor` WARNs only on the fail-open case.
7. **REST lives under `/smallstack/api/`.** The generated endpoints are
   `/smallstack/api/webhooks/endpoints/`, `…/deliveries/`, `…/receivers/`,
   `…/receipts/` (browse them in Swagger at `/api/docs/`).
8. **Handlers/seams are autodiscovered at process start, not hot-reloaded (F-018).** Add a
   `webhook_handlers.py` / `webhook_*.py` and you must **restart `db_worker`** (and the dev
   server) for it to register — otherwise dispatch records “no handler registered”.
   `webhook_doctor` calls this out when a receiver has no handler. The dev server's
   autoreload picks up file *changes*; a brand-new module still needs a restart.

## Settings (config/settings/smallstack.py)

`SMALLSTACK_WEBHOOKS_ENABLED` / `_OUTBOUND` / `_INBOUND`, `SMALLSTACK_WEBHOOK_MAX_ATTEMPTS`,
`SMALLSTACK_WEBHOOK_TIMEOUT`, `SMALLSTACK_WEBHOOK_BACKOFF`, `SMALLSTACK_WEBHOOK_MAX_BACKOFF`,
`SMALLSTACK_WEBHOOK_ORIGIN`, `SMALLSTACK_WEBHOOK_AUTO_DISABLE_AFTER`,
`SMALLSTACK_WEBHOOK_ALLOWLIST`, `SMALLSTACK_WEBHOOK_ALLOW_PRIVATE`, `SMALLSTACK_WEBHOOK_FAILURE_EMAILS`.
