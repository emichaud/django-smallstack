---
title: Using the Slide Viewer
description: Create focused presentations from markdown files
---

# Using the Slide Viewer

The help system includes a **slide presentation mode** — a focused, one-slide-at-a-time viewer for walkthroughs, feature overviews, and onboarding decks. It uses the same YAML + markdown approach as the rest of the help system.

> **Examples:** [Activity Tracking slide deck](/help/slides/activity-tracking/) | [Feature Overview on the About page](/about/)

## How It Works

Slides live in `apps/help/content/slides/`. A `_slides.yaml` config defines decks, and each slide is a separate `.md` file:

```
apps/help/content/slides/
├── _slides.yaml              # Deck definitions
└── activity-tracking/        # One folder per deck
    ├── intro.md
    ├── how-it-works.md
    └── dashboard.md
```

**URL:** `/help/slides/<deck-slug>/`

## Creating a Slide Deck

1. Add a deck to `apps/help/content/slides/_slides.yaml`:

```yaml
decks:
  - slug: my-deck
    title: "My Deck Title"
    description: "A short description"
    slides:
      - slug: intro
        title: "Introduction"
      - slug: details
        title: "The Details"
      - slug: summary
        title: "Summary"
```

2. Create a folder matching the deck slug with one `.md` file per slide:

```
apps/help/content/slides/my-deck/
├── intro.md
├── details.md
└── summary.md
```

Each slide is standard markdown. Keep slides concise — aim for one screen of content without scrolling.

## Slide Features

- **Keyboard navigation** — left/right arrow keys
- **Progress bar** — shows position in the deck
- **Slide counter** — e.g., "2 / 5"
- **URL hash** — `#slide-2` for bookmarkable positions
- **Dark mode** — uses your current theme and palette
- **Images** — reference static files with standard markdown syntax

## Images and Two-Column Layouts

Use standard markdown for inline images:

```markdown
![Screenshot](/static/smallstack/brand/my-image.png)
```

For a text + image side-by-side layout, use the built-in `two-col` class with `markdown="1"` to enable markdown processing inside HTML:

````markdown
# Slide Title

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Your **markdown** text here.

- Bullet points work
- So do `code spans` and **bold**

</div>
<div class="col" markdown="1">

![Screenshot](/static/smallstack/brand/my-image.png)

</div>
</div>
````

The two columns stack vertically on small screens. Images are automatically constrained to fit the column. See the [Feature Overview slides](/help/slides/features/) for working examples.

## Embedding in Pages

You can embed slides directly in any Django template by loading slides in your view:

```python
from apps.help.utils import get_deck_slides, get_slide_deck

def my_view(request):
    deck = get_slide_deck("my-deck")
    slides = get_deck_slides("my-deck")
    return render(request, "my_template.html", {
        "deck": deck,
        "slides": slides,
    })
```

Then include the slide viewer partial in your template. See the [About page](/about/) for a working example.

## Custom Content Root

Downstream projects can store slides outside the default location using the `content_root` query parameter:

```
/help/slides/my-deck/?content_root=apps/website/slides
```

The path is relative to `BASE_DIR`. Place a `_slides.yaml` and slide folders in that directory. This lets derived projects maintain their own slide decks without modifying the help app.
