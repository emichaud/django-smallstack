---
title: React + SmallStack
description: Connect a React frontend to SmallStack in 5 minutes — SDK setup, authentication, and fetching data
---

# React + SmallStack

This guide gets a React app talking to SmallStack's API with authentication, registration, and data fetching. We'll use the official `smallstack-sdk-js` package, which handles token management so you don't have to.

## Prerequisites

- A running SmallStack instance (`make run` — default port 8005)
- A React project (Vite, Next.js, Create React App — any works)

## 1. Configure SmallStack

Add these to your SmallStack `.env`:

```bash
# Allow your React dev server to make API calls
CORS_ALLOWED_ORIGINS=http://localhost:5173

# Enable the registration endpoint (optional — only if you need signup)
SMALLSTACK_API_REGISTER_ENABLED=True
```

Restart SmallStack after changing `.env`.

## 2. Create a System Token

If your app needs user registration, create an auth-level token that the SDK will use behind the scenes:

**Option A — Token Manager UI:**
Go to `/smallstack/tokens/`, click "Create Token", set access level to **auth**.

**Option B — CLI:**
```bash
uv run python manage.py create_api_token admin --access-level auth
```

Copy the token — you'll need it in the next step.

## 3. Install the SDK

In your React project:

```bash
npm install smallstack-sdk-js
```

## 4. Configure Environment

Create `.env.local` in your React project root:

```bash
VITE_API_URL=http://localhost:8005
```

> **Note:** If you need registration during local development, you can add `VITE_SYSTEM_TOKEN=your-token-here` for convenience. **Do not deploy this to production** — `VITE_` variables are bundled into client-side JavaScript. See [What About the System Token?](#what-about-the-system-token) for production patterns.

## 5. Create the Client

```typescript
// src/lib/client.ts
import { SmallStackClient } from "smallstack-sdk-js";

export const client = new SmallStackClient({
  baseUrl: import.meta.env.VITE_API_URL,
  persist: true,  // saves token to localStorage, restores on page refresh
});
```

That's the only setup. The SDK handles:
- Sending `Authorization: Bearer <token>` on every request
- Saving/restoring the token across page refreshes (`persist: true`)
- Swapping to the system token for `register()`, then setting the new user's token

## 6. Build an Auth Context

```tsx
// src/context/AuthContext.tsx
import { createContext, useContext, useState, useEffect } from "react";
import { client } from "../lib/client";
import type { User } from "smallstack-sdk-js";

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  register: (data: {
    username: string;
    email: string;
    password: string;
    password_confirm: string;
  }) => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // On mount, check if a persisted token is still valid
  useEffect(() => {
    client.auth
      .me()
      .then((res) => {
        if (res.ok) setUser(res.data);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const res = await client.auth.login(username, password);
    if (res.ok) {
      setUser(res.data.user);
      return true;
    }
    return false;
  };

  const register = async (data: {
    username: string;
    email: string;
    password: string;
    password_confirm: string;
  }) => {
    const res = await client.auth.register(data);
    if (res.ok) {
      setUser(res.data.user);
      return true;
    }
    return false;
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

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
```

## 7. Wire Up Your App

```tsx
// src/App.tsx
import { AuthProvider } from "./context/AuthContext";
import { Dashboard } from "./pages/Dashboard";
import { LoginPage } from "./pages/LoginPage";
import { useAuth } from "./context/AuthContext";

function AppContent() {
  const { user, loading } = useAuth();

  if (loading) return <div>Loading...</div>;
  if (!user) return <LoginPage />;
  return <Dashboard />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
```

## 8. Fetch Data

Use `client.api()` for any SmallStack endpoint. The token is included automatically.

```tsx
// src/pages/Dashboard.tsx
import { useEffect, useState } from "react";
import { client } from "../lib/client";
import { useAuth } from "../context/AuthContext";
import type { PaginatedResponse } from "smallstack-sdk-js";

interface Widget {
  id: number;
  name: string;
  status: string;
}

export function Dashboard() {
  const { user, logout } = useAuth();
  const [widgets, setWidgets] = useState<Widget[]>([]);

  useEffect(() => {
    client
      .api<PaginatedResponse<Widget>>("/api/manage/widgets/")
      .then((res) => {
        if (res.ok) setWidgets(res.data.results);
      });
  }, []);

  return (
    <div>
      <h1>Welcome, {user?.username}</h1>
      <button onClick={logout}>Logout</button>
      <ul>
        {widgets.map((w) => (
          <li key={w.id}>{w.name} — {w.status}</li>
        ))}
      </ul>
    </div>
  );
}
```

## API Response Shapes

### Paginated Responses

All list endpoints return a paginated wrapper:

```json
{
  "count": 42,
  "next": "http://localhost:8005/api/items/?page=2",
  "previous": null,
  "results": [{ "id": 1, "name": "Widget" }, ...]
}
```

Use the `PaginatedResponse<T>` type from the SDK:

```typescript
import type { PaginatedResponse } from "smallstack-sdk-js";
const { data } = await client.api<PaginatedResponse<Item>>("/api/items/");
// data.results, data.count, data.next, data.previous
```

### FK Expansion

By default, ForeignKey fields return as integer IDs:

```json
{ "id": 1, "name": "Widget", "category": 3 }
```

If the CRUDView declares `api_expand_fields = ["category"]`, you can request expanded objects with `?expand=category`:

```json
{ "id": 1, "name": "Widget", "category": { "id": 3, "name": "Electronics" } }
```

In your frontend code:

```typescript
const { data } = await client.api<PaginatedResponse<Item>>("/api/items/", {
  params: { expand: "category,bin" },
});
// data.results[0].category is now { id: 3, name: "Electronics" }
```

The CRUDView must declare which fields are expandable — `?expand=` only works for fields listed in `api_expand_fields`. Fields not in the list are silently ignored.

## How the Token Flow Works

```
1. User fills login form → client.auth.login(username, password)
   SDK sends credentials → SmallStack returns user token
   SDK stores token in memory + localStorage

2. User navigates to dashboard → client.api("/api/manage/widgets/")
   SDK attaches "Authorization: Bearer <user-token>" automatically
   SmallStack validates token, returns data

3. User refreshes the page
   SDK reads token from localStorage (persist: true)
   AuthContext calls client.auth.me() → still authenticated

4. User clicks register → client.auth.register(data)
   SDK swaps to system token for this one request
   SmallStack creates user, returns new user token
   SDK sets the new user token (replaces system token in memory)

5. User logs out → client.auth.logout()
   SDK revokes token server-side, clears memory + localStorage
```

## What About the System Token?

The system token is an auth-level API token that can register users, list users, reset passwords, and deactivate accounts. It is a **privileged credential** — treat it like a database password.

**Do not put it in client-side environment variables** like `VITE_SYSTEM_TOKEN` or `NEXT_PUBLIC_SYSTEM_TOKEN`. These prefixes tell bundlers to include the value in the JavaScript bundle, which means anyone can see it in their browser's dev tools.

### For production apps that need registration

Proxy the registration request through your own server-side endpoint that holds the system token. The browser never sees it — your server makes the SmallStack call:

```
Browser → POST /api/register (your server)
Your server → POST /api/auth/register/ (SmallStack, with system token)
Your server ← 201 { token, user }
Browser ← 201 { token, user }
```

**Next.js API Route** (`app/api/register/route.ts`):

```typescript
import { SmallStackClient } from "smallstack-sdk-js";

const server = new SmallStackClient({
  baseUrl: process.env.SMALLSTACK_API_URL!,   // not NEXT_PUBLIC_ — server only
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

Then your React client calls your own server instead of SmallStack directly:

```typescript
// No systemToken needed — your server handles it
const res = await fetch("/api/register", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username, email, password, password_confirm }),
});
const data = await res.json();
if (res.ok) {
  client.setToken(data.token);  // SDK stores + persists the user's token
}
```

### For apps that don't need registration

Skip `systemToken` entirely — users are created by admins through the SmallStack UI:

```typescript
const client = new SmallStackClient({
  baseUrl: import.meta.env.VITE_API_URL,
  persist: true,
});
// login() works fine without systemToken
```

### For local development / internal tools

Using `VITE_SYSTEM_TOKEN` during local development is fine — just don't deploy it to production that way.

## Next Steps

- [Frontend Integration](/smallstack/help/smallstack/explorer-rest-api/) — Full API reference, filtering, export
- [API Documentation](/smallstack/help/smallstack/api-documentation/) — Swagger/ReDoc interactive docs
- [Authentication](/smallstack/help/smallstack/authentication/) — Token types, expiry, access levels
