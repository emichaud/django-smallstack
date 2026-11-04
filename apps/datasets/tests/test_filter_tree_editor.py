"""The shared filter-tree editor: it ships as static files, and the metric
builder loads it ahead of its own script (which calls into it)."""

import re

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_editor_static_files_exist() -> None:
    assert finders.find("datasets/js/filter-tree.js")
    assert finders.find("datasets/css/filter-tree.css")


def test_editor_has_no_hard_coded_colours() -> None:
    path = finders.find("datasets/css/filter-tree.css")
    assert path
    css = open(path, encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "hex colour literal in the shared editor's CSS"
    assert "var(--" in css


def test_metric_form_mounts_the_shared_editor(client, django_user_model) -> None:
    user = django_user_model.objects.create_user(username="staff", password="pw", is_staff=True)
    client.force_login(user)
    resp = client.get(reverse("dashboards/metrics-create"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "datasets/css/filter-tree.css" in html
    assert 'id="mb-tree"' in html
    # The shared script must be listed before the builder that calls it.
    assert "datasets/js/filter-tree.js" in html
    assert html.index("datasets/js/filter-tree.js") < html.index("dashboards/js/metric-builder.js")
    # The builder no longer carries its own copy of the tree editor.
    builder = open(finders.find("dashboards/js/metric-builder.js"), encoding="utf-8").read()
    assert "SmallStackFilterTree.create" in builder
    assert "function renderLeaf" not in builder
