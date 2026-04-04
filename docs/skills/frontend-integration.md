# Skill: Frontend Integration

Using SmallStack as a headless API backend for React, Vue, Next.js, Svelte, or any frontend framework. Covers the token architecture, CORS setup, and the full user lifecycle.

For endpoint-level details (request/response formats, filtering, aggregation), see `api.md`.

## Overview

SmallStack provides:
- **User management** — registration, authentication, password changes, deactivation
- **CRUDView API** — JSON endpoints for any model with `enable_api = True`
- **Token authentication** — Bearer scheme with automatic expiry

Your frontend owns:
- UI/UX, routing, state management
- Token storage (localStorage, cookie, etc.)
- Error handling and 401 redirect logic

## Setup Checklist

### 1. Enable CORS

Set the frontend's origin in your `.env`:

```bash
# .env
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

For production, use the actual domain:

```bash
CORS_ALLOWED_ORIGINS=https://app.example.com
```

Multiple origins are comma-separated. This is already wired in `config/settings/base.py` — no code changes needed.

### 2. Enable Registration (if needed)

```bash
# .env
SMALLSTACK_API_REGISTER_ENABLED=True
```

Without this, `POST /api/auth/register/` returns 403.

### 3. Create a System Token

In the Token Manager UI (`/smallstack/tokens/`), create a manual token with **auth** access level. Only superusers can create auth-level tokens.

Or via CLI: `uv run python manage.py create_api_token <username> --access-level auth`

Store this token in your frontend's server-side environment config (`.env.local`, Vercel secrets, etc.) — **never in client-side code**.

## Token Architecture

SmallStack uses two kinds of tokens:

| Token | Held By | Created Via | Purpose |
|-------|---------|-------------|---------|
| **System token** (manual, auth-level) | Frontend server / environment config | Token Manager UI | System operations: register users, reset passwords, deactivate accounts |
| **User login token** | Browser (localStorage/cookie) | `POST /api/auth/token/` or `/api/auth/register/` | Authenticated requests on behalf of the user |

### Which token for which operation

```
Frontend Server (has system token)
├── POST /api/auth/register/              → system token
├── GET/PATCH /api/auth/users/            → system token (list, search, update)
├── POST /api/auth/users/5/password/      → system token
└── POST /api/auth/users/5/deactivate/    → system token

Browser (has user's login token)
├── POST /api/auth/token/                 → no token needed (sends credentials)
├── GET  /api/auth/me/                    → login token
├── POST /api/auth/password/              → login token (self-service)
├── POST /api/auth/token/refresh/         → login token (extends session)
├── POST /api/auth/logout/                → login token (revokes token)
├── GET  /api/manage/widgets/             → login token (CRUDView read)
└── POST /api/manage/widgets/             → login token (CRUDView write)

No token needed (public)
├── GET  /api/auth/password-requirements/ → password validation rules
├── GET  /api/schema/                     → endpoint discovery
├── GET  /api/schema/openapi.json         → OpenAPI 3.0.3 spec
└── OPTIONS /api/{endpoint}/              → field metadata
```

## User Lifecycle Flow

### Registration

```
Frontend server → POST /api/auth/register/
                  Authorization: Bearer <system-token>
                  {"username": "alice", "password": "secret123", "email": "alice@example.com"}

              ← 201 {"token": "user-login-token...", "user": {...}, "expires_at": "..."}
```

Return the login token to the browser. The new user is always non-staff, non-superuser.

### Login

```
Browser → POST /api/auth/token/
          {"username": "alice", "password": "secret123"}

      ← 200 {"token": "user-login-token...", "user": {...}, "expires_at": "..."}
```

This is an upsert — if the user already has a login token, the key is regenerated and the old one stops working. No system token needed.

### Authenticated Requests

```
Browser → GET /api/manage/widgets/
          Authorization: Bearer <login-token>

      ← 200 {"count": 42, "results": [...]}
```

### Discovering the API

SmallStack provides three discovery endpoints (no auth required):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/schema/` | SmallStack-native schema — lists all endpoints, fields, filters, ordering |
| `GET /api/schema/openapi.json` | OpenAPI 3.0.3 spec — for Swagger UI, code generators, Postman |
| `OPTIONS /api/{endpoint}/` | Field types, constraints, allowed methods for a single endpoint |

Use the OpenAPI spec to auto-generate TypeScript types or API clients for your frontend framework.

### Password Change (Self-Service)

```
Browser → POST /api/auth/password/
          Authorization: Bearer <login-token>
          {"current_password": "old123", "new_password": "new456"}

      ← 200 {"message": "Password updated"}
```

### Password Reset (Admin/System)

```
Frontend server → POST /api/auth/users/5/password/
                  Authorization: Bearer <system-token>
                  {"new_password": "temp456"}

              ← 200 {"message": "Password updated"}
```

### Deactivation

```
Frontend server → POST /api/auth/users/5/deactivate/
                  Authorization: Bearer <system-token>

              ← 200 {"message": "User deactivated"}
```

This sets `is_active=False` and revokes all the user's tokens.

### Token Refresh

Login tokens expire (default 24h, configurable). To extend a session without re-entering
credentials, call `POST /api/auth/token/refresh/` with the current login token. The key is
regenerated and the old one immediately stops working.

If the token has already expired (401), redirect to your login page for re-authentication.

## Using the SDK (Recommended)

The `smallstack-sdk-js` package handles token management, persistence, and the system token proxy for registration. Install it in your frontend project:

```bash
npm install smallstack-sdk-js
```

### Client Setup

```typescript
// lib/client.ts
import { SmallStackClient } from "smallstack-sdk-js";

export const client = new SmallStackClient({
  baseUrl: import.meta.env.VITE_API_URL || "http://localhost:8005",
  persist: true,  // auto-sync token to localStorage
});
```

> **Do not pass `systemToken` in client-side code.** `VITE_` and `NEXT_PUBLIC_` environment variables are bundled into JavaScript that anyone can view in their browser. The system token can register users, reset passwords, and deactivate accounts — it must stay server-side. Using `VITE_SYSTEM_TOKEN` during local development is acceptable.

#### Production Registration Proxy

For SPAs that need registration, proxy through a server-side endpoint that holds the system token:

**Next.js API Route** (`app/api/register/route.ts`):
```typescript
import { SmallStackClient } from "smallstack-sdk-js";

const server = new SmallStackClient({
  baseUrl: process.env.SMALLSTACK_API_URL!,
  systemToken: process.env.SMALLSTACK_SYSTEM_TOKEN!,
});

export async function POST(request: Request) {
  const body = await request.json();
  const res = await server.auth.register(body);
  return Response.json(res.data, { status: res.status });
}
```

**Express** (`routes/register.js`):
```javascript
import { SmallStackClient } from "smallstack-sdk-js";

const server = new SmallStackClient({
  baseUrl: process.env.SMALLSTACK_API_URL,
  systemToken: process.env.SMALLSTACK_SYSTEM_TOKEN,
});

app.post("/api/register", async (req, res) => {
  const result = await server.auth.register(req.body);
  res.status(result.status).json(result.data);
});
```

The browser calls your server, your server calls SmallStack with the system token, and the user's login token is returned to the browser.

### Auth Context (React)

```tsx
// context/AuthContext.tsx
import { createContext, useContext, useState, useEffect } from "react";
import { client } from "../lib/client";
import type { User } from "smallstack-sdk-js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // On mount, check if persisted token is still valid
    client.auth.me().then(res => {
      if (res.ok) setUser(res.data);
    }).finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const res = await client.auth.login(username, password);
    if (res.ok) setUser(res.data.user);
    return res;
  };

  const register = async (data) => {
    const res = await client.auth.register(data);
    if (res.ok) setUser(res.data.user);
    return res;
  };

  const logout = async () => {
    await client.auth.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

### Fetching Data

```typescript
// Use client.api() for any endpoint — token is sent automatically
const { data } = await client.api<PaginatedResponse<Widget>>("/api/manage/widgets/");
console.log(data.results);
```

The SDK handles: token storage/restoration on page refresh, system token swap for `register()`, and token cleanup on `logout()`. No manual `localStorage` or `Authorization` header management needed.

### SDK Constructor Options

| Option        | Type      | Default              | Description                                      |
|---------------|-----------|----------------------|--------------------------------------------------|
| `baseUrl`     | `string`  | —                    | Base URL of your SmallStack instance             |
| `token`       | `string`  | —                    | Pre-existing Bearer token                        |
| `systemToken` | `string`  | —                    | Auth-level token for `register()` (auto-proxied) |
| `persist`     | `boolean` | `false`              | Auto-sync token to localStorage                  |
| `storageKey`  | `string`  | `"smallstack_token"` | localStorage key for persisted token             |

## React Example (Without SDK)

If you prefer not to use the SDK, here's the equivalent manual approach:

```jsx
// lib/api.js
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8005";

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    localStorage.removeItem("token");
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  return res;
}

// Login
async function login(username, password) {
  const res = await apiFetch("/api/auth/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json();
  if (res.ok) {
    localStorage.setItem("token", data.token);
    return data.user;
  }
  throw new Error(Object.values(data.errors).flat().join(", "));
}

// Refresh token (extends session without re-entering credentials)
async function refreshToken() {
  const res = await apiFetch("/api/auth/token/refresh/", { method: "POST" });
  const data = await res.json();
  if (res.ok) {
    localStorage.setItem("token", data.token);
    return data;
  }
  throw new Error("Token refresh failed");
}

// Logout (revokes token server-side)
async function logout() {
  await apiFetch("/api/auth/logout/", { method: "POST" });
  localStorage.removeItem("token");
  window.location.href = "/login";
}

// Fetch data
async function getWidgets(page = 1) {
  const res = await apiFetch(`/api/manage/widgets/?page=${page}`);
  return res.json();
}
```

## TanStack Query Integration

SmallStack's API maps naturally to [TanStack Query](https://tanstack.com/query) patterns. Here are the recommended patterns:

### Setup

```jsx
// main.jsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,  // 30s — good default for CRUD data
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <YourApp />
    </QueryClientProvider>
  );
}
```

### Query Key Factories

Organize keys by resource to match SmallStack's URL structure:

```js
const queryKeys = {
  widgets: {
    all: ["widgets"],
    list: (params) => ["widgets", "list", params],
    detail: (id) => ["widgets", "detail", id],
  },
  passwordRequirements: ["password-requirements"],  // staleTime: Infinity
};
```

### Hooks Pattern

```jsx
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

function useWidgets(params) {
  return useQuery({
    queryKey: queryKeys.widgets.list(params),
    queryFn: () => apiFetch(`/api/manage/widgets/?${params}`).then(r => r.json()),
    enabled: !!user,  // prevent 401 spam before login
  });
}

function useCreateWidget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => apiFetch("/api/manage/widgets/", {
      method: "POST",
      body: JSON.stringify(data),
    }).then(r => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.widgets.all });
    },
  });
}
```

### Key Recommendations

- **`enabled: !!user` on authenticated queries** — prevents unnecessary 401 errors before the user logs in
- **`queryClient.clear()` on logout** — clears cached data from the previous session to prevent cross-session data leaks
- **Token rotation awareness** — SmallStack's login upserts the token (old key stops working). If a user logs in from another tab, the first tab's token is dead. Handle this by redirecting to login on 401 rather than retrying
- **`staleTime: Infinity` for static data** — use for endpoints like `/api/auth/password-requirements/` that rarely change

### OpenAPI Codegen

Generate a fully typed TypeScript client from SmallStack's OpenAPI spec:

```bash
npx orval --input http://localhost:8005/api/schema/openapi.json --output ./src/api/
```

This produces typed functions for every endpoint, including auth responses, filter parameters, and pagination envelopes.

## Security Notes

- **System token is a backend secret** — store it in server-side environment variables, never expose it to the browser. `VITE_`, `NEXT_PUBLIC_`, and `REACT_APP_` prefixed variables are bundled into client-side JavaScript and visible to anyone. For SPAs that need registration, proxy through a server-side endpoint (Next.js API route, Express, etc.) that holds the system token. If your frontend has no server component, you cannot safely use register/deactivate/system-password-change endpoints from the client.
- **Login tokens expire** — default 24 hours, configurable via `SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS`. Handle 401 gracefully (redirect to login).
- **Registration creates non-staff users only** — the register endpoint always sets `is_staff=False`, `is_superuser=False`.
- **CORS restricts origins** — only origins listed in `CORS_ALLOWED_ORIGINS` can make cross-origin requests.
- **One login token per user** — calling `/api/auth/token/` replaces the previous login token. A user can only be "logged in" from one token at a time.

## What's Not Included (Yet)

- **Public signup** (no system token needed) — would require rate limiting and CAPTCHA
- **Password reset via email** — requires email sending infrastructure
- **Social auth / OAuth** — consider `django-allauth` if needed
