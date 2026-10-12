---
title: Blog & Newsletter
order: 1
---

# Blog & Newsletter

A blog in SmallStack is a **channel** you publish into. Each one has an owner, a
slug, and a visibility level, and lives at `/blog/<slug>/` with its own feeds,
tags, archive and newsletter list.

## Visibility — the three-tier ladder

Visibility is not a single on/off switch, because "published" means different
things to different teams:

| Level | Who can read it | Use it for |
|---|---|---|
| **Private** | The owner and staff | Drafting. This is the default — publishing is always a deliberate act. |
| **Members** | Any signed-in user | An internal team blog: readable by every colleague, invisible to the internet. |
| **Public** | Anyone | A real public blog, indexed and syndicated. |

A post has its own lifecycle on top of that — *draft*, *scheduled*,
*published*, *archived* — and both gates apply. A published post in a private
blog is still private; a draft in a public blog is still a draft. Only the
author and staff can see an unpublished post, and they see it with a
"draft preview" banner so it is obvious which version a reader would get.

## Where things live

| Surface | URL | Who |
|---|---|---|
| Your studio | `/my/blogs/` | You — your blogs, your posts, the editor. Also under your name at the top right. |
| System blog manager | `/smallstack/blog/` | Staff — every blog, every field, subscribers and sends |
| Public reading | `/blog/` | Anyone (when the public surface is enabled) |
| Per-blog feeds | `/blog/<slug>/feed.rss`, `.atom`, `.json` | Follows the blog's visibility |
| Site-wide feed | `/feed/blog.rss` | Public blogs only |

## Writing

Posts are markdown. The renderer is deliberately conservative — see
[Writing posts](writing-posts.md) for what is supported and why raw HTML is
not. You can also publish an existing [runbook page](publishing-runbook-pages.md)
into a blog, and keep it in sync as the runbook page changes.

## Newsletter

Any blog can also be a newsletter: readers subscribe, confirm by email, and
receive posts as issues. See [Newsletter](newsletter.md) for the subscriber
lifecycle, sending, and the deliverability setup you need before a first send.

## Building on it

The built-in UI is intentionally plain. The durable part is the backend —
a service layer, REST endpoints, MCP tools, keyword search and feeds — so you
can replace the reading experience entirely and keep everything underneath.
See [Feeds and APIs](feeds-and-apis.md).
