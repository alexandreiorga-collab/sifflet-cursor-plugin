# Sifflet Cursor Plugin

Bring Sifflet data observability into Cursor. This plugin connects agents to Sifflet through the official MCP server and adds guidance for writing [Monitors as Code](https://docs.siffletdata.com/docs/monitors-as-code).

This plugin is provided as-is and is not an officially supported Sifflet product.

## What You Get

- **Sifflet MCP** for catalog, monitor, incident, and lineage discovery from Agent chat.
- **Quality as Code skills** for drafting and reviewing `workspace.yaml` and monitor YAML.
- **Rules and commands** that keep monitor changes reviewable before they are applied.

## Requirements

- A Sifflet account and API token.
- Cursor with plugin and MCP support.
- [`uv`](https://docs.astral.sh/uv/) available on your PATH so Cursor can run `uvx sifflet-mcp`.
- The Sifflet CLI if you want to run `sifflet code workspace plan` or `apply`.

## Installation

Install **Sifflet** from Cursor's plugin marketplace.

## Getting Started

Install the plugin, then authenticate Sifflet once:

```bash
sifflet configure
```

Reload Cursor, enable the `sifflet` MCP server in Cursor settings, then ask Agent chat a Sifflet question:

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

The plugin registers the `sifflet` MCP server through `mcp.json`. It starts `run-sifflet-mcp.sh`, which launches `sifflet-mcp` with `uvx`.

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
and is configured fail-closed on both platforms (Cursor via `failClosed`, Claude Code via a
blocking exit code). The guard has a test suite in `tests/` (`pytest tests/`).

## Monitors as Code

Use MCP for discovery and the Sifflet CLI for workspace changes:

```bash
sifflet code workspace plan --file workspace.yaml
sifflet code workspace apply --file workspace.yaml
```

Run `sifflet configure` before using Monitors as Code commands.

## Troubleshooting

If MCP tools do not appear, reload Cursor and confirm the `sifflet` MCP server is enabled in settings.

If authentication fails, run `sifflet configure` again, then reload Cursor.

If `uvx` is missing, install `uv` and restart Cursor.

## Publishing

Publish from a dedicated public repository or generated mirror that contains only this plugin tree. The manifest keeps `logo` as `assets/logo.svg` so the Cursor Marketplace can resolve it after publication.

## Links

- [Sifflet MCP server](https://docs.siffletdata.com/docs/sifflet-mcp-server)
- [Monitors as Code](https://docs.siffletdata.com/docs/monitors-as-code)
- [Monitor schema](https://docs.siffletdata.com/docs/monitor-schema)
- [Workspace schema](https://docs.siffletdata.com/docs/workspace-schema)
