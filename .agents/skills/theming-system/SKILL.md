---
name: theming-system
description: "CSS variables, palettes, dark mode"
license: MIT
metadata:
  source: "docs/skills/theming-system.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/theming-system.md` by `make skills-index` — edit the source, not this file.

# Skill: Theming System

> **For page-building work, start with [`modern-dark-theme.md`](modern-dark-theme.md) instead.** That's the v0.9.x prescriptive guide for AI agents building pages. This file covers the broader architecture (variable cascade, file locations, how the data-palette attribute is set) and remains the right reference for that. For palette modification specifically, see [`modify-palettes.md`](modify-palettes.md).

This skill describes how to customize the SmallStack theme, including colors, color palettes, dark mode, and UI components.

## Overview

The theme is built on Django admin's CSS foundation with CSS custom properties (variables) for easy customization. All theming is done through CSS - no build tools required.

SmallStack supports **selectable color palettes** (django, high-contrast, dark-blue, orange, purple) with a system-wide default and per-user override.

This skill is long; the full text is in [references/theming-system.md](references/theming-system.md) — read it before acting.
