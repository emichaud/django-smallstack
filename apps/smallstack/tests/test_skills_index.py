"""Guards on the agent-skill index.

The failure these prevent: a skill file that exists on disk and is referenced by
``CLAUDE.md`` but registered in neither ``docs/skills/README.md`` nor ``index.json``.
An agent consulting the index then gets a confidently wrong answer — it finds the
*other* skill on the topic and follows it. Upstream's index had drifted to 29 of 76
files, including a stale entry for a deleted file, before these landed.

These assert self-consistency only — never that a particular skill exists — so a fork
is free to add, delete, or rewrite skills. It just has to keep the two indexes honest.
"""

import pytest

from apps.smallstack import skills_index

SKILLS = skills_index.skills_dir()

pytestmark = pytest.mark.skipif(
    not (SKILLS / skills_index.README_NAME).exists(),
    reason="project has no docs/skills/README.md",
)


def test_every_skill_file_is_registered() -> None:
    """A file with no README row is invisible to an agent browsing the index."""
    drift = skills_index.check(SKILLS)
    assert not drift.unregistered, "add a README table row for: " + ", ".join(drift.unregistered)


def test_every_index_entry_resolves() -> None:
    """No rows (and so no index entries) pointing at files that were deleted or renamed."""
    drift = skills_index.check(SKILLS)
    assert not drift.dangling, "README rows with no file on disk: " + ", ".join(drift.dangling)


def test_index_matches_readme() -> None:
    """index.json is generated — it must be what the current README produces."""
    drift = skills_index.check(SKILLS)
    assert not drift.stale_index, "docs/skills/index.json is stale — run `make skills-index`"


def test_index_entry_ids_are_unique() -> None:
    entries = skills_index.build_index(SKILLS)["skills"]
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids)), "duplicate skill ids in the generated index"


def test_scope_markers_are_parsed_not_left_in_descriptions() -> None:
    """``**(upstream repo only)**`` becomes a ``scope`` field, not description noise."""
    entries = skills_index.build_index(SKILLS)["skills"]
    for entry in entries:
        for marker in skills_index.SCOPE_MARKERS:
            assert not entry["description"].startswith(marker), entry["file"]


def test_a_fork_can_register_its_own_skills_without_touching_the_readme(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``local.md`` is the fork-owned registry — upstream ships no rows there, so no conflicts."""
    (tmp_path / skills_index.README_NAME).write_text(
        "## Available Skills\n\n| File | Description |\n|---|---|\n| [shipped.md](shipped.md) | Upstream |\n",
        encoding="utf-8",
    )
    (tmp_path / skills_index.LOCAL_NAME).write_text(
        "## Our Skills\n\n| File | Description |\n|---|---|\n"
        "| [upstream-workflow.md](upstream-workflow.md) | **(forks / downstream)** How *we* release |\n",
        encoding="utf-8",
    )
    (tmp_path / "shipped.md").write_text("# Shipped", encoding="utf-8")
    (tmp_path / "upstream-workflow.md").write_text("# Ours", encoding="utf-8")

    drift = skills_index.check(tmp_path)
    assert not drift.unregistered and not drift.dangling

    entries = {entry["file"]: entry for entry in skills_index.build_index(tmp_path)["skills"]}
    assert entries["upstream-workflow.md"]["origin"] == "fork-local"
    assert entries["upstream-workflow.md"]["scope"] == "fork-facing"
    assert "origin" not in entries["shipped.md"]


def test_an_unregistered_skill_file_is_reported_with_its_fix(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The downstream report's exact case: file on disk, registered nowhere."""
    (tmp_path / skills_index.README_NAME).write_text(
        "## Available Skills\n\n| File | Description |\n|---|---|\n", encoding="utf-8"
    )
    (tmp_path / "upstream-workflow.md").write_text("# Ours", encoding="utf-8")

    drift = skills_index.check(tmp_path)
    assert drift.unregistered == ["upstream-workflow.md"]
    assert not drift.ok
    assert any(skills_index.LOCAL_NAME in problem for problem in drift.describe())


def test_claude_md_skill_references_are_registered() -> None:
    """Every ``docs/skills/...`` path CLAUDE.md names must exist and be in the index.

    This is the exact shape of the downstream report: CLAUDE.md pointed at a skill file
    that the index didn't know about.
    """
    import re
    from pathlib import Path

    from django.conf import settings

    claude_md = Path(settings.BASE_DIR) / "CLAUDE.md"
    if not claude_md.exists():
        pytest.skip("no CLAUDE.md")

    referenced = {
        ref
        for ref in re.findall(r"docs/skills/([A-Za-z0-9_\-/]+\.md)", claude_md.read_text(encoding="utf-8"))
        if ref != skills_index.README_NAME
    }
    registered = {row.file for row in skills_index.parse_readme(SKILLS)}
    missing_on_disk = sorted(ref for ref in referenced if not (SKILLS / ref).exists())
    unregistered = sorted(referenced - registered)

    assert not missing_on_disk, "CLAUDE.md points at missing skill files: " + ", ".join(missing_on_disk)
    assert not unregistered, (
        "CLAUDE.md points at skills missing from the index: " + ", ".join(unregistered)
    )
