"""Custom MCP tools for the blog.

The CRUDView flags already emit ``list_/get_/create_/update_/delete_`` for
Blog, Post and Issue, plus ``search_blog_posts``. These five fill the gaps
those cannot:

* **Publishing is not a field.** ``update_blog_post`` deliberately cannot set
  ``status`` — publishing has to render the HTML, stamp ``published_at`` and
  fire the webhook, which a generic field write would skip. So it gets a verb.
* **The runbook bridge** is the integration this app exists for, and an agent
  needs a way to discover what it may publish as well as to publish it.

Equally deliberate: **there is no send tool.** Queueing a blast to thousands
of real people is not something a tool call should be able to do, and the
subscriber models are not exposed to MCP at all — a tool that pages email
addresses into an LLM client is a data-exfiltration surface, not a feature.

Handlers are thin and sync; the ``do_*`` delegates take an explicit actor so
they are testable without an MCP dispatch context (runbook's pattern).
"""

from __future__ import annotations

from typing import Any, Optional

from . import permissions, service
from .models import Blog, Post


def _post_payload(post: Post) -> dict[str, Any]:
    return {
        "uid": str(post.uid),
        "id": post.pk,
        "blog": post.blog.slug,
        "title": post.title,
        "slug": post.slug,
        "status": post.status,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "url": post.public_url or None,
        "tags": list(post.tags.values_list("name", flat=True)),
        "source_document_uid": str(post.source_document_uid)
        if post.source_document_uid
        else None,
        "source_version": post.source_version,
    }


def _resolve_post(identifier: Any, actor: Any) -> Post:
    """Find a post by uid or id, within what ``actor`` may edit."""
    qs = Post.objects.select_related("blog")
    post = None
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        post = qs.filter(pk=int(identifier)).first()
    elif identifier:
        post = qs.filter(uid=str(identifier)).first()
    if post is None or not permissions.can_edit_post(actor, post):
        # Same answer either way: whether a post exists is not information an
        # agent without access should be able to probe for.
        raise service.PostNotFound(f"No editable post {identifier!r}.")
    return post


def _resolve_blog(slug: Any, actor: Any) -> Blog:
    blog = permissions.editable_blogs(actor).filter(slug=str(slug)).first()
    if blog is None:
        raise service.BlogNotFound(f"No blog {slug!r} you can write to.")
    return blog


# -- Testable delegates ------------------------------------------------------


def do_draft_post(
    actor: Any,
    *,
    blog: str,
    title: str,
    body_markdown: str = "",
    excerpt: str = "",
    tags: Optional[list] = None,
) -> dict:
    """Create a draft. Takes tag *names* and derives the slug and excerpt —
    the ergonomic difference between "draft a post about X" working and not."""
    try:
        target = _resolve_blog(blog, actor)
        post = service.create_post(
            target,
            title=title,
            body_markdown=body_markdown,
            excerpt=excerpt,
            tags=[str(t) for t in (tags or [])],
            actor=actor,
        )
    except service.BlogServiceError as exc:
        return {"error": str(exc)}
    return _post_payload(post)


def do_publish_post(actor: Any, *, post: Any) -> dict:
    try:
        resolved = service.publish_post(_resolve_post(post, actor), actor=actor)
    except service.BlogServiceError as exc:
        return {"error": str(exc)}
    return _post_payload(resolved)


def do_unpublish_post(actor: Any, *, post: Any) -> dict:
    try:
        resolved = service.unpublish_post(_resolve_post(post, actor), actor=actor)
    except service.BlogServiceError as exc:
        return {"error": str(exc)}
    return _post_payload(resolved)


def do_list_publishable_documents(
    actor: Any, *, runbook: Optional[str] = None, query: Optional[str] = None, limit: int = 50
) -> dict:
    """The read half of the bridge, so an agent can discover what it may
    publish instead of guessing runbook keys."""
    qs = service.publishable_documents(actor)
    if runbook:
        qs = qs.filter(runbook__slug=runbook)
    if query:
        qs = qs.filter(title__icontains=query)
    return {
        "results": [
            {
                "uid": str(doc.uid),
                "key": doc.key,
                "title": doc.title,
                "runbook": doc.runbook.slug if doc.runbook_id and doc.runbook else None,
                "version": doc.version,
            }
            for doc in qs.order_by("title")[: max(1, min(int(limit or 50), 200))]
        ]
    }


def do_publish_runbook_document(
    actor: Any,
    *,
    document: str,
    blog: str,
    slug: str = "",
    status: str = "draft",
    sync: str = "manual",
) -> dict:
    """Publish a runbook document into a blog.

    Resolution goes through ``runbook.service`` + ``runbook.permissions``, so
    an agent cannot publish a document its own token could not read.
    """
    try:
        target = _resolve_blog(blog, actor)
        post = service.publish_document(
            document, target, slug=slug, status=status, sync=sync, actor=actor
        )
    except service.BlogServiceError as exc:
        return {"error": str(exc)}
    return _post_payload(post)


def do_resync_post(actor: Any, *, post: Any, force: bool = True) -> dict:
    try:
        resolved = service.resync_post(_resolve_post(post, actor), actor=actor, force=force)
    except service.BlogServiceError as exc:
        return {"error": str(exc)}
    return _post_payload(resolved)


# -- MCP registration (only when the SmallStack MCP app is present) ----------

try:
    from apps.mcp.server import current_context, tool
except ImportError:  # pragma: no cover - MCP app not installed downstream

    def register_blog_tools() -> None:
        """No-op — the SmallStack MCP app isn't installed."""

else:

    def _actor() -> Any:
        return current_context().user

    _POST_REF = {
        "post": {
            "type": "string",
            "description": "Post uid (preferred) or numeric id.",
        }
    }

    def register_blog_tools() -> None:
        """Register the ``blog_*`` tools. Idempotent — ``tool`` dedups by name."""
        tool(
            "blog_draft_post",
            "Create a DRAFT blog post from markdown. Takes tag names and derives the "
            "slug and excerpt. Publishing is a separate step — call blog_publish_post.",
            {
                "type": "object",
                "properties": {
                    "blog": {"type": "string", "description": "Blog slug to write into."},
                    "title": {"type": "string", "description": "Post title."},
                    "body_markdown": {"type": "string", "description": "Markdown body."},
                    "excerpt": {
                        "type": "string",
                        "description": "Summary for lists and feeds; derived when omitted.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tag names; created in this blog if new.",
                    },
                },
                "required": ["blog", "title"],
            },
            write=True,
            requires_access="readwrite",
        )(lambda args: do_draft_post(
            _actor(),
            blog=args.get("blog", ""),
            title=args.get("title", ""),
            body_markdown=args.get("body_markdown", ""),
            excerpt=args.get("excerpt", ""),
            tags=args.get("tags") or [],
        ))

        tool(
            "blog_publish_post",
            "Publish a draft so it is visible to readers. A plain update cannot do this: "
            "publishing renders the HTML, stamps the publication time and fires the "
            "webhook, so it is its own verb.",
            {"type": "object", "properties": dict(_POST_REF), "required": ["post"]},
            write=True,
            requires_access="readwrite",
        )(lambda args: do_publish_post(_actor(), post=args.get("post")))

        tool(
            "blog_unpublish_post",
            "Return a published post to draft, removing it from the public site and feeds.",
            {"type": "object", "properties": dict(_POST_REF), "required": ["post"]},
            write=True,
            requires_access="readwrite",
        )(lambda args: do_unpublish_post(_actor(), post=args.get("post")))

        tool(
            "blog_list_publishable_documents",
            "List runbook documents you may publish into a blog. Use this to find a "
            "document's uid before calling blog_publish_runbook_document.",
            {
                "type": "object",
                "properties": {
                    "runbook": {"type": "string", "description": "Limit to one runbook slug."},
                    "query": {"type": "string", "description": "Case-insensitive title filter."},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            requires_access="readonly",
        )(lambda args: do_list_publishable_documents(
            _actor(),
            runbook=args.get("runbook"),
            query=args.get("query"),
            limit=int(args.get("limit") or 50),
        ))

        tool(
            "blog_publish_runbook_document",
            "Publish a runbook document into a blog as a post. Frontmatter title and "
            "description become the post's title and excerpt. sync=auto keeps the post "
            "following the runbook page; manual leaves it yours to edit.",
            {
                "type": "object",
                "properties": {
                    "document": {"type": "string", "description": "Runbook document uid."},
                    "blog": {"type": "string", "description": "Blog slug to publish into."},
                    "slug": {"type": "string", "description": "Optional post slug."},
                    "status": {
                        "type": "string",
                        "enum": ["draft", "published"],
                        "default": "draft",
                        "description": "Draft by default — review before it goes live.",
                    },
                    "sync": {
                        "type": "string",
                        "enum": ["manual", "auto"],
                        "default": "manual",
                    },
                },
                "required": ["document", "blog"],
            },
            write=True,
            requires_access="readwrite",
        )(lambda args: do_publish_runbook_document(
            _actor(),
            document=args.get("document", ""),
            blog=args.get("blog", ""),
            slug=args.get("slug", ""),
            status=args.get("status") or "draft",
            sync=args.get("sync") or "manual",
        ))

        tool(
            "blog_resync_post",
            "Pull the latest runbook content into a post that was published from a "
            "runbook document.",
            {
                "type": "object",
                "properties": {
                    **_POST_REF,
                    "force": {"type": "boolean", "default": True},
                },
                "required": ["post"],
            },
            write=True,
            requires_access="readwrite",
        )(lambda args: do_resync_post(
            _actor(), post=args.get("post"), force=bool(args.get("force", True))
        ))

    # Register at import time so the tools are present at startup.
    register_blog_tools()
