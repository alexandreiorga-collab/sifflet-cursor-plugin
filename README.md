# Sifflet Plugin for Cursor and Claude Code

Bring Sifflet data observability into Cursor and Claude Code. This plugin connects agents to Sifflet through the official MCP server and adds guidance for writing [Monitors as Code](https://docs.siffletdata.com/docs/monitors-as-code).

This plugin is provided as-is and is not an officially supported Sifflet product.

## What You Get

- **Sifflet MCP** for catalog, monitor, incident, and lineage discovery from Agent chat.
- **Quality as Code skills** for drafting and reviewing `workspace.yaml` and monitor YAML.
- **Rules and commands** that keep monitor changes reviewable before they are applied.
- **A safety guardrail hook** that gates destructive Sifflet actions behind explicit confirmation.

## Requirements

- A Sifflet account and an API token with the **Editor** role (see [Authentication](#authentication) for why).
- Cursor with plugin and MCP support, and/or [Claude Code](https://code.claude.com/docs).
- [`uv`](https://docs.astral.sh/uv/) available on your PATH so the IDE can run `uvx sifflet-mcp`.
- `python3` on your PATH — the safety guardrail runs through it and is configured fail-closed, so destructive Sifflet commands are blocked (not allowed) if it is missing.
- The Sifflet CLI for Monitors as Code: `pip install "sifflet>=0.4.0"` (the `plan` / `apply --auto-approve` semantics this plugin documents assume 0.4.0 or later).

## Installation

### Cursor

This plugin is **not published on the Cursor Marketplace**, so it cannot be found by searching there. Install it from this repository instead, either way below (see [Cursor's plugin docs](https://cursor.com/docs/plugins)):

**Option A — local plugin folder (individual install):**

```bash
git clone https://github.com/alexandreiorga-collab/sifflet-cursor-plugin.git ~/.cursor/plugins/local/sifflet
```

Restart Cursor (or run **Developer: Reload Window**), then open **Customize** and confirm the plugin's rules, skills, commands, and the `sifflet` MCP server appear. To update later, `git pull` in that folder and reload. On Teams/Enterprise plans this requires **Allow Local Plugin Imports** (Dashboard → Settings → Security & Identity → Marketplace and Plugins; off by default on Enterprise).

**Option B — team marketplace (Teams/Enterprise; best for rolling out to a team):**

An admin opens **Dashboard → Plugins → Add Marketplace → Import from Repo** and imports this repository; developers then install **Sifflet** from **Customize**. Enable Auto Refresh so pushes to `main` update the plugin automatically.

### Claude Code

Add this repository as a plugin marketplace, then install the plugin:

```text
/plugin marketplace add alexandreiorga-collab/sifflet-cursor-plugin
/plugin install sifflet@sifflet-local
```

Or from the command line:

```bash
claude plugin marketplace add alexandreiorga-collab/sifflet-cursor-plugin
claude plugin install sifflet@sifflet-local
```

The skills (`skills/`), commands (`commands/`), safety hooks (`hooks/hooks.json`), and the MCP server (`.mcp.json`) are all discovered automatically. Verify the install with `/plugin list` (and `/hooks` to confirm the guardrail is registered). Update later with `/plugin update sifflet`.

## Authentication

Create an API token with the **Editor** role ([Generate an API token](https://docs.siffletdata.com/docs/generate-an-api-token)), then run:

```bash
sifflet configure
```

**Why Editor?** Catalog discovery through MCP works with a read-only Viewer token, but Monitors as Code `plan`/`apply` and incident actions require Editor — and the plugin uses one token for both: `sifflet configure` writes `~/.sifflet/config.ini`, which the CLI reads directly and the MCP launcher uses as a fallback. If you only want read-only catalog exploration and will never apply monitors from the IDE, a Viewer token works for MCP alone.

Environment variables are an alternative to `config.ini` (useful for CI):

- Sifflet CLI: `SIFFLET_TOKEN` and `SIFFLET_BACKEND_URL`
- Sifflet MCP: `SIFFLET_API_TOKEN` and `SIFFLET_BACKEND_URL`

The backend URL form is `https://<tenant>.siffletdata.com/api/` (note the `/api/` suffix). Note the two different token variable names — the CLI and the MCP server do not share one.

Reload your IDE after configuring so the MCP server picks up the new credentials.

## Getting Started

With the plugin installed and authentication configured, reload the IDE (in Cursor, also enable the `sifflet` MCP server in settings), then ask Agent chat a Sifflet question:

```text
Find datasets related to customer orders in Sifflet.
```

## Example Prompts

Catalog and lineage:

```text
Search Sifflet for the orders dataset and show its downstream assets.
```

```text
Which monitors are attached to this dataset?
```

Monitors as Code:

```text
Create a Sifflet monitor YAML for freshness on this table.
```

```text
Review this workspace.yaml before I run a plan.
```

```text
Run a dry-run plan for quality/workspace.yaml and summarize the changes.
```

## Included

### MCP Server

The plugin registers the `sifflet` MCP server through `mcp.json` (Cursor) and `.mcp.json` (Claude Code). Both launch `sifflet-mcp` with `uvx`, reading credentials from the environment variables above or falling back to `~/.sifflet/config.ini`. A standalone launcher, `run-sifflet-mcp.sh`, is also included for manual use and debugging.

### Skills

- `sifflet-mcp` - explore catalog assets, monitors, incidents, and lineage before changing data or YAML.
- `sifflet-quality-as-code` - draft and refine Sifflet monitor and workspace YAML using MCP context and the Monitors as Code schema.

### Rules

- `sifflet-mac-yaml` - conventions for safe Monitors as Code YAML changes.

### Commands

- `configure-sifflet-auth` - help configure Sifflet authentication.
- `mac-plan-workspace` - run and review a dry-run plan.
- `mac-apply-workspace` - apply a reviewed workspace change.

### Safety guardrail

A bundled hook gates destructive or potentially-destructive actions and surfaces a native
confirmation prompt before they run: `sifflet ... apply`, `--auto-approve`,
`sifflet code workspace delete`, removing or renaming monitor/`workspace.yaml` files,
reads of `~/.sifflet/config.ini` (it stores the API token), and mutating Sifflet MCP calls
(incident open/close). The behavioral protocol lives in the `sifflet-quality-as-code` skill.
The hook ships for both Cursor (`hooks/cursor-hooks.json`) and Claude Code (`hooks/hooks.json`)
and shares one script (`hooks/guard-sifflet-destructive.py`); it requires `python3` on PATH
and is configured to fail closed if it crashes (Cursor via `failClosed`, Claude Code via a
blocking exit code; a hook timeout on Claude Code is not blocked). Commands the guard does
not flag are left to the platform's own permission flow — never auto-approved on Claude Code.
The guard has a test suite in `tests/` (`pytest tests/`).

## Monitors as Code

Use MCP for discovery and the Sifflet CLI for workspace changes:

```bash
sifflet code workspace plan --file workspace.yaml
sifflet code workspace apply --file workspace.yaml
```

Run `sifflet configure` before using Monitors as Code commands.

## Testing

- Automated: `pytest tests/` runs the guard's test suite; `python3 scripts/validate_manifests.py` checks every manifest, hook config, and referenced path. Both run in CI on every pull request.
- Manual: [TESTING.md](TESTING.md) has the install smoke-test checklist, guardrail spot-checks, the live-tenant test script, and red-team prompts.

## Troubleshooting

If MCP tools do not appear: in Cursor, reload and confirm the `sifflet` MCP server is enabled in settings; in Claude Code, run `/plugin list` to confirm the plugin loaded and check the MCP server status.

If authentication fails, run `sifflet configure` again, then reload the IDE.

If `uvx` is missing, install `uv` and restart the IDE.

If the guardrail blocks everything with a hook error, check that `python3` is on the PATH visible to the IDE — the guard is fail-closed by design.

## Publishing

Publish from a dedicated public repository or generated mirror that contains only this plugin tree. The manifest keeps `logo` as `assets/logo.svg` so the Cursor Marketplace can resolve it after publication.

## Links

- [Sifflet MCP server](https://docs.siffletdata.com/docs/sifflet-mcp-server)
- [Monitors as Code](https://docs.siffletdata.com/docs/monitors-as-code)
- [Monitor schema](https://docs.siffletdata.com/docs/monitor-schema)
- [Workspace schema](https://docs.siffletdata.com/docs/workspace-schema)
