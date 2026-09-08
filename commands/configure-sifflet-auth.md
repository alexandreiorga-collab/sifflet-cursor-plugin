---
name: configure-sifflet-auth
description: Set up Sifflet authentication for Cursor, Claude Code, and Monitors as Code.
---

# Configure Sifflet Authentication

Create an API token with the **Editor** role first: [Generate an API token](https://docs.siffletdata.com/docs/generate-an-api-token). Editor is required because one token serves both MCP discovery and Monitors as Code `plan`/`apply` (a read-only Viewer token is enough only for catalog exploration without applies).

Then run:

```bash
sifflet configure
```

This writes `~/.sifflet/config.ini`, which the Sifflet CLI reads directly and the plugin's MCP launcher uses as a fallback. Reload the IDE (Cursor or Claude Code) after configuration so the Sifflet MCP server can use the new credentials.

## Environment variables (alternative, e.g. for CI)

The CLI and the MCP server use **different token variable names**:

- Sifflet CLI: `SIFFLET_TOKEN` and `SIFFLET_BACKEND_URL`
- Sifflet MCP: `SIFFLET_API_TOKEN` and `SIFFLET_BACKEND_URL`

Backend URL form: `https://<tenant>.siffletdata.com/api/` (note the `/api/` suffix).

## Verify

- Run `sifflet status`.
- Ask Agent to search the Sifflet catalog.
- For Monitors as Code, run `sifflet code workspace plan --file workspace.yaml`.

Do not commit API tokens or local Sifflet configuration files, and do not print the token into the conversation.
