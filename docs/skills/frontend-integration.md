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
├── POST /api/auth/register/     → system token (creates user + returns login token)
├── POST /api/auth/users/5/password/   → system token
└── POST /api/auth/users/5/deactivate/ → system token

Browser (has user's login token)
├── POST /api/auth/token/        → no token needed (sends credentials)
├── GET  /api/auth/me/           → login token
├── POST /api/auth/password/     → login token (self-service)
├── GET  /api/manage/widgets/    → login token (CRUDView read)
└── POST /api/manage/widgets/    → login token (CRUDView write)
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

Login tokens expire (default 24h, configurable). To refresh, call `POST /api/auth/token/` again with the user's credentials. The old token is replaced.

Handle 401 responses by redirecting to your login page.

## React Example

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
  throw new Error(data.error);
}

// Fetch data
async function getWidgets(page = 1) {
  const res = await apiFetch(`/api/manage/widgets/?page=${page}`);
  return res.json();
}
```

## Security Notes

- **System token is a backend secret** — store it in server-side environment variables, never expose it to the browser. If your frontend is a pure SPA with no server component, you cannot safely use register/deactivate/system-password-change endpoints from the client.
- **Login tokens expire** — default 24 hours, configurable via `SMALLSTACK_LOGIN_TOKEN_EXPIRY_HOURS`. Handle 401 gracefully (redirect to login).
- **Registration creates non-staff users only** — the register endpoint always sets `is_staff=False`, `is_superuser=False`.
- **CORS restricts origins** — only origins listed in `CORS_ALLOWED_ORIGINS` can make cross-origin requests.
- **One login token per user** — calling `/api/auth/token/` replaces the previous login token. A user can only be "logged in" from one token at a time.

## What's Not Included (Yet)

- **Public signup** (no system token needed) — would require rate limiting and CAPTCHA
- **Password reset via email** — requires email sending infrastructure
- **Social auth / OAuth** — consider `django-allauth` if needed
- **Rate limiting on auth endpoints** — `axes` handles login brute-force; register endpoint is protected by requiring an auth-level token
