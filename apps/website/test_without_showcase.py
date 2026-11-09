"""The site works with ``apps/showcase`` deleted.

SmallStack's demo pages are an app a project deletes, so nothing that stays may
need it: the public topbar and the home page reverse its URLs with
``{% url … as x %}``, which comes back empty instead of raising. Here the real
URLconf runs without showcase's ``include()``, and a static check holds every
other template to the guarded form.
"""

from __future__ import annotations

import re

import pytest
from django.test import override_settings
from django.urls import URLResolver, reverse

import config.urls
from apps.smallstack import template_hygiene

pytestmark = pytest.mark.django_db

urlpatterns = [
    p
    for p in config.urls.urlpatterns
    if not (isinstance(p, URLResolver) and getattr(p.urlconf_module, "__name__", "") == "apps.showcase.urls")
]
handler404 = getattr(config.urls, "handler404", None)
handler500 = getattr(config.urls, "handler500", None)

WITHOUT_SHOWCASE = __name__


def test_this_urlconf_really_drops_showcase():
    assert len(urlpatterns) == len(config.urls.urlpatterns) - 1


@override_settings(ROOT_URLCONF=WITHOUT_SHOWCASE)
@pytest.mark.parametrize("signed_in", [False, True])
def test_the_home_page_renders_without_showcase(client, django_user_model, signed_in):
    if signed_in:
        client.force_login(django_user_model.objects.create_user("noshow", password="x", is_staff=True))
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.content.decode()
    for gone in ('href="/search/"', 'href="/prompts/"', 'href="/getting-started/"'):
        assert gone not in html
    assert client.get("/prompts/").status_code == 404


@override_settings(ROOT_URLCONF=WITHOUT_SHOWCASE)
def test_pages_on_the_public_base_render_without_showcase(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("noshow2", password="x"))
    resp = client.get(reverse("profile"))
    assert resp.status_code == 200
    assert "profile/profile.html" in [t.name for t in resp.templates]  # which extends website/base.html


@override_settings(ROOT_URLCONF=WITHOUT_SHOWCASE)
def test_the_default_error_page_is_the_framework_one(client):
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404
    assert "smallstack/css/templates/errors.css" in resp.content.decode()


_SHOWCASE_URL = re.compile(r"\{%\s*url\s+['\"]showcase:[^%]*%\}")


def test_nothing_outside_showcase_reverses_it_unguarded():
    """``{% url 'showcase:…' %}`` raises once the app is gone; ``… as x %}`` doesn't."""
    offenders = []
    for path in template_hygiene.project_templates():
        rel = path.relative_to(template_hygiene.REPO_ROOT)
        if rel.parts[:2] == ("apps", "showcase"):
            continue
        for match in _SHOWCASE_URL.finditer(path.read_text(errors="replace")):
            if not re.search(r"\sas\s+\w+\s*%\}$", match.group(0)):
                offenders.append(f"{rel}: {match.group(0)}")
    assert not offenders, "reverse showcase URLs with {% url … as x %}{% if x %}:\n" + "\n".join(offenders)
