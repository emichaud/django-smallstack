# demo_purchasing — Scenario A: the web approval gate

The classic business gate: a person raises a purchase request, a **human decides
it in the UI**, and the app's own model reacts. Built to stress-test the *web*
consumer of `apps/approvals/` — the staff console, the embeddable decision card,
tiered routing, and non-staff approvers.

**Status:** Demo / scenario app. Safe to delete in a downstream project.

## What it demonstrates

| Claim under test | Where |
|---|---|
| A kind is declared in `approvals.py` and autodiscovered | `approvals.py` |
| The callback handles **every** terminal status; the PO is armed only on approval | `approvals.py` |
| Approvals never write your model — the app owns "what approved means" | `approvals.py` (the only writer of `state` / `po_number`) |
| Requests are **filed** through `services.request_approval`, never by constructing the model | `services.submit_for_approval` |
| Tiered routing at request time via `assignees` | `services.finance_approvers` + `HIGH_VALUE_THRESHOLD` |
| A **non-staff** assignee can decide, via `{% approval_card %}` | `templates/demo_purchasing/purchaserequest_review.html` |
| The context card resolves from the **kind key** (dots → dashes) | `templates/approvals/kinds/purchasing-approve.html` |
| The decision fans out to a signal as well as the callback | `signals.py` |
| `enable_api` + `enable_webhooks` on the business model | `views.py` |

## The model

`PurchaseRequest`: `vendor`, `description`, `amount`, `category`
(hardware/software/services/travel), `justification`, `state`
(draft → pending → approved | rejected | expired | canceled), `requested_by`,
`approval` (FK to `ApprovalRequest`), `decided_note`, `po_number`.

`po_number` is the proof the callback ran: it is minted (`PO-00042`) on approval
and on nothing else.

## The kind

`purchasing.approve` — label "Approve purchase request",
`default_expires_in=timedelta(days=2)`.

Routing, decided in `services.submit_for_approval`:

| Amount | `assignees` | Who may decide |
|---|---|---|
| `>= $5,000` | members of the `finance-approvers` group (**non-staff** in the demo) | those members, plus staff (`SMALLSTACK_APPROVALS_STAFF_OVERRIDE`) |
| `< $5,000` | none | any staff member |

Self-approval is blocked on both tiers (framework default).

## Users

Created by `manage.py seed_approval_scenarios` (see `scenarios.py` for the
full matrix — it is shared by all three scenarios).

| Login | Staff? | Role here |
|---|---|---|
| `admin` / `admin` | superuser | created separately by `create_dev_superuser` |
| `buyer` / `buyer` | no | raises the requests |
| `finance` / `finance` | **no** | `finance-approvers` member — decides ≥ $5,000 in the embed |
| `opslead` / `opslead` | yes | any-staff approver for the lower tier |
| `analyst` / `analyst` | no | the ineligible-bystander control |

## Pages

| URL | Who | What |
|---|---|---|
| `/demo/purchasing/requests/` | staff | console: list + stat cards + filters + search |
| `/demo/purchasing/requests/<pk>/` | staff | CRUD detail |
| `/demo/purchasing/requests/<pk>/review/` | requester, assignees, staff | the requester-facing page with the embedded decision card |
| `POST /demo/purchasing/requests/<pk>/submit/` | requester or staff | "Send for approval" |
| `/api/demo/purchasing/requests/` | staff token | REST (list/create/detail/update) |
| `/smallstack/approvals/requests/` | staff | the shared approvals queue + decision console |

## How to drive it

```bash
uv run python manage.py create_dev_superuser        # admin/admin
uv run python manage.py seed_approval_scenarios
uv run python manage.py approval_scenario a --check # 30 assertions, no server needed
make run PORT=8065
```

Then, in the browser:

1. Sign in as `buyer`, open `/demo/purchasing/requests/2/review/`, press
   **Send for approval** (the seeded `4× developer laptops` draft is a low-tier
   request; the Snowflake row is already in the finance tier).
2. Sign in as `finance` (non-staff) and open the same review URL — the embedded
   card offers **Approve / Reject**. Decide it.
3. Back as `buyer`, the PO number appears and the bell shows the decision.
4. As `admin`, the shared console at `/smallstack/approvals/requests/?status=pending`
   is the queue, and `/smallstack/` shows the pending-count widget.

## Known FAILs (deliberate)

`approval_scenario all --check` currently exits **1** with 89 PASS / 4 FAIL. All
four are framework/doc gaps, kept as live checks rather than deleted so they flip
green the moment they're fixed:

| Check | Gap |
|---|---|
| `A27` | Docs say a non-staff assignee can decide "via the emailed console link", but the console is `StaffRequiredMixin` → 403. Their in-app notification (`A28`) links to the same dead end. |
| `B08` | The `get_approval` MCP polling tool docs §2 names is staff-gated, so a non-staff agent can file but never learn the outcome. |
| `B12` | Same for the approvals REST detail endpoint. |
| `C03` | `POST /smallstack/api/approvals/requests/create/` has no way to attach a `target`. |

See `test_smallstack_frontends/docs/findings/2026-09-25-approvals-notifications.md`.

## Also hosted here (cross-scenario)

This app hosts the scaffolding the three scenarios share, because one of them
had to:

* `scenarios.py` — the user matrix, demo API tokens, and the webhook wiring.
* `management/commands/seed_approval_scenarios.py` — the deterministic seed.
* `management/commands/approval_scenario.py` — the `a|b|c|all [--check]` harness.

`demo_agentops` and `demo_access` do not import from this app; the dependency
runs one way only.
