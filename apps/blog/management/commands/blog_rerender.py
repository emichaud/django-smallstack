"""Re-render stored post HTML after a renderer change."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.blog.models import RENDERER_VERSION, Blog, Post
from apps.blog.service import rerender_posts


class Command(BaseCommand):
    help = (
        "Re-render Post.body_html from body_markdown. By default only rows "
        "rendered by an older RENDERER_VERSION are touched."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--blog", help="Limit to one blog, by slug.")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-render every post, not just the stale ones.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Cap the rows touched.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be re-rendered and change nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        blog = None
        if options["blog"]:
            try:
                blog = Blog.objects.get(slug=options["blog"])
            except Blog.DoesNotExist as exc:
                raise CommandError(f"No blog with slug {options['blog']!r}.") from exc

        stale_only = not options["all"]

        qs = Post.objects.all()
        if blog is not None:
            qs = qs.filter(blog=blog)
        if stale_only:
            qs = qs.exclude(html_renderer_version=RENDERER_VERSION)
        pending = qs.count()

        scope = f"blog {blog.slug!r}" if blog else "all blogs"
        kind = "stale" if stale_only else "total"
        if options["dry_run"]:
            self.stdout.write(f"Would re-render {pending} {kind} post(s) in {scope}.")
            return

        if not pending:
            self.stdout.write(self.style.SUCCESS(f"Nothing to do — no {kind} posts in {scope}."))
            return

        count = rerender_posts(blog=blog, stale_only=stale_only, limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(f"Re-rendered {count} post(s) in {scope} at version {RENDERER_VERSION}.")
        )
