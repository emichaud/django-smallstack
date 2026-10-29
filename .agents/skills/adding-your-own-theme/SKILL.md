---
name: adding-your-own-theme
description: "Bring your own look — mount Bootstrap / Tailwind / a bespoke base template alongside SmallStack's theme (for teams with an existing design system). Not for changing colors — that's modify-palettes.md"
license: MIT
metadata:
  source: "docs/skills/adding-your-own-theme.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/adding-your-own-theme.md` by `make skills-index` — edit the source, not this file.

# Skill: Adding Your Own Theme

This guide walks you through adding a custom CSS framework (Bootstrap, Tailwind, Tabler, etc.) to a SmallStack project while preserving all built-in SmallStack apps for admin and operational use.

## The Big Idea

SmallStack ships with a complete theme — topbar, sidebar, cards, dark mode, palettes. That theme powers all the built-in apps: Activity, Status, Backups, User Manager, Help, Profile. You don't want to rewrite those pages.

Instead, you add your own theme **alongside** SmallStack's. Your new pages use your theme. SmallStack's built-in pages keep using `smallstack/base.html`. Both themes share dark mode, palettes, and authentication — users move between them seamlessly.

```
┌──────────────────────────────────────────────────┐
│  Your Custom Theme (mytheme/base.html)           │
│  ├── Homepage, dashboards, public pages          │
│  └── Anything you build in apps/website/         │
├──────────────────────────────────────────────────┤
│  SmallStack Theme (smallstack/base.html)         │
│  ├── Activity dashboard     (/activity/)         │
│  ├── Status / Heartbeat     (/status/)           │
│  ├── Backups                (/backups/)           │
│  ├── User Manager           (/manage/users/)     │
│  ├── Help & Docs            (/help/)             │
│  ├── Profile                (/profile/)          │
│  └── Django Admin           (/admin/)            │
└──────────────────────────────────────────────────┘
```

This skill is long; the full text is in [references/adding-your-own-theme.md](references/adding-your-own-theme.md) — read it before acting.
