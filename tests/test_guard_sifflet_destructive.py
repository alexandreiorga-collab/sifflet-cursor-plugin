"""Tests for hooks/guard-sifflet-destructive.py.

The guard is a stdin -> stdout JSON filter, so these tests exercise the real
contract: feed it a hook event, assert on the JSON decision and exit code.

Run from the repository root:  pytest tests/
"""

import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "guard-sifflet-destructive.py"


def run_guard(payload, raw=None):
    """Run the guard with a JSON event (or raw stdin) and return (decision, exit code)."""
    stdin = raw if raw is not None else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"guard exited {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout), proc.returncode


def cursor_shell(command):
    return {"hook_event_name": "beforeShellExecution", "command": command}


def cursor_mcp(tool_name):
    return {"hook_event_name": "beforeMCPExecution", "tool_name": tool_name}


def claude_bash(command):
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def claude_mcp(tool_name):
    return {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": {}}


def cursor_permission(out):
    return out["permission"]


def claude_permission(out):
    return out["hookSpecificOutput"]["permissionDecision"]


# ---------------------------------------------------------------- benign paths

def test_plain_command_allowed():
    out, _ = run_guard(cursor_shell("ls -la"))
    assert cursor_permission(out) == "allow"
    assert "user_message" not in out


def test_plan_is_not_gated():
    out, _ = run_guard(cursor_shell("sifflet code workspace plan --file workspace.yaml"))
    assert cursor_permission(out) == "allow"


def test_sifflet_configure_allowed():
    out, _ = run_guard(cursor_shell("sifflet configure"))
    assert cursor_permission(out) == "allow"


def test_invalid_stdin_allows_and_exits_zero():
    out, code = run_guard(None, raw="this is not json")
    assert code == 0
    assert cursor_permission(out) == "allow"


def test_empty_stdin_allows():
    out, _ = run_guard(None, raw="")
    assert cursor_permission(out) == "allow"


# ------------------------------------------------------------------- CLI apply

def test_apply_interactive_asks():
    out, _ = run_guard(cursor_shell("sifflet code workspace apply --file workspace.yaml"))
    assert cursor_permission(out) == "ask"
    assert "plan" in out["user_message"].lower()


def test_apply_auto_approve_asks_with_stronger_warning():
    out, _ = run_guard(
        cursor_shell("sifflet code workspace apply --file workspace.yaml --auto-approve")
    )
    assert cursor_permission(out) == "ask"
    assert "NON-INTERACTIVE" in out["user_message"]


def test_apply_yes_flag_asks():
    out, _ = run_guard(cursor_shell("sifflet code workspace apply --file w.yaml --yes"))
    assert cursor_permission(out) == "ask"
    assert "NON-INTERACTIVE" in out["user_message"]


def test_apply_via_claude_bash_event():
    out, _ = run_guard(claude_bash("sifflet code workspace apply --file workspace.yaml"))
    assert claude_permission(out) == "ask"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


# -------------------------------------------------------------- workspace delete

def test_workspace_delete_asks():
    out, _ = run_guard(cursor_shell("sifflet code workspace delete --id 1234-abcd"))
    assert cursor_permission(out) == "ask"
    assert "WORKSPACE" in out["user_message"]
    assert "DELETE WORKSPACE" in out["user_message"]


def test_workspace_delete_via_claude_bash_event():
    out, _ = run_guard(claude_bash("sifflet code workspace delete --id 1234-abcd"))
    assert claude_permission(out) == "ask"


# ------------------------------------------------------------- config.ini reads

def test_cat_config_ini_asks():
    out, _ = run_guard(cursor_shell("cat ~/.sifflet/config.ini"))
    assert cursor_permission(out) == "ask"
    assert "token" in out["user_message"].lower()


def test_grep_config_ini_absolute_path_asks():
    out, _ = run_guard(cursor_shell("grep token /Users/me/.sifflet/config.ini"))
    assert cursor_permission(out) == "ask"


def test_copy_config_ini_asks():
    out, _ = run_guard(cursor_shell("cp ~/.sifflet/config.ini /tmp/backup.ini"))
    assert cursor_permission(out) == "ask"


# ------------------------------------------------------- monitor file rm/mv gates

def test_rm_monitors_dir_asks():
    out, _ = run_guard(cursor_shell("rm -rf monitors/"))
    assert cursor_permission(out) == "ask"


def test_git_rm_workspace_yaml_asks():
    out, _ = run_guard(cursor_shell("git rm workspace.yaml"))
    assert cursor_permission(out) == "ask"


def test_mv_monitor_file_asks():
    out, _ = run_guard(cursor_shell("mv monitors/freshness.yaml monitors/old.yaml"))
    assert cursor_permission(out) == "ask"


def test_rm_unrelated_file_allowed():
    out, _ = run_guard(cursor_shell("rm notes.txt"))
    assert cursor_permission(out) == "allow"


def test_template_removal_not_gated():
    # Documented behavior: template files live outside the apply scope.
    out, _ = run_guard(cursor_shell("rm monitors-drafts/foo.template.yaml"))
    assert cursor_permission(out) == "allow"


# ------------------------------------------------------------------- MCP tools

def test_mcp_close_incident_asks():
    out, _ = run_guard(claude_mcp("mcp__sifflet__close_incident_by_id"))
    assert claude_permission(out) == "ask"


def test_mcp_open_incident_asks_cursor_style_name():
    out, _ = run_guard(cursor_mcp("open_incident_by_id"))
    assert cursor_permission(out) == "ask"


def test_mcp_readonly_tool_allowed():
    out, _ = run_guard(claude_mcp("mcp__sifflet__search_asset"))
    assert claude_permission(out) == "allow"


def test_mcp_future_mutating_verb_asks():
    # Forward-compat heuristic: unknown tool with a mutating verb + sifflet context.
    out, _ = run_guard(claude_mcp("mcp__sifflet__delete_monitor"))
    assert claude_permission(out) == "ask"


# --------------------------------------------------------------- output shapes

def test_cursor_ask_includes_agent_message():
    out, _ = run_guard(cursor_shell("sifflet code workspace apply --file w.yaml"))
    assert set(out) == {"permission", "user_message", "agent_message"}


def test_claude_output_has_hook_specific_shape():
    out, _ = run_guard(claude_bash("sifflet code workspace apply --file w.yaml"))
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "ask"
    assert "permissionDecisionReason" in hso


def test_cursor_event_never_gets_claude_shape():
    out, _ = run_guard(cursor_shell("sifflet code workspace apply --file w.yaml"))
    assert "hookSpecificOutput" not in out
