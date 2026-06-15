# Connecting Claude Desktop / Claude.ai

Two paths depending on which client you're using.

## Claude.ai (Connectors UI — OAuth)

In Claude.ai's settings → Connectors → Add custom connector:

- **URL:** `https://your-host/mcp`
- **Display name:** Whatever you'd like

Claude.ai will:

1. Probe `https://your-host/.well-known/oauth-protected-resource`
2. Fetch the AS metadata, register dynamically via DCR
3. Pop a consent window pointed at `/mcp/oauth/authorize`
4. After you Allow, complete the PKCE-bound code exchange
5. Use the resulting Bearer for subsequent `/mcp` calls

If anything errors during the OAuth dance, the consent page logs the failure under `smallstack.mcp.oauth` and Claude.ai shows a generic "couldn't connect". Check `kamal app logs | grep smallstack.mcp` first.

## Claude Desktop (mcp-remote, raw Bearer)

For Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "smallstack": {
      "command": "npx",
      "args": ["mcp-remote", "https://your-host/mcp"],
      "env": {
        "AUTHORIZATION": "Bearer <token>"
      }
    }
  }
}
```

Mint the token with:

```bash
uv run python manage.py create_api_token me --name "claude-desktop" --access-level readonly
```

`mcp-remote` proxies stdio to HTTP and passes the `AUTHORIZATION` env through.

For Desktop's Connectors UI (newer versions) — same as Claude.ai's UI flow above; point it at `https://your-host/mcp`.

## Verifying the connection

After connecting, ask Claude:

> What tools do you have access to from this server?

Claude will list the tools from your `tools/list`. If you see only `ping`, the registry is empty — no `enable_mcp = True` anywhere, and no `MCP_TOOL_MODULES`.
