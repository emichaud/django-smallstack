# htmx Live Refresh

Dashboard stats update every 10 seconds via `hx-trigger="every 10s"` — no page reload.

**Dual-response pattern:** Views return a full page normally, or just the HTML fragment for htmx requests.

No WebSockets needed — simple polling works behind any reverse proxy.
