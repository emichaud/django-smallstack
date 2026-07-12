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

## Output
- **Path:** `docs/report-cards/<YYYY-MM-DD>_<label>_<version>.md` (e.g.
  `2026-07-12_feat-runbook_v0.12.4.md`). `<label>` = branch or milestone, kebab-case.
- One file per snapshot. Keep old cards — the history *is* the value. Update
  `docs/report-cards/README.md`'s index with the new row.

## The rubric — how to grade (keep it reproducible)

Grade seven core areas. Use letter grades **A · A− · B+ · B · B− · C · D · F** (`+`/`−` for within-band
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
| 6 | **Operability & Release** | doctors, migrations, setup, versioning | doctors green, migrations clean, reproducible `make setup`, version synced, backups/monitoring present | a doctor warns, or setup needs undocumented steps | setup broken / missing migrations |
| 7 | **Accessibility & Theming** | palettes, contrast, responsive (SmallStack-specific) | renders correctly across all 5 palettes × light/dark, good contrast, responsive | one palette broken or contrast issues | unusable UI |

**Coverage bands (area 3, for consistency):** ≥85% → A · 75–85% → B+ · 70–75% → B · 60–70% → C · <60% → D.
100% pass is required for any grade above C.

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

## Procedure
1. Pick the snapshot commit; provision/checkout a clean copy of it.
2. Run the data-source commands above; record the raw numbers.
3. Collect findings (open + resolved this cycle) with severity from the review/test record.
4. Categorize every change via the taxonomy.
5. Grade each of the 7 areas against the rubric, citing evidence. Apply the BLOCKER/MAJOR caps.
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
