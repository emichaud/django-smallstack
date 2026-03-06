# How It Works

A single middleware intercepts every request and creates a `RequestLog`:

| Field | Field | Field |
|-------|-------|-------|
| `path` | `user` | `timestamp` |
| `method` | `ip_address` | `duration_ms` |
| `status_code` | `user_agent` | |

Static files, health checks, and admin media are **excluded by default**.
