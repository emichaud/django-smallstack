# Skill: Connect Claude Desktop to the MCP server

## When to use this skill
The user wants to validate the MCP server from a real client.

## Two paths

### A. Claude Desktop / Claude.ai — Connectors UI (OAuth)

1. Confirm OAuth discovery works:

   ```bash
   curl -s http://localhost:8005/.well-known/oauth-protected-resource | jq .resource
   # → "http://localhost:8005/mcp"   (NO trailing slash)
   curl -s http://localhost:8005/.well-known/oauth-authorization-server | jq .issuer
   ```

2. In Claude Desktop → Settings → Connectors → "Add custom connector":
   - URL: `http://localhost:8005/mcp` (or your prod URL)
   - Name: anything

3. Claude pops a browser window → consent page → Allow → done.

4. Sanity check by asking Claude: "What tools do you have from this server?"

### B. Claude Desktop — JSON config (raw Bearer)

1. Mint a token:

   ```bash
   uv run python manage.py create_api_token --user me --name "claude-desktop" --access-level readonly
   ```

2. Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "smallstack": {
         "command": "npx",
         "args": ["mcp-remote", "https://your-host/mcp"],
         "env": {
           "AUTHORIZATION": "Bearer <paste raw key>"
         }
       }
     }
   }
   ```

3. Restart Claude Desktop. Connector should appear; ask: "List the tools you have."

## Validating end-to-end

```bash
# tools/list with the token
curl -s -X POST http://localhost:8005/mcp \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools | length'
```

Should print an integer. Even 0 is success — it means dispatch + auth work; you just don't have any tools registered yet.

## If it fails

`uv run python manage.py mcp_doctor` first. Then `kamal app logs | grep smallstack.mcp` (or `tail -f` the dev log). See [`mcp-debugging.md`](../../apps/smallstack/docs/mcp-debugging.md) for the symptom → cause table.
