---
name: sifflet-mcp
description: Use the Sifflet Model Context Protocol server to explore catalog assets, monitors, incidents, and lineage before changing data or YAML. Use when the user needs Sifflet discovery, impact analysis, or monitor metadata.
---

# Sifflet MCP

## When to use

- Resolve tables, dashboards, or other assets before writing SQL or Monitors as Code YAML.
- Inspect or compare existing monitors and incidents.
- Understand downstream lineage or blast radius for a change.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) so `uvx` is available (recommended by [Sifflet MCP server](https://docs.siffletdata.com/docs/sifflet-mcp-server)).
2. Create an **Editor** API token in Sifflet ([docs](https://docs.siffletdata.com/docs/generate-an-api-token)). Editor is required because the plugin uses one token for both MCP and the Sifflet CLI (`sifflet configure` writes `~/.sifflet/config.ini`, which feeds both), and Monitors as Code `plan`/`apply` and incident actions need Editor. A read-only **Viewer** token is enough only if the user will never apply monitors or mutate incidents from the IDE.
3. Set **`SIFFLET_API_TOKEN`** and **`SIFFLET_BACKEND_URL`** for MCP: the plugin’s MCP configuration forwards those env vars when the IDE can resolve them, and the bundled launcher falls back to **`~/.sifflet/config.ini`** (from **`sifflet configure`**) when they are unset or unresolved placeholders. See **configure-sifflet-auth**. Shell-only exports (**`~/.zshrc`**) are not visible to MCP unless they are also present on the IDE’s app process, so a correct **`echo`** in the integrated terminal does not prove MCP sees the variable. (The Sifflet **CLI** uses a different variable name for the token: **`SIFFLET_TOKEN`**.)
4. Use the backend URL form expected by [sifflet-mcp](https://github.com/siffletdata/sifflet-mcp), usually **`https://<tenant>.siffletdata.com/api/`** (note the **`/api/`** suffix).

## Working style

- Prefer **discovery tools first** (`search_asset`, `asset_by_urn`) so YAML and proposals use real URNs, owners, and tags.
- For **`get_monitor_code_by_description`**: always pass at least one **`dataset_ids`** entry from discovery; before calling, run the **monitor-type questionnaire** in the **sifflet-quality-as-code** skill (step 2) so the **`description`** includes thresholds, time columns, SQL, allowed values, etc., when those inputs are required for that **`parameters.kind`**.
- For monitor authoring, combine MCP results with the **sifflet-quality-as-code** skill and the official schema docs.
- **Most Sifflet MCP tools are read-only.** `open_incident_by_id` and `close_incident_by_id` are **state-mutating** (closing can also qualify a monitor). Treat them as destructive actions: confirm per the destructive-change confirmation protocol in **sifflet-quality-as-code** (typed token **`CONFIRM SIFFLET MUTATE`**) before calling, and never call them just to explore. Apply the same caution to any future mutating tool.
- Do not paste secrets into chat or commit them to the repository.

## Further reading

- [Sifflet MCP server](https://docs.siffletdata.com/docs/sifflet-mcp-server)
- [Monitors as Code](https://docs.siffletdata.com/docs/monitors-as-code)
- [Parameters per monitor type](https://docs.siffletdata.com/docs/parameters-per-monitor-type) (use with **sifflet-quality-as-code** when drafting monitors)
- Upstream project: [github.com/siffletdata/sifflet-mcp](https://github.com/siffletdata/sifflet-mcp)
