# SmallStack API clients

Thin, batteries-included clients for consuming a SmallStack backend's REST API — one for
JavaScript/TypeScript frontends, one for Python. They ship **inside** SmallStack (they're only
useful with a SmallStack backend), so they're always the same version as the API they talk to.
There's nothing to `npm install` or `pip install` from a registry.

| Client | Path | For |
|--------|------|-----|
| **JavaScript / TypeScript** | [`js/`](js/) | React, Svelte, Solid, any browser SPA (npm `file:` dependency) |
| **Python** | [`python/`](python/) | Streamlit, internal tools, scripts (single-file, `requests`) |

Both give you the same shape: token auth (`login` / `me` / `logout` / `register` / …), a generic
`api()` call, and a `resource()` CRUD helper (`list` / `get` / `create` / `update` / `remove`) that
surfaces SmallStack's `{"errors": {...}}` validation errors as a ready-to-use field-error map.

## JavaScript / TypeScript

Your frontend usually sits next to your backend clone, so install the client with a local path —
no registry:

```bash
# from your frontend directory
npm install ../backend/clients/js
```

```js
import { SmallStackClient, ApiError } from 'smallstack-sdk-js'

const client = new SmallStackClient({ baseUrl: import.meta.env.VITE_API_URL, persist: true })
await client.auth.login('admin', 'admin')          // token stored + persisted for you
const items = client.resource('/api/inventory/items')
const page = await items.list({ q: 'drill', status: 'active', expand: 'category' })
try {
  await items.create({ name: '', sku: 'X1' })
} catch (e) {
  if (e instanceof ApiError) console.log(e.fieldErrors)  // { name: ["This field is required."] }
}
```

The compiled `dist/` is committed, so the `file:` install needs no build step. To develop the
client, edit `js/src/` and run `npm run build` in `js/`.

## Python

Single file, one dependency (`requests`). Copy it into your app (or add its folder to `sys.path`):

```bash
cp ../backend/clients/python/smallstack_client.py .
```

```python
from smallstack_client import SmallStackClient, ApiError

client = SmallStackClient("http://localhost:8050")
client.auth.login("admin", "admin")
items = client.resource("/api/inventory/items")
page = items.list(q="drill", expand="category")        # server-side search + FK expansion
total = items.list(sum="quantity")["sum_quantity"]     # server-side aggregation
try:
    items.create({"name": ""})
except ApiError as e:
    print(e.status, e.field_errors)                    # {"name": ["This field is required."], ...}
```

## Why bundled, not published?

These clients are inert without a SmallStack backend, so a registry release (npm/PyPI) buys only a
pipeline and version-skew risk. Bundling them here means they're the same git commit as the API,
`git clone` delivers them, and the local `file:` / copy install works offline. If you ever want to
publish, `js/package.json` is ready — nothing here prevents it.
