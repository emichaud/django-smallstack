"""The writing studio at /my/blogs/.

Same envelope as the console — anonymous out, owner in, non-owner **404** —
plus the one thing the studio adds: lifecycle buttons that save the editor
first and then transition in the same request, so nothing typed is lost on
the way to publishing and "publish" still has a single implementation.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.blog.models import Blog, Post

pytestmark = pytest.mark.django_db

STUDIO = "/my/blogs"


# ── Envelope ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/", "/new/", "/field-notes/", "/field-notes/posts/new/"])
def test_anonymous_is_redirected_to_login(client, blog, path):
    response = client.get(STUDIO + path)
    assert response.status_code == 302
    assert "/login" in response.url


def test_owner_sees_their_blog_and_posts(client, owner, blog, post, draft):
    client.force_login(owner)
    body = client.get(f"{STUDIO}/").content.decode()
    assert blog.name in body
    assert draft.title in body, "drafts lead the dashboard"
    assert post.title in body


@pytest.mark.parametrize("suffix", ["", "settings/", "posts/new/"])
def test_a_stranger_gets_404_for_someone_elses_blog(client, other_user, blog, suffix):
    client.force_login(other_user)
    assert client.get(f"{STUDIO}/{blog.slug}/{suffix}").status_code == 404


def test_a_stranger_gets_404_for_someone_elses_post(client, other_user, blog, draft):
    client.force_login(other_user)
    assert client.get(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/").status_code == 404
    assert client.post(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/delete/").status_code == 404
    assert Post.objects.filter(pk=draft.pk).exists()


def test_a_reader_of_a_public_blog_is_still_not_its_author(client, other_user, blog):
    """Public means readable by everyone; the studio stays the owner's."""
    client.force_login(other_user)
    assert client.get(f"{STUDIO}/{blog.slug}/").status_code == 404
    assert blog.name not in client.get(f"{STUDIO}/").content.decode()


def test_a_post_cannot_be_opened_under_the_wrong_blog(client, owner, blog, draft):
    """Both the blog slug and the pk have to match — a URL naming a blog you
    own with a post from another blog must not resolve."""
    other = Blog.objects.create(name="Second", slug="second", owner=owner)
    client.force_login(owner)
    assert client.get(f"{STUDIO}/{other.slug}/posts/{draft.pk}/").status_code == 404


# ── Blogs ───────────────────────────────────────────────────────────────────


def test_creating_a_blog_lands_in_the_editor(client, owner):
    client.force_login(owner)
    response = client.post(
        f"{STUDIO}/new/", {"name": "Field Notes", "visibility": "public", "tagline": "", "slug": ""}
    )
    blog = Blog.objects.get(name="Field Notes")
    assert blog.owner == owner
    assert blog.visibility == Blog.Visibility.PUBLIC
    assert response.status_code == 302
    assert response.url == f"{STUDIO}/{blog.slug}/posts/new/"


def test_the_empty_dashboard_invites_a_first_blog(client, owner):
    client.force_login(owner)
    assert "Create your first blog" in client.get(f"{STUDIO}/").content.decode()


def test_settings_basics_rename_and_change_visibility(client, owner, private_blog):
    client.force_login(owner)
    client.post(
        f"{STUDIO}/{private_blog.slug}/settings/",
        {"which": "basics", "name": "Renamed", "visibility": "public", "tagline": "t",
         "description": "", "slug": ""},
    )
    private_blog.refresh_from_db()
    assert private_blog.name == "Renamed"
    assert private_blog.slug == "renamed"
    assert private_blog.visibility == Blog.Visibility.PUBLIC


def test_settings_newsletter_block_saves_independently(client, owner, blog):
    client.force_login(owner)
    client.post(
        f"{STUDIO}/{blog.slug}/settings/",
        {"which": "newsletter", "newsletter_enabled": "on", "newsletter_from_name": "Field Notes",
         "newsletter_reply_to": "", "newsletter_footer_markdown": "", "double_opt_in": "on"},
    )
    blog.refresh_from_db()
    assert blog.newsletter_enabled
    assert blog.newsletter_from_name == "Field Notes"
    assert blog.name == "Field Notes", "the basics form was not touched"


# ── The editor ──────────────────────────────────────────────────────────────


def _editor_post(**overrides):
    data = {
        "action": "save", "title": "From the studio", "slug": "", "excerpt": "",
        "body_markdown": "# From the studio\n\nWritten here.", "tag_names": "ops, studio",
        "cover_alt": "", "canonical_url": "", "allow_newsletter": "on", "scheduled_for": "",
    }
    data.update(overrides)
    return data


def test_save_creates_a_draft_through_the_service(client, owner, blog):
    client.force_login(owner)
    response = client.post(f"{STUDIO}/{blog.slug}/posts/new/", _editor_post())
    post = Post.objects.get(title="From the studio")

    assert response.status_code == 302
    assert response.url == f"{STUDIO}/{blog.slug}/posts/{post.pk}/"
    assert post.status == Post.Status.DRAFT
    assert post.author == owner
    assert "<p>Written here.</p>" in post.body_html, "rendered via the service"
    assert "<h1" not in post.body_html, "duplicate title heading stripped"
    assert post.excerpt == "Written here."
    assert set(post.tags.values_list("slug", flat=True)) == {"ops", "studio"}


def test_publish_saves_then_publishes_in_one_request(client, owner, blog):
    """The point of `action`: the words you just typed go live, not the last
    saved version."""
    client.force_login(owner)
    client.post(f"{STUDIO}/{blog.slug}/posts/new/", _editor_post(action="publish"))
    post = Post.objects.get(title="From the studio")
    assert post.status == Post.Status.PUBLISHED
    assert post.is_live


def test_publish_from_the_editor_saves_unsaved_edits_first(client, owner, blog, draft):
    client.force_login(owner)
    client.post(
        f"{STUDIO}/{blog.slug}/posts/{draft.pk}/",
        _editor_post(action="publish", title="Unfinished", body_markdown="Final words."),
    )
    draft.refresh_from_db()
    assert draft.status == Post.Status.PUBLISHED
    assert "Final words." in draft.body_html


def test_unpublish_returns_to_draft(client, owner, blog, post):
    client.force_login(owner)
    client.post(f"{STUDIO}/{blog.slug}/posts/{post.pk}/",
                _editor_post(action="unpublish", title=post.title, body_markdown=post.body_markdown))
    post.refresh_from_db()
    assert post.status == Post.Status.DRAFT
    assert post.published_at is None


def test_schedule_sets_a_future_time(client, owner, blog, draft):
    when = timezone.localtime(timezone.now() + timezone.timedelta(days=2))
    client.force_login(owner)
    client.post(
        f"{STUDIO}/{blog.slug}/posts/{draft.pk}/",
        _editor_post(action="schedule", title=draft.title, body_markdown="x",
                     scheduled_for=when.strftime("%Y-%m-%dT%H:%M")),
    )
    draft.refresh_from_db()
    assert draft.status == Post.Status.SCHEDULED
    assert draft.scheduled_for is not None


def test_schedule_without_a_time_reports_and_keeps_the_draft(client, owner, blog, draft):
    client.force_login(owner)
    response = client.post(
        f"{STUDIO}/{blog.slug}/posts/{draft.pk}/",
        _editor_post(action="schedule", title=draft.title, body_markdown="x", scheduled_for=""),
    )
    assert response.status_code == 200
    assert "Pick a date and time" in response.content.decode()
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT


def test_archive_from_the_editor(client, owner, blog, post):
    client.force_login(owner)
    client.post(f"{STUDIO}/{blog.slug}/posts/{post.pk}/",
                _editor_post(action="archive", title=post.title, body_markdown=post.body_markdown))
    post.refresh_from_db()
    assert post.status == Post.Status.ARCHIVED


def test_an_unknown_action_is_treated_as_save(client, owner, blog, draft):
    client.force_login(owner)
    client.post(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/",
                _editor_post(action="detonate", title="Renamed", body_markdown="x"))
    draft.refresh_from_db()
    assert draft.title == "Renamed"
    assert draft.status == Post.Status.DRAFT


def test_the_editor_never_accepts_status_as_a_field(client, owner, blog, draft):
    client.force_login(owner)
    client.post(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/",
                _editor_post(title=draft.title, body_markdown="x", status="published"))
    draft.refresh_from_db()
    assert draft.status == Post.Status.DRAFT


def test_delete_removes_the_post(client, owner, blog, draft):
    client.force_login(owner)
    response = client.post(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/delete/")
    assert response.status_code == 302
    assert not Post.objects.filter(pk=draft.pk).exists()


def test_the_editor_page_carries_the_preview_endpoint_and_assets(client, owner, blog):
    client.force_login(owner)
    body = client.get(f"{STUDIO}/{blog.slug}/posts/new/").content.decode()
    assert 'data-preview-url="/smallstack/blog/posts/preview/"' in body
    assert "blog/studio.css" in body
    assert "blog/blog.js" in body
    assert 'name="action"' in body


def test_the_blog_page_filters_by_status(client, owner, blog, post, draft):
    client.force_login(owner)
    drafts = client.get(f"{STUDIO}/{blog.slug}/?status=draft").content.decode()
    assert draft.title in drafts
    assert f'/posts/{post.pk}/' not in drafts


# ── Integration points ──────────────────────────────────────────────────────


def test_nav_entry_sits_in_the_main_section(client, owner, blog):
    client.force_login(owner)
    body = client.get(f"{STUDIO}/").content.decode()
    assert 'href="/my/blogs/"' in body
    assert "My blogs" in body


def test_the_user_dropdown_links_to_the_studio(client, owner):
    client.force_login(owner)
    body = client.get("/smallstack/runbook/").content.decode()
    assert "My blogs" in body
    assert 'href="/my/blogs/"' in body


def test_the_profile_lists_blogs_the_viewer_may_see(client, owner, other_user, blog, private_blog):
    page = f"/profile/{owner.username}/"
    client.force_login(other_user)
    body = client.get(page).content.decode()
    assert blog.name in body
    assert private_blog.name not in body, "a stranger must not see a private blog's name"

    client.force_login(owner)
    body = client.get(page).content.decode()
    assert private_blog.name in body
    assert 'href="/my/blogs/"' in body


def test_the_profile_card_survives_a_user_with_no_blogs(client, owner, other_user):
    client.force_login(other_user)
    assert client.get(f"/profile/{owner.username}/").status_code == 200


# ── Layout toggle and the themed date picker ────────────────────────────────


def test_the_dashboard_and_blog_page_offer_a_cards_view(client, owner, blog, post):
    client.force_login(owner)
    for path in (f"{STUDIO}/", f"{STUDIO}/{blog.slug}/"):
        body = client.get(path).content.decode()
        assert 'data-view="cards"' in body, path
        assert 'data-view="list"' in body, path
        assert "blog/studio.js" in body, path


def test_rows_carry_the_excerpt_so_cards_need_no_second_query(client, owner, blog, post):
    """One markup, two layouts — the excerpt is in the row and CSS decides."""
    client.force_login(owner)
    body = client.get(f"{STUDIO}/{blog.slug}/").content.decode()
    assert 'class="studio-row-excerpt"' in body
    assert post.excerpt in body


def test_the_schedule_input_uses_the_themed_picker(client, owner, blog, draft):
    """The browser's native calendar indicator is drawn dark-on-dark in the
    dark themes; the framework wrapper hides it and supplies a themed button."""
    client.force_login(owner)
    body = client.get(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/").content.decode()
    assert 'class="crud-date-wrapper studio-date"' in body
    assert 'data-picker-for="studio-when"' in body


def test_cards_show_the_cover_image_when_a_post_has_one(client, owner, blog, post, draft):
    from django.core.files.base import ContentFile

    post.cover_image.save("c.png", ContentFile(b"\x89PNG\r\n\x1a\n"), save=False)
    post.cover_alt = "A notebook"
    post.save(update_fields=["cover_image", "cover_alt"])

    client.force_login(owner)
    body = client.get(f"{STUDIO}/{blog.slug}/").content.decode()
    assert body.count('class="studio-row-cover"') == 1, "only the post with a cover gets one"
    assert post.cover_image.url in body


def test_the_cover_field_shows_a_thumbnail_not_a_url(client, owner, blog, post):
    from django.core.files.base import ContentFile

    post.cover_image.save("c.png", ContentFile(b"\x89PNG\r\n\x1a\n"), save=False)
    post.cover_alt = "A notebook"
    post.save(update_fields=["cover_image", "cover_alt"])

    client.force_login(owner)
    body = client.get(f"{STUDIO}/{blog.slug}/posts/{post.pk}/").content.decode()
    assert "Currently:" not in body, "Django's stock ClearableFileInput leaked through"
    assert f'src="{post.cover_image.url}"' in body
    # Clearing still works through the standard field name.
    assert 'name="cover_image-clear"' in body


def test_removing_the_cover_through_the_editor(client, owner, blog, post):
    from django.core.files.base import ContentFile

    post.cover_image.save("c.png", ContentFile(b"\x89PNG\r\n\x1a\n"), save=False)
    post.cover_alt = "A notebook"
    post.save(update_fields=["cover_image", "cover_alt"])

    client.force_login(owner)
    client.post(f"{STUDIO}/{blog.slug}/posts/{post.pk}/",
                _editor_post(title=post.title, body_markdown=post.body_markdown,
                             **{"cover_image-clear": "on"}))
    post.refresh_from_db()
    assert not post.cover_image


# ── Header band, stat cards, and the public TOC rail ────────────────────────


def test_studio_list_pages_use_the_header_band_like_runbook_and_help(client, owner, blog):
    client.force_login(owner)
    for path in (f"{STUDIO}/", f"{STUDIO}/{blog.slug}/", f"{STUDIO}/{blog.slug}/settings/", f"{STUDIO}/new/"):
        body = client.get(path).content.decode()
        assert 'class="page-header-bleed' in body, path


def test_the_editor_stays_flat(client, owner, blog, draft):
    """Focused work surfaces don't get the band; the sheet is the surface."""
    client.force_login(owner)
    body = client.get(f"{STUDIO}/{blog.slug}/posts/{draft.pk}/").content.decode()
    assert 'class="page-header-bleed' not in body


def test_the_dashboard_uses_stat_cards_not_a_sentence(client, owner, blog, post, draft):
    client.force_login(owner)
    body = client.get(f"{STUDIO}/").content.decode()
    assert body.count('class="stat-card') >= 4
    assert "1 live, 1 in draft" not in body


def test_a_long_post_gets_an_on_this_page_rail(client, blog, owner):
    from apps.blog import service

    body_md = "\n\n".join(f"## Section {i}\n\nText." for i in range(4))
    p = service.create_post(blog, title="Long", body_markdown=body_md, actor=owner)
    service.publish_post(p, actor=owner)
    html = client.get(f"/blog/{blog.slug}/{p.slug}/").content.decode()
    assert 'class="blog-toc"' in html
    assert "On this page" in html


def test_a_short_post_gets_no_rail(client, blog, post):
    html = client.get(f"/blog/{blog.slug}/{post.slug}/").content.decode()
    assert 'class="blog-toc"' not in html
