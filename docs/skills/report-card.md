# Skill: Generate a Project Quality Report Card

Produce a **consistent, evidence-backed "report card"** that grades the current state of a SmallStack
project across core quality areas, summarizes what changed (by category), and lists open/resolved
findings. Report cards are committed to `docs/report-cards/` so anyone can view the project's quality
trajectory over time — like a standardized audit scorecard.

**Read this skill before generating a card.** It defines the rubric (so grades are reproducible, not
vibes), the change taxonomy, the data sources, and the procedure. Pair it with the blank
`docs/report-cards/TEMPLATE.md` and the worked example alongside it.

## When to use
- After a feature branch, release, or audit cycle — to record the resulting quality state before merge.
- On a cadence (e.g. each release) to show trend.
- The card is a **snapshot at one commit**. Always stamp the exact commit; never retro-edit an old card.

## Output — two tiers
There are two kinds of card; keep them separate:

1. **Release card (canonical, public):** `docs/report-cards/v<version>.md` (e.g. `v0.12.4.md`) — **one
   per release**, finalized at tag time, committed here. This is the trust artifact: browsable per-release
   history, linked from the README and each GitHub Release. Keep old ones — the trajectory *is* the value.
2. **Round snapshot (working record):** a per-test-round draft named
   `<YYYY-MM-DD>_<label>_<version>.md`, produced by the integration test harness
   (github.com/emichaud/smallstack-testing-agent → `results/`). These are the audit trail; they stay in
   the harness repo and do **not** clutter this public folder.

A release card is typically the finalized version of the last round snapshot before the tag. Update
`docs/report-cards/README.md`'s index when you add a release card. **Immutable:** never retro-edit a
released card; a new state is a new card.

## The rubric — how to grade (keep it reproducible)

Grade eight core areas. Use letter grades **A · A− · B+ · B · B− · C · D · F** (`+`/`−` for within-band
nuance). Every grade must cite **evidence** (a number, a command output, a finding). When an area
wasn't meaningfully assessed this cycle, grade it **`— (not assessed)`** rather than guessing.

**An open BLOCKER caps the whole card at F, and its area at F, until fixed.** A single unresolved MAJOR
caps the affected area at C.

| # | Area | What it measures | A (excellent) | C (needs work) | F (failing) |
|---|------|------------------|---------------|----------------|-------------|
| 1 | **Security** | vulns, hardened defaults, authz, injection posture | 0 known vulns (pip-audit), 0 open security findings, CSP/HSTS/secure-cookies/token-hashing present, authz enforced | 1 open MAJOR security finding, or a missing hardening default | any open exploitable finding (stored XSS, authz bypass, secret leak) |
| 2 | **Code Quality** | lint, duplication, conventions, types | ruff clean, no new duplication (shared helpers), conventions followed, public surfaces typed | lint errors, or notable copy-paste / dead code | won't lint / pervasive smells |
| 3 | **Testing & Coverage** | pass rate + coverage band | 100% pass **and** coverage ≥ 85% | pass but coverage < 70%, or flaky/skipped core paths | any failing test |
| 4 | **Documentation & Skills** | docs present + *accurate*, skill index current, changelog | docs verified accurate (followed verbatim), skills + `index.json` updated, CHANGELOG/SECURITY current | stale or missing docs for shipped behavior | docs contradict the code |
| 5 | **Architecture & Design** | separation, reuse, extensibility | single responsibility, shared write-paths/helpers, no duplicated logic, clean extension points | duplicated subsystems, leaky boundaries | tangled / unmaintainable |
| 6 | **Operability & Release** | doctors, migrations, setup, versioning, **upgrade path** | doctors green, migrations clean, reproducible `make setup`, version synced, **clean upgrade from the previous release (forward migrations on a populated DB, no data loss)**, backups/monitoring present | a doctor warns, setup needs undocumented steps, or the upgrade path needs manual reconciliation | setup broken, missing migrations, or upgrade loses data / fails |
| 7 | **Accessibility & Theming** | palettes, contrast, responsive (SmallStack-specific) | renders correctly across all 5 palettes × light/dark, good contrast, responsive | one palette broken or contrast issues | unusable UI |
| 8 | **Locality of Behavior** | files-to-understand-one-feature; colocation; indirection cost | a typical feature is legible from 1–2 files; behavior sits with its config/model; code starts local and splits only when real complexity demands | common features routinely need ~5 files, or rely on anti-local escape hatches (dynamic view patching, monkey-patching, display logic split across registry/template/endpoint) | can't tell what a feature does without tracing many layers; splitting is convention-driven, not complexity-driven |

**Coverage bands (area 3, for consistency):** ≥85% → A · 75–85% → B+ · 70–75% → B · 60–70% → C · <60% → D.
100% pass is required for any grade above C.

**Locality of Behavior (area 8)** applies Carlton Gibson's *locality of behavior* principle: everything
needed to understand a piece of code should be close together (ideally one file); optimize for
comprehension over structural purity; **start local, split only when complexity demands** — every split
asks the reader to hold more context. Assess it: pick 2–3 representative features and count how many
files you must open to understand each, and whether behavior is colocated with its config. Reward the
simple-case-stays-simple path (e.g. a 7-line CRUDView with no forms/tables/urls files). Penalize
anti-local patterns: one-item `forms.py`/`tables.py`/`filters.py` for trivial cases, dynamic view
patching (`_make_view`-style overrides), and display logic fragmented across a registry + template +
HTMX endpoint. Guiding line: *build it local, split it later.* (If the repo keeps a locality assessment
under `ai_cowork/`, use it as the reference exemplar.)

**Overall grade:** the holistic roll-up (not a strict mean) — weight Security and Testing highest.
State a one-line rationale. Respect the BLOCKER/MAJOR caps above.

## Change taxonomy — summarize what changed
Group every change in the cycle into these categories (derive from Conventional-Commit prefixes in
`git log <base>..<head>`, then sanity-check against the diff):

| Category | Emoji | Commit prefixes | Example |
|----------|-------|-----------------|---------|
| Security | 🔒 | `security`, `fix` on a vuln, hardening | "fix stored XSS in markdown rendering" |
| New Feature | ✨ | `feat` | "integrate the runbook app" |
| Enhancement | ⬆️ | `feat` (extends existing), `perf` | "eliminate N+1 queries in CLI" |
| Bug Fix | 🐛 | `fix` | "include section-less docs in ZIP export" |
| Refactor | ♻️ | `refactor` | "share one proxy-aware client-IP resolver" |
| Docs & Skills | 📝 | `docs`, skill/`index.json` updates | "add rb CLI + document skills" |
| Chore / Infra | 🔧 | `chore`, `build`, `ci` | "sync uv.lock to 0.12.4" |

## Data sources (gather these — exact commands)
Run against a clean checkout of the snapshot commit (the test harness's provisioned clone is ideal):

```bash
git rev-parse --short HEAD                                  # commit
grep -m1 '^version' pyproject.toml                          # version
uv run ruff check .                                         # Code Quality (lint)
uv run pytest -q                                            # Testing: "N passed" + TOTAL coverage %
uvx pip-audit                                               # Security: known-vuln count
uv run python manage.py api_doctor                          # Operability (Summary: X ✓ / Y ⚠ / Z ✗)
uv run python manage.py mcp_doctor
uv run python manage.py search_doctor
uv run python manage.py makemigrations --check --dry-run    # Operability (clean migrations)
git log <base>..<head> --pretty=format:'%s'                # Change taxonomy
```
- **Findings** (open + resolved, with severity) come from the review/test cycle — e.g. the integration
  test harness's `OPEN_ISSUES.md` + `results/*/SUMMARY.md`, or an `ai_cowork/audit_history/*` audit.
- **Theming** needs a visual pass (shot-scraper palette matrix) — cite it, or mark `— (not assessed)`.
- **Upgrade path** (for a release card): run the harness's `scripts/upgrade-test.sh` (clones the
  previous release, seeds data, merges the new version, migrates forward on the existing DB). It emits
  `upgrade-notes_<prev>_to_<new>.md` — cite PASS/FAIL + the breaking-change signals in Operability &
  Release, and fold the notes into the release's `UPGRADING.md` / GitHub release notes.

## Procedure
1. Pick the snapshot commit; provision/checkout a clean copy of it.
2. Run the data-source commands above; record the raw numbers.
3. Collect findings (open + resolved this cycle) with severity from the review/test record.
4. Categorize every change via the taxonomy.
5. Grade each of the 8 areas against the rubric, citing evidence. Apply the BLOCKER/MAJOR caps.
6. Write the overall grade + one-line verdict.
7. Fill `TEMPLATE.md` into `docs/report-cards/<date>_<label>_<version>.md`.
8. Set **Trend** vs the previous card (↑ / → / ↓ per area); for the first card, "baseline".
9. Add the row to `docs/report-cards/README.md`.
10. Commit (`docs: add report card for <label> (<version>)`).

## Honesty rules (non-negotiable — the card is only useful if trusted)
- **Every grade cites evidence.** No number, no grade → mark `— (not assessed)`.
- **No inflation.** 80% coverage is B+, not A, even if everything else is great. Follow the bands.
- **Caps are hard.** An open BLOCKER = overall F. Don't average it away.
- **Snapshots are immutable.** New state → new card. Never edit yesterday's grades.
- Prefer the terse, verifiable claim ("1474 pass, 80% cov, 0 vulns") over adjectives.
