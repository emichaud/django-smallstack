"""Console forms.

These exist for one security reason above all others. ``get_list_queryset``
scopes every *read* surface, but it cannot reach the choice queryset of a
``ForeignKey`` or ``ManyToManyField`` on a generated ModelForm — so without
these classes the post form would render a ``<select>`` listing **every** blog
in the installation, and a POST naming someone else's blog would be accepted.
That is a cross-tenant *write*, and it is the one gap the read scoper leaves
open.

Narrowing the queryset is also the validation: ``ModelChoiceField`` validates
the submitted pk against its own queryset, so a forged POST fails with "not a
valid choice" rather than succeeding. One mechanism closes both the disclosure
(a dropdown of other people's blog names) and the write.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.urls import NoReverseMatch, reverse
from django.utils.functional import lazy

from . import permissions
from .models import Blog, Issue, Post, Tag


def _preview_url() -> str:
    """URL of the server-side markdown preview, or "" if the console is off.

    The editor posts here rather than rendering markdown in the browser,
    because a client-side renderer would eventually disagree with what gets
    stored — and a preview that disagrees with the published page is worse
    than no preview.
    """
    try:
        return reverse("blog_post_preview")
    except NoReverseMatch:
        return ""


# Resolved when the attribute is coerced to a string (template render), NOT
# when the form is constructed.
#
# This matters more than it looks. Forms get instantiated during startup — the
# OpenAPI/CRUD machinery builds one per view — and a `reverse()` at that moment
# forces Django to load the ROOT URLConf while the app registry is still
# initialising. Django then caches that half-built resolver forever: every app
# whose routes are registered later (Explorer builds its CRUD classes in
# `ready()`) silently ends up with zero URLs, and the failure surfaces far from
# here as a pile of NoReverseMatch errors in unrelated apps. Deferring is the
# fix; the `lazy()` wrapper keeps the NoReverseMatch guard above intact.
preview_url_lazy = lazy(_preview_url, str)


class _UserScopedForm(forms.ModelForm):
    """Base for console forms: accepts ``user=`` and scopes its own choices.

    The ``user`` kwarg is injected by ``_ScopedFormMixin._make_view`` in
    ``views.py``. ``user=None`` means no request context (a shell caller, a
    schema introspection pass), and the choices are left alone — the service
    layer is the authority in that case.
    """

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.scope_choices(user)
        # Hand the editor its preview endpoint. Progressive enhancement: with
        # JS off (or the console disabled) the textarea is simply a textarea.
        field = self.fields.get("body_markdown")
        if field is not None:
            field.widget.attrs["data-preview-url"] = preview_url_lazy()

    def scope_choices(self, user: Any) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class PostForm(_UserScopedForm):
    tag_names = forms.CharField(
        required=False,
        label="Tags",
        help_text="Comma-separated. New tags are created in this blog.",
        widget=forms.TextInput(attrs={"placeholder": "ops, on-call, postmortem"}),
    )

    class Meta:
        model = Post
        # Lifecycle and derived fields are absent on purpose — status,
        # published_at, scheduled_for, body_html and the source_* provenance
        # columns belong to the service's publish/schedule/sync operations. A
        # CRUD form that could set `status` would publish a post without
        # rendering its HTML or firing its webhook.
        fields = [
            "blog",
            "title",
            "slug",
            "body_markdown",
            "excerpt",
            "cover_image",
            "cover_alt",
            "canonical_url",
            "is_featured",
            "allow_newsletter",
        ]
        widgets = {
            "body_markdown": forms.Textarea(
                attrs={"rows": 24, "class": "vTextField blog-markdown-input", "spellcheck": "true"}
            ),
            "excerpt": forms.Textarea(attrs={"rows": 3, "class": "vTextField"}),
        }
        help_texts = {
            "slug": "Leave blank to derive it from the title.",
            "excerpt": "Leave blank to derive it from the first paragraph.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Blank is never valid, but required=True on an edit form whose blog is
        # fixed would be noise; the service re-checks either way.
        self.fields["blog"].empty_label = None  # type: ignore[attr-defined]
        self.fields["slug"].required = False
        if self.instance.pk:
            self.fields["tag_names"].initial = ", ".join(
                self.instance.tags.values_list("name", flat=True)
            )

    def scope_choices(self, user: Any) -> None:
        # editable_blogs, NOT viewable_blogs: a public blog is readable by the
        # whole internet and writable by nobody but its owner.
        self.fields["blog"].queryset = permissions.editable_blogs(user)  # type: ignore[attr-defined]

    def clean_tag_names(self) -> list[str]:
        raw = self.cleaned_data.get("tag_names") or ""
        return [part.strip() for part in raw.split(",") if part.strip()]


class BlogForm(_UserScopedForm):
    class Meta:
        model = Blog
        fields = [
            "name",
            "slug",
            "tagline",
            "description",
            "visibility",
            "newsletter_enabled",
            "newsletter_from_name",
            "newsletter_reply_to",
            "newsletter_footer_markdown",
            "double_opt_in",
            "email_template",
            "mailer_alias",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4, "class": "vTextField"}),
            "newsletter_footer_markdown": forms.Textarea(attrs={"rows": 4, "class": "vTextField"}),
        }
        help_texts = {
            "slug": "Leave blank to derive it from the name.",
            "visibility": "Private by default. 'Members' means any signed-in user.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False

    def scope_choices(self, user: Any) -> None:
        # Nothing to scope — a Blog has no FK a non-owner could target. `owner`
        # is deliberately absent from `fields`: it is stamped from the request
        # on create (see BlogCRUDView.on_form_valid), because a form field would
        # let one user assign a blog to another.
        return


class TagForm(_UserScopedForm):
    class Meta:
        model = Tag
        fields = ["blog", "name", "slug", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3, "class": "vTextField"})}
        help_texts = {"slug": "Leave blank to derive it from the name."}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False

    def scope_choices(self, user: Any) -> None:
        self.fields["blog"].queryset = permissions.editable_blogs(user)  # type: ignore[attr-defined]


class IssueForm(_UserScopedForm):
    class Meta:
        model = Issue
        # No state fields: status, queued_at, recipient_count and the body_html
        # snapshot are the send pipeline's, not a form's.
        fields = ["blog", "post", "subject", "preheader", "body_markdown"]
        widgets = {
            "body_markdown": forms.Textarea(
                attrs={"rows": 18, "class": "vTextField blog-markdown-input"}
            ),
        }
        help_texts = {
            "post": "Optional. Pick a post to send it as this issue.",
            "body_markdown": "Leave blank to use the post's body.",
        }

    def scope_choices(self, user: Any) -> None:
        self.fields["blog"].queryset = permissions.editable_blogs(user)  # type: ignore[attr-defined]
        # Only posts from blogs this user may author in, so an issue can never
        # be built from someone else's draft.
        self.fields["post"].queryset = Post.objects.filter(  # type: ignore[attr-defined]
            blog__in=permissions.editable_blogs(user)
        ).select_related("blog")
