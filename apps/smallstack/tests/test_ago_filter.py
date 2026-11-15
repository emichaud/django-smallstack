"""``{{ dt|ago }}``: a short relative time for a table column."""

from datetime import timedelta

from django.utils import timezone

from apps.smallstack.templatetags.theme_tags import ago


def test_ago_picks_one_unit():
    now = timezone.now()
    assert ago(now - timedelta(seconds=20)) == "just now"
    assert ago(now - timedelta(minutes=4, seconds=50)) == "4m ago"
    assert ago(now - timedelta(hours=9, minutes=24)) == "9h ago"
    assert ago(now - timedelta(days=6, hours=9)) == "6d ago"
    assert ago(now - timedelta(weeks=3)) == "3w ago"
    assert ago(now - timedelta(days=150)) == "4mo ago"
    assert ago(now - timedelta(days=800)) == "2y ago"
    assert ago(None) == "" and ago(now + timedelta(hours=1)) == "just now"
