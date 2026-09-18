#!/usr/bin/env python3
"""Cross-platform destructive-action guard for the Sifflet plugin.

Runs as a Cursor hook (`beforeShellExecution` / `beforeMCPExecution`) and as a
Claude Code hook (`PreToolUse`). It reads a single JSON event on stdin and emits
the platform-appropriate decision, asking for explicit user confirmation before
any destructive or potentially-destructive Sifflet action:

  - `sifflet ... apply` (interactive or with --auto-approve/--yes/--force)
  - `sifflet code workspace delete` (removes the workspace AND every attached monitor)
  - mutating Sifflet REST API calls, which otherwise bypass every CLI gate above
    (`POST /v1/workspaces/{id}` is apply, `DELETE /v1/workspaces/{id}` is delete)
  - reading or copying `~/.sifflet/config.ini` (stores the API token in plain text)
  - removing/renaming monitor or workspace YAML (incl. `rm -rf monitors/`)
  - mutating Sifflet MCP tools (open/close incident, + forward-compat verbs)

The matching decision is "ask" (never silently allow these). Configure the hook
with failClosed (Cursor) or `|| exit 2` (Claude Code) so a crash blocks the
action rather than letting it through.
"""

import json
import re
import sys

MUTATING_MCP_TOOLS = ("open_incident_by_id", "close_incident_by_id")

# Forward-compatibility: future MCP tools whose name implies a write/delete.
MUTATING_VERB_RE = re.compile(
    r"(?:^|[_.])(?:delete|create|update|apply|remove|qualify|set|patch)(?:[_.]|$)",
    re.IGNORECASE,
)

# Template files live outside the apply scope; their removal is not gated.
TEMPLATE_RE = re.compile(r"(?:\.template\.ya?ml\b|/templates/)", re.IGNORECASE)

# Monitor / workspace source files whose removal or rename is destructive.
MONITOR_PATH_RE = re.compile(r"(?:workspace\.ya?ml|monitors/)", re.IGNORECASE)

# ~/.sifflet/config.ini stores the API token in plain text; touching it can leak
# the secret into the conversation or delete the local credentials.
SIFFLET_CONFIG_RE = re.compile(r"\.sifflet[/\\]config\.ini", re.IGNORECASE)

# ── Sifflet REST API ──────────────────────────────────────────────────────────
# The API can do everything the CLI can, so an ungated API call is a hole
# straight through the CLI gates above. Recognise both the bundled helper and a
# direct HTTP client aimed at a Sifflet host.
# Target detection must NOT depend on the hostname: self-hosted Sifflet is served
# from the customer's own domain, and an agent following the skill will typically
# write "$SIFFLET_BACKEND_URL/v1/...". So recognise the API by its path shape too.
SIFFLET_HOST_RE = re.compile(r"[A-Za-z0-9._-]*\.siffletdata\.com", re.IGNORECASE)
SIFFLET_HELPER_RE = re.compile(r"\bsifflet-api(?:\.sh)?\b", re.IGNORECASE)
SIFFLET_API_PATH_RE = re.compile(
    r"/(?:api/)?(?:ui/)?v[12]/"
    r"(?:workspaces|rules|assets|incidents|tags|terms|domains|data-products"
    r"|lineages|datasets|dataset-fields|collaboration-tools|sources"
    r"|impact-analysis|datasources|integrations|statistics|dashboards)\b",
    re.IGNORECASE,
)
# An HTTP client in command position — anchored so that the "https" inside a URL
# is not mistaken for httpie, which made the old check a no-op.
HTTP_CLIENT_RE = re.compile(
    r"(?:^|[|;&(]\s*)(?:sudo\s+)?(?:curl|wget|xh|httpie|https?)\b", re.IGNORECASE
)
HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

# POST endpoints that read rather than write. Keep this list tight and explicit:
# a blunt "POST means write" rule would gate asset and incident search, which are
# the two most common read calls, and make the plugin unusable.
API_READ_ONLY_POST_RE = re.compile(
    r"/(?:search|_download|failing-rows|count-preview|convert-uri-to-urn"
    r"|form-fields|_debug)\b",
    re.IGNORECASE,
)

# A dry run is the API's equivalent of `plan` — safe, and must stay ungated.
API_DRY_RUN_RE = re.compile(r"\bdryRun=true\b", re.IGNORECASE)

CURSOR_AGENT_MESSAGE = (
    "Sifflet guardrail intercepted a destructive or potentially-destructive action. "
    "Follow the destructive-change confirmation protocol in the sifflet-quality-as-code "
    "skill (show the plan diff and collect the typed confirmation token) before proceeding."
)


def _load_event():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _api_method(c):
    """Best-effort HTTP method for a Sifflet API invocation."""
    # curl -X POST / -XPOST / --request=POST, and wget --method=DELETE.
    m = re.search(r"(?:-X|--request|--method)\s*=?\s*['\"]?([A-Za-z]+)", c)
    if m and m.group(1).upper() in HTTP_VERBS:
        return m.group(1).upper()
    # Bundled helper form: sifflet-api.sh [--yaml] POST /v1/workspaces/<id>
    m = re.search(r"sifflet-api(?:\.sh)?\s+(?:--\S+\s+)*([A-Za-z]+)\b", c, re.IGNORECASE)
    if m and m.group(1).upper() in HTTP_VERBS:
        return m.group(1).upper()
    # httpie / xh positional form: http DELETE <url>, https POST <url>, xh PUT <url>
    m = re.search(
        r"(?:^|[|;&(]\s*)(?:sudo\s+)?(?:https?|xh|httpie)\s+(?:-{1,2}\S+\s+)*([A-Za-z]+)\b",
        c,
        re.IGNORECASE,
    )
    if m and m.group(1).upper() in HTTP_VERBS:
        return m.group(1).upper()
    # A body without an explicit method means POST for curl and httpie alike.
    if re.search(r"(--data\b|--data-raw\b|--data-binary\b|--json\b|\s-d\s|--upload-file\b|\s-T\s)", c):
        return "POST"
    return "GET"


def _api_targets(c):
    """The URL/path-looking tokens of a command.

    Allow-listing and dryRun detection are matched against these only, so that a
    body file named .../search/body.json cannot launder a write past the
    read-only allowlist, and a trailing "# not dryRun=true" comment cannot
    disarm the apply gate.
    """
    return " ".join(
        re.findall(
            r"(?:https?://[^\s'\"]+"
            r"|\$\{?[A-Za-z_]\w*\}?/[^\s'\"]*"
            r"|/(?:api/)?(?:ui/)?v[12]/[^\s'\"]*)",
            c,
        )
    )


def classify_api(command):
    """Return a confirmation reason for a mutating Sifflet REST API call, else None."""
    c = command
    targets = _api_targets(c)

    aimed_at_sifflet = bool(
        SIFFLET_HOST_RE.search(c)
        or SIFFLET_HELPER_RE.search(c)
        or SIFFLET_API_PATH_RE.search(targets)
    )
    if not aimed_at_sifflet:
        return None

    method = _api_method(c)

    # Require something that plausibly performs the request, so that merely
    # mentioning a path in prose does not trip the gate. An explicit verb flag
    # alongside a Sifflet path is itself sufficient evidence.
    looks_like_a_request = bool(
        HTTP_CLIENT_RE.search(c)
        or SIFFLET_HELPER_RE.search(c)
        or re.search(r"(?:-X|--request|--method)\s*=?\s*['\"]?[A-Za-z]+", c)
    )
    if not looks_like_a_request:
        return None

    dry_run = bool(API_DRY_RUN_RE.search(targets))
    workspace_path = re.search(r"/(?:api/)?v[12]/workspaces/[^/\s?&'\"]+", targets)

    if method == "POST" and workspace_path and not re.search(r"/_download\b", targets):
        if dry_run:
            return None  # dryRun=true is the API's `plan`
        if re.search(r"objectUntrackAction=DELETE", targets, re.IGNORECASE):
            return (
                "This applies a workspace over the API with objectUntrackAction=DELETE, "
                "which DELETES every monitor no longer tracked by the workspace, along "
                "with its history. It is the API equivalent of `sifflet code workspace "
                "apply` and is subject to the same destructive-change confirmation "
                "protocol: run it with dryRun=true first, then collect the typed tokens "
                "CONFIRM SIFFLET APPLY and DELETE <N>."
            )
        return (
            "This applies a workspace over the API (POST /v1/workspaces/{id}) — the API "
            "equivalent of `sifflet code workspace apply`. It mutates the remote workspace "
            "and may delete or recreate monitors. Re-run with dryRun=true to see the plan, "
            "then follow the destructive-change confirmation protocol (CONFIRM SIFFLET APPLY)."
        )

    if method == "DELETE" and re.search(r"/(?:api/)?v[12]/workspaces/", targets):
        if dry_run:
            return None
        cascade = re.search(r"cascadeDelete=(ALL|MONITORS)", targets, re.IGNORECASE)
        extra = (
            f" cascadeDelete={cascade.group(1).upper()} also deletes the attached monitors "
            "and all their data."
            if cascade
            else ""
        )
        return (
            "This deletes a Sifflet WORKSPACE over the API (DELETE /v1/workspaces/{id}) — "
            "the API equivalent of `sifflet code workspace delete`, and it cannot be undone."
            + extra
            + " Re-run with dryRun=true first, then collect the typed token DELETE WORKSPACE."
        )

    if method in {"PUT", "PATCH", "DELETE"}:
        return (
            f"This is a state-changing Sifflet API call ({method}). It writes to Sifflet "
            "without going through the CLI, so no plan output exists for it. Confirm "
            "explicitly, per the destructive-change confirmation protocol, before running it."
        )

    if method == "POST" and not API_READ_ONLY_POST_RE.search(targets):
        return (
            "This POSTs to the Sifflet API, which creates or changes state (tags, terms, "
            "domains, data products, collaboration-tool items, workspaces). Confirm "
            "explicitly before running it; read-only POSTs such as /search, /failing-rows "
            "and /convert-uri-to-urn are not gated."
        )

    return None


def classify_shell(command):
    """Return a confirmation reason for a destructive shell command, else None."""
    if not command:
        return None
    c = command

    api_reason = classify_api(c)
    if api_reason:
        return api_reason

    if re.search(r"\bsifflet\b.*\bapply\b", c):
        if re.search(r"(--auto-approve|--yes|\s-y(\s|$)|--force)", c):
            return (
                "This is a NON-INTERACTIVE Sifflet apply (--auto-approve/--yes/--force). "
                "It mutates the remote workspace with no further prompt, including any "
                "monitor deletions or recreations. Confirm explicitly before running."
            )
        return (
            "This applies Monitors-as-Code changes to the remote Sifflet workspace and may "
            "delete or recreate monitors (recreation loses history). Confirm after reviewing "
            "the plan diff."
        )

    if re.search(r"\bsifflet\b.*\bworkspace\s+delete\b", c):
        return (
            "This deletes a Sifflet WORKSPACE and every monitor attached to it, with all "
            "associated data (runs, incidents, history). This cannot be undone. Follow the "
            "destructive-change confirmation protocol (typed token DELETE WORKSPACE) before "
            "running it."
        )

    # No exemptions here: an agent composes the command string, so any
    # "unless it mentions X" carve-out is a one-comment bypass.
    if SIFFLET_CONFIG_RE.search(c):
        return (
            "This command touches ~/.sifflet/config.ini, which stores the Sifflet API token "
            "in plain text. Reading or copying it can leak the secret into the conversation. "
            "Prefer the SIFFLET_API_TOKEN / SIFFLET_TOKEN environment variables or the "
            "bundled launcher; confirm explicitly if direct access is truly required."
        )

    if re.search(r"\b(rm|git\s+rm|mv)\b", c) and not TEMPLATE_RE.search(c):
        if MONITOR_PATH_RE.search(c):
            return (
                "This removes or renames Sifflet monitor source files. On the next apply this "
                "can DELETE the corresponding remote monitors and their history. Confirm before "
                "proceeding."
            )
    return None


def _sifflet_context(event, tool_name):
    parts = [
        tool_name or "",
        str(event.get("url") or ""),
        str(event.get("command") or ""),
        str(event.get("tool_input") or ""),
    ]
    return "sifflet" in " ".join(parts).lower()


def classify_mcp(tool_name, event):
    """Return a confirmation reason for a mutating Sifflet MCP tool, else None."""
    if not tool_name:
        return None
    base = tool_name.split("__")[-1]
    if base in MUTATING_MCP_TOOLS:
        return (
            f"The Sifflet MCP tool '{base}' changes state in Sifflet (opening/closing "
            "incidents, and closing can qualify a monitor). Confirm before it runs."
        )
    if MUTATING_VERB_RE.search(base) and _sifflet_context(event, tool_name):
        return (
            f"The Sifflet MCP tool '{base}' looks state-mutating. Confirm before it runs."
        )
    return None


# Cursor sends camelCase event names (and also includes hook_event_name), so we cannot
# treat the mere presence of hook_event_name as "Claude Code". Claude Code uses PascalCase
# event names such as "PreToolUse". Default to Cursor when the platform is ambiguous.
CURSOR_EVENT_NAMES = {
    "beforeShellExecution",
    "afterShellExecution",
    "beforeMCPExecution",
    "afterMCPExecution",
    "beforeReadFile",
    "preToolUse",
    "postToolUse",
}


def _is_claude(event):
    name = event.get("hook_event_name") or ""
    if name in CURSOR_EVENT_NAMES:
        return False
    return name[:1].isupper()


def respond(event, permission, reason=None):
    if _is_claude(event):
        if permission == "allow":
            # Emit no decision so Claude Code's own permission flow applies.
            # An explicit "allow" here would BYPASS the user's permission
            # settings for every command the guard does not flag.
            return
        out = {
            "hookSpecificOutput": {
                "hookEventName": event.get("hook_event_name", "PreToolUse"),
                "permissionDecision": permission,
            }
        }
        if reason:
            out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    else:
        out = {"permission": permission}
        if reason:
            out["user_message"] = reason
            out["agent_message"] = CURSOR_AGENT_MESSAGE
    sys.stdout.write(json.dumps(out))


def main():
    event = _load_event()

    tool_name = event.get("tool_name") or ""
    tool_input = event.get("tool_input")
    command = event.get("command") or ""

    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            tool_input = {}
    if not command and isinstance(tool_input, dict):
        command = tool_input.get("command") or ""

    reason = None
    if command:
        reason = classify_shell(command)
    if reason is None and tool_name and tool_name.lower() != "bash":
        reason = classify_mcp(tool_name, event)

    respond(event, "ask" if reason else "allow", reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
