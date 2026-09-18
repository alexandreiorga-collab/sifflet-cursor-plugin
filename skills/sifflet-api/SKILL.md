---
name: sifflet-api
description: Call the Sifflet REST API for things the MCP server and CLI cannot do — lineage traversal, bulk export, workspace operations. Use when the user needs lineage data, wants to export monitors as code, or asks for Sifflet data no MCP tool exposes.
---

# Sifflet REST API

Third and last resort. **Prefer MCP for discovery, the CLI for Monitors as Code, and
the API only for what neither covers** — chiefly lineage traversal and bulk export.

## Tell the user when you use the API

Two of the three API surfaces are **alpha**. Whenever you call one, say so in your
answer: which endpoint, and that it is alpha and may change without notice. A user
who does not know they are depending on an unstable interface cannot make an informed
choice about it.

## Surfaces and stability

| Prefix | Stability | Use |
|---|---|---|
| `/api/v2/...` | **Public, documented, stable** | Prefer this whenever it covers the need. See the [API reference](https://docs.siffletdata.com/reference). |
| `/api/v1/...` | **Alpha** | Workspace apply/delete/download, `_all-as-code`, dbt impact analysis. |
| `/api/ui/v1/...` | **Alpha, least stable** | The endpoints backing Sifflet's own UI: lineage, assets, incidents, tags, terms, domains, data products. Shape can change with any UI release. |

Say "alpha" out loud for anything under `/v1/` or `/ui/v1/`.

## Calling it

Always use the bundled helper. It resolves credentials the same way the MCP launcher
does and passes the token straight to curl, so the token never reaches the transcript:

```bash
scripts/sifflet-api.sh GET /ui/v1/lineages/<urn>/downstreams
scripts/sifflet-api.sh --yaml GET /v1/rules/_all-as-code?mode=STRICT
scripts/sifflet-api.sh POST /ui/v1/assets/search --data '{"textSearch":"orders"}'
```

**Never `cat ~/.sifflet/config.ini` to build an Authorization header by hand.** That
puts the token in the conversation, and the guard hook will stop to ask about it. The
helper exists precisely so you never need to. It also refuses curl's `-v` and `--trace*`
flags, which would print the Authorization header — use its own `--verbose` instead,
which shows the request line without the token.

Auth is `Authorization: Bearer <access token>` (JWT). Every endpoint accepts both
`application/json` and `application/x-yaml` — `--yaml` is genuinely useful when the
response is going to become a monitor file.

Base URL: `https://<tenant>.siffletdata.com/api`. Self-hosted instances serve the API
on the same host as the UI; if the deployment sets the `backendApiUrl` Helm value the
`/api` prefix is dropped, in which case set `SIFFLET_API_NO_PREFIX=1`.

## Lineage — the main reason to be here

No MCP tool traverses lineage graphs, so this is the API's primary job. Lineage is
keyed by **URN**, while monitor YAML references datasets by **URI**, so convert first:

```bash
# 1. URI -> URN
scripts/sifflet-api.sh POST /ui/v1/assets/convert-uri-to-urn \
  --data '{"uri":"databricks://<host>/<catalog>.<schema>.<table>"}'

# 2. Traverse
scripts/sifflet-api.sh GET /ui/v1/lineages/<urn>/downstreams
scripts/sifflet-api.sh GET /ui/v1/lineages/<urn>/upstreams
scripts/sifflet-api.sh GET /ui/v1/lineages/<urn>            # immediate neighbourhood
scripts/sifflet-api.sh GET /ui/v1/lineages/<urn>/lineages   # full downstream graph
```

For impact analysis of a dbt change specifically, `POST /v1/impact-analysis/dbt` takes
a project and model name directly and avoids the URN round trip.

## Other endpoints worth knowing

- `GET /v1/rules/_all-as-code` — exports **every** monitor as code (`mode` is
  `RELAXED` | `STRICT` | `EXPANDED`, plus filters for dataset, tag, datasource,
  criticality, domain). The fastest way to see existing monitors as YAML. Note the
  Monitors-as-Code caveat: a UI-managed monitor cannot be converted into a
  code-managed one, so treat the output as a starting point, not a migration.
- `GET /v1/workspaces` — list workspaces.
- `POST /ui/v1/assets/search`, `POST /ui/v1/incidents/search` — read-only despite
  being POSTs.
- `GET /ui/v1/incidents/downstream-impacted-assets` — blast radius of an incident.
- `POST /ui/v1/rules/{id}/failing-rows` — the failing rows behind a monitor run.

## Destructive API calls

**The API can do everything the CLI can. Mutating calls are subject to exactly the
same destructive-change confirmation protocol** in the **sifflet-quality-as-code**
skill — using the API does not lower the bar, and the guard hook gates these too.

| Call | Equivalent to | Required token |
|---|---|---|
| `POST /v1/workspaces/{id}` | `sifflet code workspace apply` | `CONFIRM SIFFLET APPLY` (+ `DELETE <N>`) |
| `POST /v1/workspaces/{id}` with `objectUntrackAction=DELETE` | apply that deletes untracked monitors | `CONFIRM SIFFLET APPLY` + `DELETE <N>` |
| `DELETE /v1/workspaces/{id}` | `sifflet code workspace delete` | `DELETE WORKSPACE` |
| `DELETE /ui/v1/rules/{id}` | deleting a monitor | explicit confirmation |
| `POST`/`PUT`/`PATCH`/`DELETE` on tags, terms, domains, data products | metadata writes | explicit confirmation |

**Always dry-run first.** Both workspace operations accept `dryRun=true`, which is the
API's `plan`. A dry run is safe and ungated — run it, show the output, and only then
ask for the typed token:

```bash
scripts/sifflet-api.sh POST "/v1/workspaces/<id>?dryRun=true" --data @workspace.json
```

Prefer the CLI for workspace apply and delete anyway: it produces a readable plan and
is the documented path. Reach for the API version only when scripting something the
CLI genuinely cannot express.

## Further reading

- [API reference (public v2)](https://docs.siffletdata.com/reference)
- [API overview: deployment models, content types](https://docs.siffletdata.com/reference/overview-1)
- [Access tokens](https://docs.siffletdata.com/docs/access-tokens) — tokens can carry
  per-domain roles, so a token that reads the catalog may still be refused a monitor
  apply. A confusing 403 is usually this.
