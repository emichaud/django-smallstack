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
    """Every ``docs/skills/...`` path CLAUDE.md / AGENTS.md names must exist and be in the index.

    This is the exact shape of the downstream report: CLAUDE.md pointed at a skill file
    that the index didn't know about.
    """
    import re
    from pathlib import Path

    from django.conf import settings

    files = [Path(settings.BASE_DIR) / name for name in ("CLAUDE.md", "AGENTS.md")]
    files = [f for f in files if f.exists()]
    if not files:
        pytest.skip("no CLAUDE.md / AGENTS.md")

    text = "\n".join(f.read_text(encoding="utf-8") for f in files)
    referenced = {
        ref for ref in re.findall(r"docs/skills/([A-Za-z0-9_\-/]+\.md)", text) if ref != skills_index.README_NAME
    }
    registered = {row.file for row in skills_index.parse_readme(SKILLS)}
    missing_on_disk = sorted(ref for ref in referenced if not (SKILLS / ref).exists())
    unregistered = sorted(referenced - registered)

    assert not missing_on_disk, "AGENTS.md/CLAUDE.md point at missing skill files: " + ", ".join(missing_on_disk)
    assert not unregistered, (
        "AGENTS.md/CLAUDE.md point at skills missing from the index: " + ", ".join(unregistered)
    )


# -- Agent Skills (https://agentskills.io/specification) ------------------------


_NAME_OK = __import__("re").compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def test_generated_skill_names_and_descriptions_are_spec_valid() -> None:
    skills = skills_index.build_agent_skills(SKILLS)
    assert skills, "no Agent Skills generated"
    for name, files in skills.items():
        assert 1 <= len(name) <= 64 and _NAME_OK.match(name), name
        text = files[skills_index.SKILL_FILE]
        assert text.startswith("---\nname: " + name + "\n"), name
        desc = text.split("\ndescription: ", 1)[1].split("\n", 1)[0]
        assert 2 < len(desc) <= 1026, (name, len(desc))  # quoted, ≤ 1024 inside
        assert skills_index.GENERATED_BY in text


def test_long_skills_are_split_into_references() -> None:
    skills = skills_index.build_agent_skills(SKILLS)
    long_ones = [n for n, f in skills.items() if any(k.startswith("references/") for k in f)]
    assert long_ones, "expected at least one skill over MAX_INLINE_LINES"
    for name in long_ones:
        body = skills[name][skills_index.SKILL_FILE]
        assert len(body.splitlines()) <= skills_index.MAX_INLINE_LINES
        assert "references/" in body


def test_agent_skills_tree_is_in_sync() -> None:
    """``.agents/skills/`` and the ``.claude/skills/`` links are generated — they
    must be what the current README produces. ``make skills-index`` fixes it."""
    drift = skills_index.check(SKILLS)
    assert not drift.stale_skills, "the Agent Skills tree is stale — run `make skills-index`"


def test_skill_name_sanitises_awkward_file_names() -> None:
    assert skills_index.skill_name("merge-0.12.0.md") == "merge-0-12-0"
    assert skills_index.skill_name("mcp/verify-mcp.md") == "mcp-verify-mcp"
    assert skills_index.skill_name("Weird__Name!.md") == "weird-name"


def test_write_and_check_round_trip_in_a_fork(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path
    root = project / "docs" / "skills"
    root.mkdir(parents=True)
    (root / skills_index.README_NAME).write_text(
        "## Available Skills\n\n| File | Description |\n|---|---|\n| [one.md](one.md) | **First** skill |\n",
        encoding="utf-8",
    )
    (root / "one.md").write_text("# One\n\nBody.\n", encoding="utf-8")
    skills_index.write_index(root)
    skills_index.write_agent_skills(root, project)
    skill = project / skills_index.AGENT_SKILLS_SUBDIR / "one" / skills_index.SKILL_FILE
    assert skill.is_file() and "description: \"First skill\"" in skill.read_text()
    link = project / skills_index.CLAUDE_SKILLS_SUBDIR / "one"
    assert link.is_symlink() and (link / skills_index.SKILL_FILE).is_file()
    assert not skills_index.check(root, project).stale_skills
    # Drop the row: the generated directory and link go; a hand-made one stays.
    hand = project / skills_index.AGENT_SKILLS_SUBDIR / "mine"
    hand.mkdir()
    (hand / skills_index.SKILL_FILE).write_text("---\nname: mine\ndescription: hand made\n---\n")
    (root / skills_index.README_NAME).write_text("## Available Skills\n\n| File | Description |\n|---|---|\n")
    (root / "one.md").unlink()
    skills_index.write_index(root)
    skills_index.write_agent_skills(root, project)
    assert not skill.exists() and not link.exists() and hand.is_dir()

