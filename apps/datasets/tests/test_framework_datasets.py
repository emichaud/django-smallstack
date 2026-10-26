"""The bundled ``smallstack_*`` datasets — one lightweight view per module.

These guard the contract downstream reporting tools build on: every bundled
dataset registers under the namespaced prefix, declares only real columns,
never exposes a credential/secret/payload column, and answers schema / rows /
count / scalar on an empty database. Plus the two exposure settings.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.datasets.core import get_dataset, list_datasets
from apps.datasets.framework import (
    FRAMEWORK_PREFIX,
    framework_dataset,
    framework_dataset_keys,
    is_framework_dataset,
)
from apps.datasets.registry import get_def, unregister

pytestmark = pytest.mark.django_db

User = get_user_model()

# Field names that must never be a column on a bundled dataset. A dataset
# projects rows onto its declared columns, so this list is the leak boundary.
FORBIDDEN_COLUMNS = {
    "password",
    "hashed_key",
    "raw_key",
    "code",
    "code_hash",
    "code_challenge",
    "secret",
    "headers",
    "payload",
    "body",
    "context",
    "kwargs",
    "extra",
    "exc_text",
    "body_markdown",
    "body_html",
    "content_text",
    "raw",
}

# Every module that creates data ships at least these.
EXPECTED_KEYS = {
    "smallstack_api_tokens",
    "smallstack_backups",
    "smallstack_users",
    "smallstack_user_profiles",
    "smallstack_requests",
    "smallstack_log_records",
    "smallstack_heartbeats",
    "smallstack_heartbeat_daily",
    "smallstack_task_attempts",
    "smallstack_scheduled_jobs",
    "smallstack_scheduled_job_runs",
    "smallstack_webhook_deliveries",
    "smallstack_webhook_receipts",
    "smallstack_notifications",
    "smallstack_approval_requests",
    "smallstack_collected_items",
    "smallstack_blog_posts",
    "smallstack_blog_issues",
    "smallstack_runbook_documents",
}


def test_every_module_dataset_is_registered() -> None:
    keys = set(framework_dataset_keys())
    missing = EXPECTED_KEYS - keys
    assert not missing, f"bundled datasets missing: {sorted(missing)}"
    # They're all in the picker and all published to REST.
    listed = {d["key"] for d in list_datasets(api_only=True)}
    assert keys <= listed


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_bundled_dataset_declares_only_real_columns(key: str) -> None:
    """A column name typo would silently type as ``string`` and serialize as
    ``None`` — catch it at the source."""
    ds = get_dataset(key)
    assert ds is not None
    model_fields = {f.name for f in ds.model._meta.fields}
    declared = ds.column_names()
    assert declared, key
    bogus = [c for c in declared if c not in model_fields]
    assert not bogus, f"{key}: not model fields: {bogus}"
    bad_filters = [c for c in ds.filter_field_names() if c not in declared]
    assert not bad_filters, f"{key}: filterable but not a column: {bad_filters}"
    for mname, spec in ds.declared_measures().items():
        assert spec["num"] in model_fields and spec["denom"] in model_fields, (key, mname)


def test_no_bundled_dataset_exposes_a_secret_or_payload_column() -> None:
    for key in framework_dataset_keys():
        ds = get_dataset(key)
        assert ds is not None
        leaked = set(ds.column_names()) & FORBIDDEN_COLUMNS
        assert not leaked, f"{key} exposes {sorted(leaked)}"


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_bundled_dataset_answers_every_read_path(key: str) -> None:
    """Schema, rows, count and scalar all answer and agree. The DB is mostly
    empty, but not entirely: code-declared ``@scheduled`` jobs materialise
    through migrations, so assert consistency rather than emptiness."""
    ds = get_dataset(key)
    assert ds is not None
    schema = ds.schema()
    assert schema["key"] == key
    assert schema["label"] and schema["description"]
    names = {c["name"] for c in schema["columns"]}
    assert set(ds.column_names()) <= names
    total = ds.count()
    assert len(ds.rows(limit=None)) == total
    assert ds.scalar(agg="count") == total
    for row in ds.rows(limit=5):
        assert set(ds.column_names()) <= set(row)
    # Every advertised text filter round-trips without raising.
    flt = {f["name"]: "zzz-no-such-value" for f in schema["filters"] if f["type"] == "text"}
    if flt:
        assert ds.rows(filters=flt, limit=5) == []


def test_users_dataset_rows_carry_no_password_hash() -> None:
    User.objects.create_user(username="ds-user", email="ds@example.com", password="pw-123456")
    ds = get_dataset("smallstack_users")
    assert ds is not None
    (row,) = ds.rows(filters={"username": "ds-user"})
    assert row["username"] == "ds-user"
    assert "password" not in row
    assert not any("pw-123456" in str(v) for v in row.values())


def test_blog_issue_ratio_measures_roll_up_from_summed_parts() -> None:
    from apps.blog.models import Blog, Issue

    owner = User.objects.create_user(username="ds-owner", password="pw-123456")
    blog = Blog.objects.create(owner=owner, name="Ratio", slug="ratio")
    Issue.objects.create(blog=blog, subject="a", recipient_count=100, sent_count=90, failed_count=10)
    Issue.objects.create(blog=blog, subject="b", recipient_count=300, sent_count=150, failed_count=150)
    ds = get_dataset("smallstack_blog_issues")
    assert ds is not None
    # (90+150)/(100+300) = 60%, not the 75% an average-of-percentages would give.
    assert ds.scalar(measure="sent_pct", filters={"blog": str(blog.pk)}) == pytest.approx(60.0)
    assert ds.scalar(measure="failed_pct", filters={"blog": str(blog.pk)}) == pytest.approx(40.0)


def test_rest_list_includes_bundled_datasets_for_staff(client) -> None:
    staff = User.objects.create_user(username="ds-staff", password="pw-123456", is_staff=True)
    client.force_login(staff)
    resp = client.get("/smallstack/datasets/")
    assert resp.status_code == 200
    keys = {d["key"] for d in resp.json()["results"]}
    assert EXPECTED_KEYS <= keys
    resp = client.get("/smallstack/datasets/smallstack_requests/")
    assert resp.status_code == 200
    body = resp.json()
    # The activity middleware logged the list call above, so the dataset
    # already has a row — and it is projected onto the declared columns.
    assert body["total"] >= 1
    assert body["total"] == body["count"]
    paths = {r["path"] for r in body["results"]}
    assert "/smallstack/datasets/" in paths
    assert "user_agent" not in body["results"][0]


# --- the helper + its settings ----------------------------------------------


def test_prefix_is_enforced() -> None:
    assert is_framework_dataset(f"{FRAMEWORK_PREFIX}x") and not is_framework_dataset("x")
    with pytest.raises(ValueError):
        framework_dataset("tickets", label="t", description="d", columns=["id"])
    with pytest.raises(ValueError):
        framework_dataset("smallstack_tickets", label="t", description="d", columns=[])


def test_disabled_setting_registers_nothing() -> None:
    from apps.activity.models import RequestLog

    key = "smallstack_t_disabled"
    try:
        with override_settings(SMALLSTACK_FRAMEWORK_DATASETS_ENABLED=False):

            @framework_dataset(key, label="t", description="d", columns=["path"])
            def _fn():  # type: ignore[no-untyped-def]
                return RequestLog.objects.all()

        assert get_def(key) is None
        assert _fn().model is RequestLog  # the function itself is untouched
    finally:
        unregister(key)


def test_mcp_setting_controls_tool_exposure() -> None:
    from apps.activity.models import RequestLog

    for flag in (False, True):
        key = f"smallstack_t_mcp_{int(flag)}"
        try:
            with override_settings(SMALLSTACK_FRAMEWORK_DATASETS_MCP=flag):
                framework_dataset(key, label="t", description="d", columns=["path"])(lambda: RequestLog.objects.all())
            dfn = get_def(key)
            assert dfn is not None
            assert dfn.enable_api is True
            assert dfn.enable_mcp is flag
            assert dfn.mcp_access == "staff"
        finally:
            unregister(key)
