<!--
Blank report-card template. Copy to docs/report-cards/<YYYY-MM-DD>_<label>_<version>.md and fill in.
Follow docs/skills/report-card.md for the rubric, change taxonomy, data commands, and honesty rules.
Delete these comments when done.
-->
# SmallStack Quality Report Card — <Label>

| | |
|---|---|
| **Project** | <name> |
| **Version** | <x.y.z> |
| **Branch / commit** | `<branch>` @ `<shortsha>` |
| **Date** | <YYYY-MM-DD> |
| **Reviewer** | <who / how> |
| **Scope** | <what was assessed this cycle> |

## Overall: **<Grade>**
<One-paragraph verdict: the headline state, what changed, whether it's merge/release-ready. Respect the
BLOCKER/MAJOR caps — an open BLOCKER makes this F.>

## Scorecard
| # | Area | Grade | Trend | Evidence |
|---|------|:-----:|:-----:|----------|
| 1 | Security | <A–F> | <↑→↓> | <0 vulns; findings; hardening> |
| 2 | Code Quality | | | <ruff; duplication; types> |
| 3 | Testing & Coverage | | | <N passed / 0 failed; coverage %> |
| 4 | Documentation & Skills | | | <docs accuracy; index updated> |
| 5 | Architecture & Design | | | <reuse; boundaries> |
| 6 | Operability & Release | | | <doctors; migrations; setup> |
| 7 | Accessibility & Theming | | | <palettes; or "— not assessed"> |

_Trend is vs the previous card (↑ improved · → held · ↓ regressed); "baseline" on the first card._

## Changes this cycle (by category)
> Group every change; use the taxonomy in the skill. Omit empty categories.

### 🔒 Security (<n>)
- <item> — <one-liner> (`<commit>`)

### ✨ New Features (<n>)
- <item>

### ⬆️ Enhancements (<n>)
- <item>

### 🐛 Bug Fixes (<n>)
- <item>

### ♻️ Refactors (<n>)
- <item>

### 📝 Docs & Skills (<n>)
- <item>

### 🔧 Chore / Infra (<n>)
- <item>

## Findings

### Resolved this cycle
| ID | Sev | Summary | Fixed in |
|----|-----|---------|----------|
| | | | |

### Open
| ID | Sev | Summary | Where |
|----|-----|---------|-------|
| _none_ | | | |

## Evidence
- **Tests:** <N> passed / <M> failed · coverage **<P>%**
- **Lint:** <ruff status> · **Security:** pip-audit <k> known vulns
- **Doctors:** api <a✓> · mcp <m✓> · search <s✓> · **Migrations:** <clean?>
- **Theming:** <palette pass result, or "not assessed">

## Methodology
<How this card was produced: snapshot commit, clean checkout, commands run, finding sources. Keep it
short — the point is reproducibility.>
