"""Forms for the writing studio at ``/my/blogs/``.

Smaller than the console forms on purpose. The console is a system manager
and shows every field the model has; the studio is where a person writes, so
each form carries only what that person decides. The blog is fixed by the URL
(never a ``<select>``), lifecycle is never a field, and the newsletter block is
split out so the common case stays short.

Writes still go through ``apps.blog.service`` — these only validate.
"""

from __future__ import annotations

from typing import Any, cast

from django import forms

from .forms import preview_url_lazy
from .models import Blog, Post

_TEXT = {"class": "studio-input"}
_AREA = {"class": "studio-input studio-textarea"}


class StudioBlogForm(forms.ModelForm):
    """Create / rename a blog. Visibility is the one decision that matters."""

    class Meta:
        model = Blog
        fields = ["name", "tagline", "description", "visibility", "slug"]
        widgets = {
            "name": forms.TextInput(attrs={**_TEXT, "autofocus": True, "placeholder": "Field notes"}),
            "tagline": forms.TextInput(
                attrs={**_TEXT, "placeholder": "One line under the name, optional"}
            ),
            "description": forms.Textarea(attrs={**_AREA, "rows": 3}),
            "visibility": forms.RadioSelect(),
            "slug": forms.TextInput(attrs={**_TEXT, "placeholder": "derived from the name"}),
        }
        labels = {"slug": "Address"}
        help_texts = {
            "slug": "The part of the web address after /blog/. Leave blank to derive it.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        # Plain-language choices; the model's own labels are written for the
        # system manager.
        cast(forms.ChoiceField, self.fields["visibility"]).choices = [
            (Blog.Visibility.PRIVATE, "Only me (and staff)"),
            (Blog.Visibility.MEMBERS, "Anyone signed in"),
            (Blog.Visibility.PUBLIC, "Everyone on the internet"),
        ]


class StudioNewsletterForm(forms.ModelForm):
    """The newsletter block of blog settings, kept apart from the basics."""

    class Meta:
        model = Blog
        fields = [
            "newsletter_enabled",
            "newsletter_from_name",
            "newsletter_reply_to",
            "newsletter_footer_markdown",
            "double_opt_in",
        ]
        widgets = {
            "newsletter_from_name": forms.TextInput(attrs={**_TEXT, "placeholder": "Field Notes"}),
            "newsletter_reply_to": forms.EmailInput(attrs={**_TEXT, "placeholder": "you@example.com"}),
            "newsletter_footer_markdown": forms.Textarea(
                attrs={**_AREA, "rows": 3, "placeholder": "Postal address and why the reader is getting this"}
            ),
        }
        labels = {
            "newsletter_enabled": "Offer email subscriptions",
            "newsletter_from_name": "Sender name",
            "newsletter_reply_to": "Replies go to",
            "newsletter_footer_markdown": "Footer",
            "double_opt_in": "Ask readers to confirm by email",
        }


class CoverImageInput(forms.ClearableFileInput):
    """ClearableFileInput with a thumbnail instead of "Currently: <url>".

    Field names are unchanged (``cover_image``, ``cover_image-clear``), so this
    is purely presentational; the form's cleaned data is identical.
    """

    template_name = "blog/studio/widgets/cover_input.html"


class StudioPostForm(forms.ModelForm):
    """The editor.

    ``blog`` is not a field — it comes from the URL — and nothing to do with
    lifecycle is here either: publishing, scheduling and archiving are buttons
    that call the service, so a post can never be published by a form POST
    that skipped rendering its HTML.
    """

    tag_names = forms.CharField(
        required=False,
        label="Tags",
        widget=forms.TextInput(attrs={**_TEXT, "placeholder": "ops, postmortem"}),
    )

    class Meta:
        model = Post
        fields = [
            "title",
            "slug",
            "body_markdown",
            "excerpt",
            "cover_image",
            "cover_alt",
            "canonical_url",
            "allow_newsletter",
            "is_featured",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "studio-title",
                    "placeholder": "Title",
                    "autocomplete": "off",
                    "aria-label": "Title",
                }
            ),
            "slug": forms.TextInput(attrs={**_TEXT, "placeholder": "derived from the title"}),
            "body_markdown": forms.Textarea(
                attrs={
                    "class": "blog-markdown-input studio-body",
                    "placeholder": "Write in Markdown. Raw HTML is shown as text.",
                    "rows": 22,
                    "spellcheck": "true",
                    "aria-label": "Body",
                }
            ),
            "excerpt": forms.Textarea(
                attrs={**_AREA, "rows": 3, "placeholder": "Derived from the first paragraph if blank"}
            ),
            "cover_image": CoverImageInput(attrs={"accept": "image/png,image/jpeg,image/gif,image/webp"}),
            "cover_alt": forms.TextInput(attrs={**_TEXT, "placeholder": "Describe the image"}),
            "canonical_url": forms.URLInput(
                attrs={**_TEXT, "placeholder": "If it was first published elsewhere"}
            ),
        }
        labels = {
            "slug": "Address",
            "cover_image": "Cover image",
            "cover_alt": "Cover description",
            "canonical_url": "Originally published at",
            "allow_newsletter": "Can be sent as a newsletter",
            "is_featured": "Featured",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        # The live preview posts to the same renderer the service stores with.
        self.fields["body_markdown"].widget.attrs["data-preview-url"] = preview_url_lazy()
        if self.instance.pk:
            self.fields["tag_names"].initial = ", ".join(
                self.instance.tags.values_list("name", flat=True)
            )

    def clean_tag_names(self) -> list[str]:
        raw = self.cleaned_data.get("tag_names") or ""
        return [part.strip() for part in raw.split(",") if part.strip()]
