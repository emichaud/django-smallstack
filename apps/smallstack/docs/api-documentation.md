---
title: API Documentation (Swagger & ReDoc)
description: Interactive API docs with Swagger UI and ReDoc — no packages required
---

# API Documentation (Swagger & ReDoc)

{{ project_name }} includes built-in interactive API documentation powered by [Swagger UI](https://swagger.io/tools/swagger-ui/) and [ReDoc](https://redocly.com/redoc/). Both render your API's OpenAPI spec as browsable, interactive documentation — no Python packages to install, no code to maintain.

## Try It Now

| URL | Tool | What it does |
|-----|------|-------------|
| `/api/docs/` | Swagger UI | Interactive "try it out" API explorer — send real requests from the browser |
| `/api/redoc/` | ReDoc | Clean, readable API reference with a three-panel layout |
| `/api/schema/openapi.json` | Raw spec | The OpenAPI 3.0.3 JSON that both tools consume |

All three URLs are public — no authentication required to view the documentation. The spec is auto-generated from your registered CRUDView endpoints and auth endpoints.

## How It Works

Both Swagger UI and ReDoc load from CDN (no packages to install or vendor):

1. You visit `/api/docs/` or `/api/redoc/`
2. Django renders a minimal HTML page with a `<script>` tag pointing to the CDN
3. The JavaScript fetches your OpenAPI spec from `/api/schema/openapi.json`
4. The tool renders your full API documentation client-side

The HTML templates live at:
```
apps/smallstack/templates/smallstack/api/
├── swagger.html    # Swagger UI page
└── redoc.html      # ReDoc page
```

The views are defined in `apps/smallstack/api.py` and registered in `config/urls.py`.

## What Gets Documented

The OpenAPI spec automatically includes:

- **All CRUDView endpoints** with `enable_api = True` — list, create, detail, update, delete, bulk operations
- **All auth endpoints** — login, logout, register, me, password, users, token refresh
- **Request/response schemas** derived from your Django model and form fields
- **Query parameters** — search, filter, pagination, ordering, aggregation, export
- **Bearer token security scheme**
- **Error response format**

When you add a new CRUDView with `enable_api = True`, it appears in the docs automatically on the next page load.

## Swagger UI vs ReDoc

| Feature | Swagger UI (`/api/docs/`) | ReDoc (`/api/redoc/`) |
|---------|--------------------------|----------------------|
| **Try requests** | Yes — send real API calls from the browser | No — read-only reference |
| **Layout** | Single-column, expandable operations | Three-panel: nav, content, code samples |
| **Best for** | Developers testing endpoints interactively | Sharing API reference with teams or clients |
| **Auth support** | "Authorize" button to set Bearer token | Shows auth requirements but no token input |

**Use Swagger UI** when you're building and testing. **Use ReDoc** when you want clean documentation to share.

## Customizing ReDoc Theme

ReDoc supports extensive theming via its `theme` JSON attribute. The template at `apps/smallstack/templates/smallstack/api/redoc.html` is already themed to match SmallStack's brand colors. You can customize it further:

```html
<redoc spec-url="{{ schema_url }}"
       hide-download-button
       theme='{
           "colors": {
               "primary": { "main": "#417690" }
           },
           "typography": {
               "fontSize": "15px",
               "fontFamily": "Inter, sans-serif"
           },
           "sidebar": {
               "width": "280px",
               "backgroundColor": "#1a2332",
               "textColor": "#cbd5e1",
               "activeTextColor": "#f5dd5d"
           },
           "rightPanel": {
               "backgroundColor": "#1a2332"
           }
       }'>
</redoc>
```

### Available Theme Options

| Category | Key | What it controls |
|----------|-----|-----------------|
| **Colors** | `colors.primary.main` | Accent color for links, buttons, tags |
| | `colors.http.get/post/put/delete` | Per-method colors |
| | `colors.text.primary` | Main body text color |
| **Typography** | `typography.fontSize` | Base font size |
| | `typography.fontFamily` | Body font |
| | `typography.headings.fontFamily` | Heading font |
| | `typography.code.fontFamily` | Code block font |
| **Sidebar** | `sidebar.backgroundColor` | Sidebar background |
| | `sidebar.textColor` | Sidebar text |
| | `sidebar.activeTextColor` | Selected item highlight |
| | `sidebar.width` | Sidebar width |
| **Right Panel** | `rightPanel.backgroundColor` | Code samples panel background |

## Customizing Swagger UI

Swagger UI is configured in `apps/smallstack/templates/smallstack/api/swagger.html`. The configuration is in the `SwaggerUIBundle()` call:

```javascript
SwaggerUIBundle({
    url: "{{ schema_url }}",
    dom_id: "#swagger-ui",
    deepLinking: true,
    presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIBundle.SwaggerUIStandalonePreset,
    ],
    layout: "BaseLayout",
});
```

Common customizations:
- `defaultModelsExpandDepth: -1` — hide the schemas section at the bottom
- `docExpansion: "none"` — collapse all operations by default
- `filter: true` — add a search/filter bar
- `tryItOutEnabled: true` — enable "Try it out" by default

## Content Security Policy (CSP)

Both docs pages load JavaScript and CSS from `cdn.jsdelivr.net`. Since SmallStack uses CSP headers, the docs views set a per-response CSP that allows the CDN:

```python
response["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "worker-src blob:; "
)
```

This CSP is only applied to the docs pages themselves, not to the rest of your application. Your global CSP remains unchanged.

## CDN vs Vendoring

The docs pages load Swagger UI and ReDoc from `cdn.jsdelivr.net`. This means:

- **No packages to install or update** — the CDN serves the latest stable version
- **No static files to manage** — nothing in your `static/` directory
- **Requires internet access** — the browser must reach `cdn.jsdelivr.net` to load the tools

Both libraries are stable and update infrequently (ReDoc ~2-3 times per year, Swagger UI ~monthly). Breaking changes are rare. If you need offline access or version pinning, you can vendor the files into `static/` and update the template `<script>` tags.

## Debugging Blank Pages

If Swagger UI or ReDoc shows a blank white page:

1. **Check browser console** — Look for CSP violations (`Refused to load the script...`). The CSP header on the response must allow `cdn.jsdelivr.net`.
2. **Check network tab** — Verify the CDN scripts are loading (200 status).
3. **Check the spec URL** — Visit `/api/schema/openapi.json` directly. If it returns valid JSON, the spec is fine.
4. **Django Debug Toolbar** — If enabled, the toolbar can interfere with standalone HTML pages. The debug toolbar is configured to skip `/api/docs/` and `/api/redoc/` paths, but if you're still having issues, verify the `SHOW_TOOLBAR_CALLBACK` in `config/settings/development.py`.
