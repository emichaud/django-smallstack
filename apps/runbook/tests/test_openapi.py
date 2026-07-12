"""G3 regression: the document REST surface appears in the OpenAPI schema.

The schema opt-in needs the framework's ``register_api_path`` hook (SmallStack
≥ the release that introduced it). On an older base the package degrades to a
no-op, so this test skips rather than failing.
"""

import pytest
from django.urls import reverse

from apps.runbook import api  # noqa: F401 — import triggers schema registration

try:
    from apps.smallstack.api import register_api_path
except ImportError:  # pragma: no cover
    register_api_path = None


@pytest.mark.skipif(register_api_path is None, reason="SmallStack lacks the register_api_path hook")
@pytest.mark.django_db
def test_rest_surface_registered_in_openapi_schema(client):
    base = reverse("runbook:api_documents")  # mounted path, e.g. /smallstack/runbook/api/documents/
    detail = base.rstrip("/") + "/{runbook}/{key}/"

    spec = client.get(reverse("api-openapi-schema")).json()
    paths = spec["paths"]

    assert base in paths, "list/search path missing from schema"
    assert detail in paths, "document detail path missing from schema"

    # List is a GET; detail exposes GET/PUT/DELETE; and there's a JSON request body on PUT.
    assert "get" in paths[base]
    assert {"get", "put", "delete"} <= set(paths[detail])
    assert "requestBody" in paths[detail]["put"]

    # Sibling actions are present too.
    assert base.rstrip("/") + "/{runbook}/{key}/append/" in paths
    assert base.rstrip("/") + "/{runbook}/{key}/move/" in paths
    assert base.rstrip("/") + "/by-uid/{uid}/" in paths

    # Tagged so Swagger/ReDoc group them.
    assert paths[base]["get"]["tags"] == ["Runbook documents"]
