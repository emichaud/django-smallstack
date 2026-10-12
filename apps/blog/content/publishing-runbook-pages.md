---
title: Publishing runbook pages
order: 3
---

# Publishing a runbook page to a blog

Documentation that already exists in a runbook can be published as a blog post
— useful for turning an internal write-up into something you can link to
publicly, or into a newsletter issue.

Go to **Blog → Publish a runbook page**. You'll see the runbook documents you
can read; pick one, choose a blog, and publish.

## Draft or published

Publishing as a **draft** is the default, and usually right: internal
documentation is written for colleagues who share your context, and it's worth
re-reading once as an outside reader before it goes live.

## Manual or auto sync

| Sync | What happens when the runbook page changes |
|---|---|
| **Manual** (default) | Nothing. The post is yours to edit from now on. |
| **Auto** | The post's body is replaced with the new runbook content. |

Pick **manual** if you intend to adapt the wording for readers — auto-sync
would overwrite your changes the next time anyone edits the runbook page.
Pick **auto** for something like a changelog that should always match.

You can pull the latest content into a manual post at any time with **Sync from
runbook** on the post's page.

## Frontmatter

If the runbook document starts with a frontmatter block, its `title` and
`description` become the post's title and excerpt:

```
---
title: Database Failover
description: What to do when the primary goes away at 3am.
---

# Database Failover
...
```

The block itself never appears in the post.

## What publishing does and doesn't change

Publishing **copies** the content. It does not change the runbook page, its
permissions, or who can see it — and note that a "public" runbook means
*signed-in users*, while a public **blog** means the whole internet. Putting a
document on a public blog is a real change in who can read it, which is why it
is a deliberate action against a blog whose visibility you chose.

You can only publish documents you can already read, and only into a blog you
own.
