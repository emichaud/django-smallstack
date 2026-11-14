"""/media/ must not serve access-controlled subtrees (audit 2026-09-13, C2).

The leading-``..`` cases are the test round 2026-09-24 G1 bypass: the old
string-prefix gate collapsed them while ``serve`` did not, so the request
landed back in MEDIA_ROOT/runbook/ with the gate calling it public.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.smallstack.media import is_private_media_path


@pytest.fixture
def media(settings, tmp_path):
    root = tmp_path / "media"
    (root / "runbook" / "images").mkdir(parents=True)
    (root / "runbook" / "secret.md").write_text("private")
    (root / "runbook" / "images" / "a.png").write_text("private-img")
    (root / "profiles").mkdir()
    (root / "profiles" / "p.txt").write_text("public")
    settings.MEDIA_ROOT = str(root)
    return root


@pytest.mark.parametrize(
    "path",
    [
        "runbook/secret.md",
        "runbook",
        "RUNBOOK/secret.md",
        "profiles/../runbook/secret.md",
        "./runbook/images/a.png",
        "../media/runbook/secret.md",
        "../media/../media/runbook/secret.md",
    ],
)
def test_runbook_paths_are_private(media, path):
    assert is_private_media_path(path)


@pytest.mark.parametrize("path", ["profiles/p.txt", "runbooks-public/x.png", "../media/profiles/p.txt"])
def test_other_paths_are_public(media, path):
    assert not is_private_media_path(path)


@pytest.mark.parametrize(
    "url",
    [
        "/media/runbook/secret.md",
        "/media/../media/runbook/secret.md",
        "/media/%2e%2e/media/runbook/secret.md",
        "/media/%2E%2E/media/runbook/images/a.png",
        "/media/%2e%2e%2fmedia%2frunbook%2fsecret.md",
        "/media/%2e%2e/media/%2e%2e/media/runbook/secret.md",
    ],
)
def test_anonymous_cannot_fetch_a_runbook_file(media, url):
    response = Client().get(url)
    assert response.status_code == 404
    assert b"private" not in b"".join(getattr(response, "streaming_content", [response.content]))


def test_public_media_is_still_served(media):
    assert Client().get("/media/profiles/p.txt").status_code == 200


def test_symlink_into_private_dir_is_private(media):
    (media / "profiles" / "link").symlink_to(media / "runbook")
    assert is_private_media_path("profiles/link/secret.md")
