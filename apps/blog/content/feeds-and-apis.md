---
title: Feeds and APIs
order: 5
---

# Feeds and APIs

The built-in reading pages are deliberately plain. The durable part is
underneath, so you can replace the front end entirely and keep everything else.

## Feeds

| URL | What |
|---|---|
| `/blog/<slug>/feed.rss` | One blog, RSS 2.0 |
| `/blog/<slug>/feed.atom` | One blog, Atom |
| `/blog/<slug>/feed.json` | One blog, JSON Feed 1.1 |
| `/feed/blog.rss` | Newest posts across all public blogs |
| `/blog/feed.json` | The same, as JSON Feed |

Feeds follow the blog's visibility: a public blog's feed is open, a
members-only blog's feed asks for credentials (readers can't sign in, so it
returns a `401` that a reader can retry with an API token), and a private
blog's feed is not there at all. Drafts never appear in any of them.

Blog pages advertise their feeds in the `<head>`, so a reader app finds them
from the page URL alone.

## Reading data: the public JSON API

Anonymous, no token, published content only:

```
GET /blog/api/blogs/
GET /blog/api/blogs/<slug>/posts/?page=2&tag=ops
GET /blog/api/blogs/<slug>/posts/<post-slug>/     # includes the body
GET /blog/api/blogs/<slug>/tags/
```

This is what to build a custom reader against — a React front end, a
static-site generator, another service. Responses are cacheable for a minute.

For response shapes, pagination, visibility rules, CORS and worked client code —
and for rendering posts inside this project's own templates — see
[Showing posts in your own pages](custom-pages.md).

## Writing data: the authenticated REST API

```
GET|POST      /smallstack/api/blog/posts/
GET|PUT|PATCH /smallstack/api/blog/posts/<id>/
              …and the same for blogs, tags, issues, subscriptions
```

These need an API token (mint one under **API Tokens**) and return only what
that user can see. They are the *write* surface — don't point a public reader
UI at them; it will get a 401.

Publishing is not a field you can PATCH. Use the MCP tool below, or the
console.

## AI clients (MCP)

Connect Claude to this site and it can list, read, draft and publish:

- `list_blog_posts`, `get_blog_post`, `search_blog_posts`
- `blog_draft_post` — write a draft from markdown, with tags
- `blog_publish_post` / `blog_unpublish_post`
- `blog_list_publishable_documents`, `blog_publish_runbook_document`,
  `blog_resync_post`

Each tool sees exactly what the token's owner can see.

**Sending a newsletter is not available as a tool, and subscriber addresses are
not exposed to AI clients at all.** Mailing thousands of real people stays a
deliberate human action, and a subscriber list is not something to page into a
chat client.

## Notifying other systems

Turn on a webhook endpoint under **Webhooks** and subscribe to:

| Event | When |
|---|---|
| `smallstack_blog.post.created` / `.updated` / `.deleted` | a post changes |
| `smallstack_blog.blog.created` / `.updated` | a blog changes |
| `smallstack_blog.issue.updated` | an issue's status changes, including `sent` |
| `smallstack_blog.subscription.created` / `.updated` | someone subscribes or leaves |

There is deliberately no per-delivery event: a 5,000-recipient send would emit
10,000 webhooks and drown whatever is listening. Watch the issue instead.
