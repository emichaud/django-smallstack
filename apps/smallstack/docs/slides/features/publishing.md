# Runbook, blog, newsletter & feeds

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Publishing is a platform surface too.

- **Runbook** — versioned markdown documents with a split editor, slide and step views, templates and search
- **Blogs** — per-user channels with a private / members / public visibility ladder, a compact writing studio at `/my/blogs/`, and a system console under `/smallstack/blog/`
- **Publish a runbook page into a blog**, optionally resyncing when the page changes
- **Newsletter** — double opt-in subscribers, one-click unsubscribe, and a durable batched sender that resumes if the worker dies mid-send
- **Readers get** `/blog/`, a sitemap and an anonymous JSON API
- **Feeds are a publishing surface** — RSS/Atom/JSON per blog and site-wide, built as curated `Feed`s over scoped querysets; the same `register_feed()` serves a podcast or changelog, with enclosures via `FeedItem(extra_kwargs=…)`

</div>
<div class="col" markdown="1">

```python
post = service.publish_document(
    document, blog, sync="auto"
)
issue = service.create_issue_from_post(post)
service.queue_issue(issue)   # Delivery rows are the ledger
```

</div>
</div>
