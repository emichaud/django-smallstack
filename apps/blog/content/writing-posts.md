---
title: Writing posts
order: 2
---

# Writing posts

Posts are written in Markdown. The editor — **My blogs → your blog → New post** — has a
**Preview** toggle that renders exactly what readers will see — the preview and
the published page go through the same renderer, so what you see really is what
you get.

## What Markdown supports

Headings, **bold**, *italic*, links, images, lists, tables, blockquotes,
horizontal rules, inline `code` and fenced code blocks.

````
```python
Post.objects.order_by("-published_at", "-id")
```
````

Fenced blocks keep their language label, so a downstream project can add syntax
highlighting without changing anything here.

## What it doesn't support, and why

**Raw HTML is shown as text, not rendered.** If you type `<div>` you will see
`<div>` on the page. This is deliberate: posts can be written by people and by
AI agents through the API, and a renderer that executes whatever HTML it is
given is the classic way a site ends up running someone else's JavaScript.
Links using `javascript:` or `data:` are stripped for the same reason.

If you need something Markdown can't express, put it in a template rather than
a post body.

## Titles and headings

Your post's title is already shown as the page heading, so you don't need to
repeat it. If the body opens with a heading identical to the title, it is
dropped automatically — handy when publishing a runbook page, where an opening
`# Heading` is the norm. A *different* opening heading is kept.

## The slug

The slug is the last part of the URL: `/blog/field-notes/my-post/`. Leave it
blank and it's derived from the title. A few words are reserved because the
blog's own URLs use them (`feed`, `tag`, `archive`, `search`, `subscribe`,
`newsletter`); if you pick one, a number is appended rather than the save
failing.

Changing the slug of a published post **breaks existing links**. There is a
permanent alternative that survives retitling: `/blog/p/<uid>/`, shown on the
post's detail page.

## Excerpt

The one- or two-sentence summary used in lists, feeds, search results, the
newsletter preview and link previews on social sites. Leave it blank and the
first paragraph is used.

## Cover image

JPEG, PNG, GIF or WebP, up to 5MB. **Alt text is required** when you set one —
a cover with no description is invisible to anyone using a screen reader, and
the form will not save without it.

## Tags

Comma-separated, created as you type them. Tags belong to one blog, so two
blogs can both have "ops" without sharing it. Each tag gets a page at
`/blog/<blog>/tag/<tag>/`.

## Publishing

A post is a **draft** until you publish it. On the post's page:

- **Publish now** — live immediately.
- **Schedule** — pick a date and time; a background job publishes it. (This
  needs a worker running; if one isn't, `/smallstack/status/` says so.)
- **Return to draft** — takes it off the site and the feeds.
- **Archive** — removes it from lists and feeds, but its URL keeps working for
  anyone who already linked to it.

While a post is unpublished, only you and staff can open its public URL, and
you'll see a **Draft preview** banner so there's no doubt about what a reader
would get. Everyone else gets a 404.
