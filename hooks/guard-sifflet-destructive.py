#!/usr/bin/env python3
"""Cross-platform destructive-action guard for the Sifflet plugin.

Runs as a Cursor hook (`beforeShellExecution` / `beforeMCPExecution`) and as a
Claude Code hook (`PreToolUse`). It reads a single JSON event on stdin and emits
the platform-appropriate decision, asking for explicit user confirmation before
any destructive or potentially-destructive Sifflet action:

  - `sifflet ... apply` (interactive or with --auto-approve/--yes/--force)
  - `sifflet code workspace delete` (removes the workspace AND every attached monitor)
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


def classify_shell(command):
    """Return a confirmation reason for a destructive shell command, else None."""
    if not command:
        return None
    c = command

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
