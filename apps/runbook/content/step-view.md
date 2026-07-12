---
title: Step View (Coming Soon)
order: 4
---

# Step View

> **Status: Coming Soon** — Step view is built but not yet exposed in the UI. It will be enabled in a future release.

The Step View renders a markdown document as a vertical timeline of numbered steps. This is ideal for processes, checklists, and runbooks that follow a sequential flow.

## How It Will Work

Use `## Step N: Title` headings to define each step:

```markdown
# Process Title

## Step 1: Prepare

Description of what to do in step 1.

> note: Important reminder for this step.

## Step 2: Execute

Description of step 2.

## Step 3: Verify

Final step content.

> note: Check the logs after completing this step.
```

## Note Callouts

Use `> note:` blockquotes to add highlighted notes within a step:

```markdown
> note: This will appear as a highlighted callout.
```

Notes are extracted from the step content and displayed as inset cards with a colored left border.

## Formatting Tips

- Number your steps sequentially: `Step 1:`, `Step 2:`, etc.
- Keep step titles concise — they appear in the timeline markers
- Add notes for important warnings, tips, or prerequisites
- Regular markdown (code blocks, lists, tables) works inside steps
