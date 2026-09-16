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

## Always name the tenant

**Every time you report Sifflet data — incident counts, monitor lists, catalog results, lineage — say which tenant or backend URL it came from.** A bare number cannot be checked against the UI; a number labelled with its tenant can.

This matters because more than one Sifflet MCP server can be connected at once. A server the user added by hand (`claude mcp add`, or imported with `claude mcp add-from-claude-desktop`) and this plugin's bundled server **both load** — Claude Code keys the plugin's as `plugin:<plugin>:sifflet`, so they do not collide and neither is dropped. If they point at different tenants, picking the wrong one returns confidently wrong numbers.

- Before the first Sifflet call in a session, establish which server you are using and which tenant it points at; if two Sifflet servers are connected, say so and ask which the user wants.
- Prefer this plugin's bundled server unless the user says otherwise.
- Never guess the tenant from context. If you cannot determine it, say so rather than reporting unattributed numbers.
- If a user reports numbers that disagree with the Sifflet UI, suspect a second connected server first: `claude mcp list` shows every Sifflet server and its command.

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
