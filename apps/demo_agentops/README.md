# demo_agentops — Scenario B: the AI human-in-the-loop gate

An AI agent proposes a privileged action over MCP, a human decides it in the
shared approvals console, and **the action runs only on approval**. Built to
stress-test the *MCP / AI* consumer of `apps/approvals/`: can an agent close the
loop (file → poll → learn the outcome) with no Django shell and no staff web
session?

**Status:** Demo / scenario app. Safe to delete in a downstream project.

## What it demonstrates

| Claim under test | Where |
|---|---|
| A `can_decide` hook **narrows** and can never widen | `approvals.high_risk_needs_superuser` |
| The callback "never breaks the decision"; a raise lands in `callback_error` | `approvals.on_action_decision` + the `__raise_in_callback` payload flag |
| An app-level action failure is app state (`state=failed`), not a framework fault | `actions.py` + the callback's `except` |
| Exactly-once execution across a retried decision | the `is_executed` guard in the callback |
| A downstream app can add its own MCP tool that files an approval | `mcp_tools.propose_agent_action` |
| An explicit `context_template` beats the key-derived card name | `templates/demo_agentops/approval_card.html` |
| The agent's polling story | `get_approval` / `get_agent_action` (enable_mcp factory) — **see the caveat below** |

## The model

`AgentAction`: `tool_name` (`broadcast.send` · `records.purge` ·
`runbook.execute`), `payload` (JSON), `risk` (low/medium/high),
`requested_by_agent`, `state` (proposed → pending → executed | rejected |
expired | canceled | failed), `approval`, `result`, `executed_at`.

`result` + `executed_at` are the proof of execution; they are written only by the
kind callback, on approval.

## The kind

`agentops.action` — `default_expires_in=timedelta(minutes=30)` (agent-scale TTL),
`context_template="demo_agentops/approval_card.html"`, and a `can_decide` hook:

| Risk | Who may decide |
|---|---|
| `low` / `medium` | any eligible staff member (the framework default) |
| `high` | **superusers only** — the hook ANDs on top of the staff gate |

The hook can only narrow: returning `True` for a non-staff bystander changes
nothing, because the staff gate runs first.

## The simulated actions

`actions.py` holds pure, deterministic handlers. Two failure paths exist on
purpose, because the docs promise different behaviour for each:

* an action that raises (`records.purge` with a non-integer `count`, or an
  unknown tool) → `state=failed`, the reason in `result`, `callback_error` empty;
* the reserved payload flag `__raise_in_callback: true` → the **callback** raises,
  so the decision still stands and the traceback lands in
  `ApprovalRequest.callback_error`.

## Users

| Login | Staff? | Role here |
|---|---|---|
| `admin` / `admin` | superuser | the only user who may approve HIGH-risk actions |
| `opslead` / `opslead` | yes, **not** superuser | approves low/medium; refused on HIGH |
| `agentbot` / `agentbot` | **no** | the agent identity; its API token files the requests |

`manage.py seed_approval_scenarios` mints a `demo: agentbot` API token (printed
once) and a `demo: admin` token.

## Pages and tools

| Surface | Who | What |
|---|---|---|
| `/demo/agentops/actions/` | staff | the audit trail of what agents proposed |
| `/api/demo/agentops/actions/` | staff token | REST list/detail |
| `/smallstack/approvals/requests/` | staff | where the human actually decides |
| MCP `propose_agent_action` | any token tier (write) | files the action + its approval |
| MCP `list_agent_actions` / `get_agent_action` | staff token | the audit trail over MCP |
| MCP `request_approval` / `decide_approval` | approvals app | the generic tools |

## How to drive it

```bash
uv run python manage.py create_dev_superuser
uv run python manage.py seed_approval_scenarios     # prints the agentbot token
uv run python manage.py approval_scenario b --check  # 31 assertions, no server needed
```

The harness drives real MCP JSON-RPC calls through the in-process WSGI stack, so
`approval_scenario b` is the full agent loop. To do it by hand against a running
server (`make run PORT=8065`):

```bash
TOKEN=<the demo: agentbot key>
curl -s localhost:8065/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,
  "method":"tools/call","params":{"name":"propose_agent_action","arguments":
  {"tool_name":"broadcast.send","risk":"medium","payload":{"audience":"beta"}}}}'
# → {"action_id": N, "approval_id": M, "poll_with": "get_approval(pk=M)"}
```

Then approve it at `/smallstack/approvals/requests/M/` as `admin`.

## Caveat: the agent cannot poll with its own token

`docs/skills/approvals.md` §2 says an agent "polls `get_approval` until
`status != 'pending'`". `get_approval` does exist (the `enable_mcp` factory
generates it from `ApprovalRequestCRUDView`), but that CRUDView carries
`StaffRequiredMixin`, so the tool is **staff-gated** — and so is the approvals
REST detail endpoint. A non-staff agent identity can file a request and then has
no way to learn the outcome. Harness checks **B08** and **B12** are left FAILing
to record that; see the findings file
(`test_smallstack_frontends/docs/findings/2026-09-25-approvals-notifications.md`).

The workaround a downstream app can use today is either a staff service account
for the agent, or a webhook subscription on
`smallstack_approvals.approvalrequest.updated`.
