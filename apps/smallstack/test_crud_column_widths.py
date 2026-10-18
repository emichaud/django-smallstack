"""CRUD table column widths — the type-derived defaults and the resize markup.

`.crud-table` is `table-layout: fixed`, so every header without a width gets
an equal share of the row. That made a ✓/— boolean column exactly as wide as
an email column, and the email clipped. Two layers fix it:

1. `_build_sort_headers` now emits a pixel width for naturally compact field
   types (boolean, dates, numbers, choice fields) when the view sets nothing
   in `column_widths`. Free-text and relation columns stay unset and share
   the remaining space. An explicit `column_widths` entry always wins.

2. `{% crud_table %}` renders a `.col-resizer` handle in every data header,
   tags each with `data-field`, keys the table with `data-table-key`, and
   emits the tools row that `table-resize.js` un-hides. The script is the
   behaviour; these tests pin the contract it relies on.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.smallstack.models import APIToken
from apps.smallstack.templatetags.crud_tags import _build_sort_headers, _default_column_width

pytestmark = pytest.mark.django_db

User = get_user_model()


def _widths(fields, model=APIToken, column_widths=None):
    headers = _build_sort_headers(fields, model, None, column_widths=column_widths)
    return {h["field_name"]: h.get("width") for h in headers}


# ---------------------------------------------------------------------------
# Layer 1 — type-derived defaults
# ---------------------------------------------------------------------------


def test_compact_types_get_a_pixel_default():
    widths = _widths(["is_active", "created_at", "request_count", "token_type"])
    assert widths["is_active"] == "110px"  # BooleanField
    assert widths["created_at"] == "170px"  # DateTimeField
    assert widths["request_count"] == "100px"  # PositiveIntegerField
    assert widths["token_type"] == "130px"  # CharField with choices


def test_free_text_and_relations_stay_unset():
    widths = _widths(["name", "description", "user", "id"])
    assert widths["name"] is None  # CharField, no choices
    assert widths["description"] is None  # TextField
    assert widths["user"] is None  # FK — renders str(obj), unknown width
    assert widths["id"] is None  # pk — commonly the link column, leave free


def test_non_field_attributes_get_no_default():
    # A property / method column is not a model field; it must not raise.
    assert _default_column_width(APIToken, "not_a_field") is None
    assert _default_column_width(None, "anything") is None
    assert _widths(["is_expired"])["is_expired"] is None


def test_explicit_column_widths_win_over_defaults():
    widths = _widths(["is_active", "name"], column_widths={"is_active": "25%", "name": "40%"})
    assert widths["is_active"] == "25%"
    assert widths["name"] == "40%"


def test_datetime_is_matched_before_its_date_superclass():
    # DateTimeField subclasses DateField — order in the lookup table matters.
    assert _default_column_width(User, "date_joined") == "170px"
    assert _default_column_width(User, "is_staff") == "110px"
    assert _default_column_width(User, "email") is None


# ---------------------------------------------------------------------------
# Layer 2 — the rendered markup the resize script relies on
# ---------------------------------------------------------------------------


@pytest.fixture
def staff_client(client):
    user = User.objects.create_user(username="widths-staff", password="pw", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


def test_user_list_renders_resize_contract(staff_client):
    resp = staff_client.get(reverse("manage/users-list"))
    assert resp.status_code == 200
    html = resp.content.decode()

    # Table is keyed by url_base + its field list so stale widths never replay.
    assert 'data-table-key="manage/users:username,email,name,timezone,is_staff,is_active"' in html
    # Every data header is addressable and carries a handle; the actions header is not.
    for field in ("username", "email", "name", "timezone", "is_staff", "is_active"):
        assert f'data-field="{field}"' in html
    assert html.count('class="col-resizer"') == 6
    assert 'role="separator"' in html
    # The booleans got the compact default; email (free text) did not.
    assert 'data-field="is_staff" aria-sort="none" style="width: 110px;"' in html
    assert 'data-field="email" aria-sort="none">' in html
    # Tools row ships hidden — the script reveals it (progressive enhancement).
    assert '<div class="crud-table-tools" hidden>' in html
    assert "crud-table-wrap-toggle" in html
    assert "crud-table-reset-widths" in html


def test_base_template_loads_the_resize_script(staff_client):
    resp = staff_client.get(reverse("manage/users-list"))
    assert "smallstack/js/table-resize.js" in resp.content.decode()
