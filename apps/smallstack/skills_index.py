"""Derive ``docs/skills/index.json`` from the table rows in ``docs/skills/README.md``.

The skill index exists in two shapes: a human-readable table in ``README.md`` and a
machine-readable ``index.json`` for agents that want keywords and ``use_when`` hints.
Maintaining both by hand rots the JSON — it drifted to 29 of 76 files, including a
stale entry for a file that had been deleted, which left agents consulting the index
with a view of the skill set that was two years out of date.

So ``README.md`` is the single source of truth and ``index.json`` is generated from it.
Hand-curated fields that have no home in the README table (``name``, ``keywords``,
``use_when``) are carried over from the existing JSON when an entry is already there.

Downstream forks get this for free: drop a skill file in ``docs/skills/``, add a row to a
registry table, run ``make skills-index``. The checks below fail loudly if a file is
registered nowhere, so an unregistered skill can't go unnoticed the way a fork's own
``upstream-workflow.md`` did — referenced by ``CLAUDE.md``, absent from the index, so an
agent looking for release guidance found upstream's (wrong-for-a-fork) file instead.

A fork registers *its own* skills in ``docs/skills/local.md``, which upstream never ships,
so doing it right costs no merge conflicts on the next ``git pull upstream main``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

INDEX_NAME = "index.json"
README_NAME = "README.md"

#: A fork's own skill registry. Upstream never ships rows in this file (it doesn't ship the
#: file at all), so a downstream project can register its own skills — and have them show up
#: in the index agents consult — without editing an upstream-tracked table and taking a merge
#: conflict on every `git pull upstream main`. Same table format as README.md.
LOCAL_NAME = "local.md"

#: A README table row: ``| [some/file.md](some/file.md) | Description |``
_ROW_RE = re.compile(r"^\|\s*\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)\s*\|\s*(?P<description>.*?)\s*\|\s*$")

#: A markdown heading, used to tag each row with the section it sits under.
_HEADING_RE = re.compile(r"^#{2,3}\s+(?P<title>.+?)\s*$")

#: Scope markers a row may carry, so a fork's agent knows which side of the
#: upstream/downstream line a skill sits on. Parsed out of the description and
#: surfaced as ``scope`` in the JSON.
SCOPE_MARKERS: dict[str, str] = {
    "**(upstream repo only)**": "upstream-only",
    "**(forks / downstream)**": "fork-facing",
}


def skills_dir() -> Path:
    """Where the skill files live. Honours ``SMALLSTACK_SKILLS_DIR`` if a fork moved them."""
    override = getattr(settings, "SMALLSTACK_SKILLS_DIR", None)
    if override:
        return Path(override)
    return Path(settings.BASE_DIR) / "docs" / "skills"


@dataclass(frozen=True)
class Row:
    """One registered skill, as a registry table declares it."""

    file: str
    description: str
    section: str
    scope: str | None
    local: bool = False
    """Registered in the fork's own ``local.md`` rather than the shipped README."""


@dataclass(frozen=True)
class Drift:
    """Everything that is out of sync between the files on disk, the README, and the JSON."""

    unregistered: list[str]
    """Skill files on disk with no row in either registry."""

    dangling: list[str]
    """Registry rows pointing at a file that does not exist."""

    stale_index: bool
    """``index.json`` does not match what the registries would generate."""

    @property
    def ok(self) -> bool:
        return not self.unregistered and not self.dangling and not self.stale_index

    def describe(self) -> list[str]:
        """Human-readable problems, each line ending in the fix."""
        problems: list[str] = []
        for name in self.unregistered:
            problems.append(
                f"{name}: skill file is registered nowhere — add a row to docs/skills/{README_NAME} "
                f"(or docs/skills/{LOCAL_NAME} if it's your project's own skill)"
            )
        for name in self.dangling:
            problems.append(
                f"{name}: a registry row points at a file that does not exist — fix or drop the row"
            )
        if self.stale_index:
            problems.append(f"docs/skills/{INDEX_NAME} is out of date — run `make skills-index`")
        return problems


def discover_files(root: Path) -> list[str]:
    """Every skill file under ``root``, as POSIX paths relative to it. The registries excluded."""
    registries = {README_NAME, LOCAL_NAME}
    found = [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*.md"))
        if path.name not in registries or path.parent != root
    ]
    return found


def parse_readme(root: Path) -> list[Row]:
    """Every registered skill: the shipped README's tables, then the fork's ``local.md``."""
    rows = _parse_registry(root / README_NAME, local=False)
    rows.extend(_parse_registry(root / LOCAL_NAME, local=True))
    return rows


def _parse_registry(path: Path, *, local: bool) -> list[Row]:
    """Read one registry file's skill tables top to bottom, preserving document order."""
    rows: list[Row] = []
    if not path.exists():
        return rows
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group("title")
            continue
        match = _ROW_RE.match(line)
        if not match:
            continue
        target = match.group("target")
        if not target.endswith(".md") or target in {README_NAME, LOCAL_NAME}:
            continue
        description, scope = _split_scope(match.group("description"))
        rows.append(
            Row(file=target, description=description, section=section, scope=scope, local=local)
        )
    return rows


def _split_scope(description: str) -> tuple[str, str | None]:
    """Pull a leading scope marker off a row description."""
    for marker, scope in SCOPE_MARKERS.items():
        if description.startswith(marker):
            remainder = description[len(marker) :].lstrip(" —-")
            return remainder.strip(), scope
    return description.strip(), None


def entry_id(file: str) -> str:
    """``mcp/verify-mcp.md`` → ``mcp-verify-mcp``; ``sc-cli.md`` → ``sc-cli``."""
    return file.removesuffix(".md").replace("/", "-")


#: Words `str.title()` gets wrong when deriving a display name from a filename.
_ACRONYMS = {
    "a11y": "a11y",
    "api": "API",
    "cli": "CLI",
    "crud": "CRUD",
    "css": "CSS",
    "db": "DB",
    "fts": "FTS",
    "htmx": "htmx",
    "mcp": "MCP",
    "oauth": "OAuth",
    "pg": "PG",
    "postgres": "Postgres",
    "rest": "REST",
    "rss": "RSS",
    "sc": "sc",
    "sla": "SLA",
    "sql": "SQL",
    "sqlite": "SQLite",
    "ui": "UI",
    "url": "URL",
}


def _words(stem: str) -> str:
    return " ".join(_ACRONYMS.get(word, word.title()) for word in stem.split("-"))


def _default_name(file: str) -> str:
    """Derived display name. A curated ``name`` in the existing index always wins over this."""
    path = file.removesuffix(".md")
    if "/" in path:
        parent, stem = path.split("/", 1)
        return f"{_words(parent)}: {_words(stem)}"
    return _words(path)


def load_index(root: Path) -> dict[str, Any] | None:
    """The committed ``index.json``, or ``None`` if a fork removed it."""
    path = root / INDEX_NAME
    if not path.exists():
        return None
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


def build_index(root: Path) -> dict[str, Any]:
    """Generate the index from the registry tables, carrying hand-curated fields forward."""
    existing = load_index(root) or {}
    prior = {entry["file"]: entry for entry in existing.get("skills", []) if "file" in entry}

    skills: list[dict[str, Any]] = []
    for row in parse_readme(root):
        was = prior.get(row.file, {})
        entry: dict[str, Any] = {
            "id": entry_id(row.file),
            "file": row.file,
            "name": was.get("name") or _default_name(row.file),
            "description": row.description,
            "section": row.section,
        }
        if row.scope:
            entry["scope"] = row.scope
        if row.local:
            entry["origin"] = "fork-local"
        # keywords / use_when have no home in the README table, so they survive here.
        if was.get("keywords"):
            entry["keywords"] = was["keywords"]
        if was.get("use_when"):
            entry["use_when"] = was["use_when"]
        skills.append(entry)

    return {
        "name": existing.get("name", "smallstack-skills"),
        "description": (
            "AI skill index for Django SmallStack. Read the relevant skill before modifying "
            "the corresponding part of the codebase."
        ),
        "generated": True,
        "source": f"docs/skills/{README_NAME} (+ {LOCAL_NAME} for this project's own skills)",
        "regenerate": "make skills-index",
        "skills": skills,
    }


def render_index(index: dict[str, Any]) -> str:
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def check(root: Path) -> Drift:
    """Compare files on disk, the README table, and the committed JSON."""
    files = set(discover_files(root))
    rows = parse_readme(root)
    registered = {row.file for row in rows}

    current = load_index(root)
    expected = build_index(root)
    stale = current is None or current != expected

    return Drift(
        unregistered=sorted(files - registered),
        dangling=sorted(registered - files),
        stale_index=stale,
    )


def write_index(root: Path) -> Path:
    path = root / INDEX_NAME
    path.write_text(render_index(build_index(root)), encoding="utf-8")
    return path
