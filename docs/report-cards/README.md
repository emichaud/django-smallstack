# Report Cards

Standardized, point-in-time **quality report cards** for SmallStack — a public indicator of code and
solution quality over time. Each card grades the project across seven core areas, summarizes what
changed (by category), and lists open/resolved findings, backed by concrete evidence (tests, coverage,
vulnerabilities, doctors).

Think of it as a recurring audit scorecard: consistent format, reproducible grades, immutable
snapshots. The trend across cards is the story.

## How they're made — and why you can trust them
Cards are produced by an **independent, reproducible integration test harness**
([smallstack-testing-agent](https://github.com/emichaud/smallstack-testing-agent)) that clones a fresh
copy, exercises it end-to-end, and grades it against a fixed rubric — the project does not grade itself.
The method (rubric, change taxonomy, exact data commands, honesty rules) is spelled out in
[`../skills/report-card.md`](../skills/report-card.md); anyone can re-run it. Grades are evidence-backed
(tests, coverage, `pip-audit`, doctors) and honest by design — an open BLOCKER caps the card at **F**.

- **These files = release cards:** `v<version>.md`, one per release, finalized at tag time. Immutable —
  never retro-edited. Add each to the index below.
- **Per-round working snapshots** (the audit trail behind each release card) live in the harness repo's
  `results/`, not here.

## Grading at a glance
Seven areas, each **A–F**: Security · Code Quality · Testing & Coverage · Documentation & Skills ·
Architecture & Design · Operability & Release · Accessibility & Theming. An open **BLOCKER** caps the
overall grade at **F** until fixed. Full rubric in the skill.

## Index
| Version | Card | Date | Overall | Headline |
|:-------:|------|------|:-------:|----------|
| 0.12.4 | [v0.12.4](v0.12.4.md) | 2026-07-12 | **A−** ✅ | Runbook system + all reviewed issues (XSS BLOCKER, loose-doc export, API discoverability) fixed & re-verified; palettes verified; 1475 tests / 0 vulns / 80% cov; 0 open findings |
