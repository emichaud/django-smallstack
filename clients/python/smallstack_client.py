"""SmallStack Python client — a tiny ``requests`` wrapper for the SmallStack API.

The server-side twin of the JS ``SmallStackClient``: same auth ergonomics, same
``resource()`` CRUD helper, same field-error parsing. Useful for Streamlit apps,
internal tools, scripts, and any Python process that consumes a SmallStack backend.

No packaging required — drop this single file into your project (or add its folder
to ``sys.path``). Only dependency: ``requests``.

    from smallstack_client import SmallStackClient, ApiError

    client = SmallStackClient("http://localhost:8050")
    client.auth.login("admin", "admin")
    items = client.resource("/api/inventory/items")
    page = items.list(q="drill", expand="category", page_size=25)
    for row in page["results"]:
        print(row["sku"], row["name"])

    try:
        items.create({"name": ""})
    except ApiError as e:
        print(e.status, e.field_errors)   # {"name": ["This field is required."], ...}
"""

from __future__ import annotations

from typing import Any

import requests

__all__ = ["SmallStackClient", "ApiError", "parse_field_errors"]


def parse_field_errors(data: Any) -> dict[str, list[str]] | None:
    """Extract ``{field: [messages]}`` from a failed response body.

    SmallStack nests validation errors under ``errors``:
    ``{"errors": {"field": ["message", ...]}}``. This unwraps that (falling back
    to a flat ``{field: [...]}`` shape) and returns only the per-field arrays,
    or ``None`` if there are none (e.g. a 401/500).
    """
    if not isinstance(data, dict):
        return None
    nested = data.get("errors")
    if isinstance(nested, dict):
        data = nested
    errors: dict[str, list[str]] = {}
    for key, value in data.items():
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            errors[key] = value
    return errors or None


class ApiError(Exception):
    """Raised by ``resource()`` helpers on a non-2xx response.

    Carries the HTTP ``status``, the raw ``data`` body, and — for validation
    errors — a parsed ``field_errors`` map ready for forms.
    """

    def __init__(self, status: int, data: Any):
        super().__init__(f"SmallStack API error {status}")
        self.status = status
        self.data = data
        self.field_errors = parse_field_errors(data)


class _Resource:
    """Typed-ish CRUD helpers for one CRUDView resource. Raises ``ApiError`` on failure."""

    def __init__(self, client: "SmallStackClient", base: str):
        self._client = client
        self._base = base.rstrip("/")

    def _unwrap(self, resp: requests.Response) -> Any:
        if not resp.ok:
            data = _json_or_none(resp)
            raise ApiError(resp.status_code, data)
        return _json_or_none(resp)

    def list(self, **params: Any) -> dict:
        return self._unwrap(self._client._request("GET", f"{self._base}/", params=_clean(params)))

    def get(self, pk: int | str) -> dict:
        return self._unwrap(self._client._request("GET", f"{self._base}/{pk}/"))

    def create(self, data: dict) -> dict:
        return self._unwrap(self._client._request("POST", f"{self._base}/", json=data))

    def update(self, pk: int | str, data: dict) -> dict:
        return self._unwrap(self._client._request("PATCH", f"{self._base}/{pk}/", json=data))

    def remove(self, pk: int | str) -> None:
        self._unwrap(self._client._request("DELETE", f"{self._base}/{pk}/"))


class SmallStackClient:
    """A minimal authenticated client for a SmallStack backend.

    Args:
        base_url: Backend origin, e.g. ``"http://localhost:8050"`` (no trailing ``/api``).
        token: Optional pre-existing bearer token.
        system_token: Optional token used automatically for ``register()``.
    """

    def __init__(self, base_url: str, token: str | None = None, system_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.system_token = system_token
        self._session = requests.Session()
        self.auth = _Auth(self)

    # ---- low-level request ----
    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = kwargs.pop("headers", {}) or {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self._session.request(method, f"{self.base_url}{path}", headers=headers, timeout=30, **kwargs)

    def api(self, path: str, method: str = "GET", params: dict | None = None, json: Any = None) -> Any:
        """Low-level call that returns the parsed body and never raises on non-2xx.

        Use ``resource()`` for CRUD (it raises ``ApiError``); use this for custom endpoints.
        """
        resp = self._request(method, path, params=_clean(params or {}), json=json)
        return _json_or_none(resp)

    def resource(self, base: str) -> _Resource:
        """CRUD helpers for a resource, e.g. ``client.resource("/api/inventory/items")``."""
        return _Resource(self, base)

    def set_token(self, token: str | None) -> None:
        self.token = token


class _Auth:
    """Authentication namespace, mirroring the JS client's ``client.auth``."""

    def __init__(self, client: SmallStackClient):
        self._client = client

    def login(self, username: str, password: str) -> dict:
        """Exchange credentials for a bearer token and store it on the client."""
        resp = self._client._request("POST", "/api/auth/token/", json={"username": username, "password": password})
        data = _json_or_none(resp)
        if not resp.ok:
            raise ApiError(resp.status_code, data)
        self._client.token = data["token"]
        return data

    def me(self) -> dict:
        return self._client.api("/api/auth/me/")

    def logout(self) -> None:
        self._client.api("/api/auth/logout/", method="POST")
        self._client.token = None

    def register(self, data: dict) -> dict:
        """Register a new user; uses ``system_token`` for the call if configured."""
        prev = self._client.token
        if self._client.system_token:
            self._client.token = self._client.system_token
        resp = self._client._request("POST", "/api/auth/register/", json=data)
        body = _json_or_none(resp)
        if resp.ok and isinstance(body, dict) and body.get("token"):
            self._client.token = body["token"]
        else:
            self._client.token = prev
            if not resp.ok:
                raise ApiError(resp.status_code, body)
        return body


def _clean(params: dict) -> dict:
    """Drop None/empty values and stringify the rest."""
    return {k: str(v) for k, v in params.items() if v is not None and v != ""}


def _json_or_none(resp: requests.Response) -> Any:
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return None
