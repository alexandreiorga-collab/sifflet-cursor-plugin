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
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return out, proc.returncode


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


def test_config_ini_comment_smuggling_still_asks():
    # No carve-outs: mentioning "sifflet configure" in a comment must not
    # exempt a command that touches the token file.
    out, _ = run_guard(cursor_shell("cat ~/.sifflet/config.ini  # sifflet configure"))
    assert cursor_permission(out) == "ask"


# --------------------------------------------------------- Sifflet REST API
# The API can do everything the CLI can, so an ungated API call would be a hole
# straight through every CLI gate. POST /v1/workspaces/{id} is apply;
# DELETE /v1/workspaces/{id} is delete.

API = "https://acme.siffletdata.com/api"


def test_api_workspace_apply_asks():
    out, _ = run_guard(cursor_shell(f"curl -X POST {API}/v1/workspaces/abc-123 -d @ws.json"))
    assert cursor_permission(out) == "ask"
    assert "apply" in out["user_message"].lower()


def test_api_workspace_apply_via_helper_asks():
    out, _ = run_guard(cursor_shell("scripts/sifflet-api.sh POST /v1/workspaces/abc-123 --data @ws.json"))
    assert cursor_permission(out) == "ask"


def test_api_workspace_apply_dry_run_is_not_gated():
    # dryRun=true is the API's `plan` and must stay free, like the CLI's plan.
    out, _ = run_guard(cursor_shell(
        f"curl -X POST '{API}/v1/workspaces/abc-123?dryRun=true' -d @ws.json"))
    assert cursor_permission(out) == "allow"


def test_api_workspace_apply_with_untrack_delete_demands_delete_count():
    out, _ = run_guard(cursor_shell(
        f"curl -X POST '{API}/v1/workspaces/abc?objectUntrackAction=DELETE' -d @ws.json"))
    assert cursor_permission(out) == "ask"
    assert "DELETE <N>" in out["user_message"]


def test_api_workspace_delete_asks_for_workspace_token():
    out, _ = run_guard(cursor_shell(f"curl -X DELETE {API}/v1/workspaces/abc-123"))
    assert cursor_permission(out) == "ask"
    assert "DELETE WORKSPACE" in out["user_message"]


def test_api_workspace_delete_cascade_is_called_out():
    out, _ = run_guard(cursor_shell(
        f"curl -X DELETE '{API}/v1/workspaces/abc?cascadeDelete=ALL'"))
    assert cursor_permission(out) == "ask"
    assert "cascadeDelete=ALL" in out["user_message"]


def test_api_delete_monitor_asks():
    out, _ = run_guard(cursor_shell(f"curl -X DELETE {API}/ui/v1/rules/7edf1177"))
    assert cursor_permission(out) == "ask"


def test_api_put_and_patch_ask():
    for verb in ("PUT", "PATCH"):
        out, _ = run_guard(cursor_shell(f"curl -X {verb} {API}/ui/v1/tags/abc -d '{{}}'"))
        assert cursor_permission(out) == "ask", verb


def test_api_post_body_without_explicit_method_is_treated_as_post():
    out, _ = run_guard(cursor_shell(f"curl {API}/ui/v1/tags --data '{{\"name\":\"x\"}}'"))
    assert cursor_permission(out) == "ask"


def test_api_read_only_posts_are_not_gated():
    # Gating these would break the two most common read calls.
    for path in ("/ui/v1/assets/search", "/ui/v1/incidents/search",
                 "/ui/v1/assets/convert-uri-to-urn", "/ui/v1/rules/abc/failing-rows"):
        out, _ = run_guard(cursor_shell(f"curl -X POST {API}{path} -d '{{}}'"))
        assert cursor_permission(out) == "allow", path


def test_api_lineage_get_is_not_gated():
    for path in ("/ui/v1/lineages/urn:x/downstreams", "/ui/v1/lineages/urn:x/upstreams",
                 "/v1/workspaces", "/v1/rules/_all-as-code?mode=STRICT"):
        out, _ = run_guard(cursor_shell(f"scripts/sifflet-api.sh GET {path}"))
        assert cursor_permission(out) == "allow", path


# Regression tests: every one of these was a live bypass found in review.

def test_api_method_flag_without_space_is_caught():
    out, _ = run_guard(cursor_shell(f"curl -XDELETE {API}/v1/workspaces/abc"))
    assert cursor_permission(out) == "ask"


def test_api_method_flag_with_equals_is_caught():
    out, _ = run_guard(cursor_shell(f"curl --request=DELETE {API}/v1/workspaces/abc"))
    assert cursor_permission(out) == "ask"


def test_api_httpie_positional_verb_is_caught():
    for client in ("http", "https", "xh"):
        out, _ = run_guard(cursor_shell(f"{client} DELETE {API}/v1/workspaces/abc"))
        assert cursor_permission(out) == "ask", client


def test_api_wget_method_flag_is_caught():
    out, _ = run_guard(cursor_shell(f"wget --method=DELETE {API}/v1/workspaces/abc"))
    assert cursor_permission(out) == "ask"


def test_self_hosted_sifflet_is_guarded():
    # Target detection must not depend on siffletdata.com, or every self-hosted
    # deployment is unguarded.
    out, _ = run_guard(cursor_shell("curl -X DELETE https://sifflet.acme.com/api/v1/workspaces/abc"))
    assert cursor_permission(out) == "ask"


def test_backend_url_variable_form_is_guarded():
    # The shape an agent following the skill is most likely to write.
    out, _ = run_guard(cursor_shell("curl -X DELETE $SIFFLET_BACKEND_URL/v1/workspaces/abc"))
    assert cursor_permission(out) == "ask"


def test_read_only_allowlist_cannot_be_laundered_via_a_body_path():
    # A body file whose path contains /search must not buy a pass for a write.
    out, _ = run_guard(cursor_shell(
        "scripts/sifflet-api.sh POST /ui/v1/tags --data @/tmp/search/body.json"))
    assert cursor_permission(out) == "ask"


def test_dry_run_in_a_comment_does_not_disarm_the_apply_gate():
    out, _ = run_guard(cursor_shell(
        f"curl -X POST {API}/v1/workspaces/abc -d @ws.json  # not dryRun=true"))
    assert cursor_permission(out) == "ask"


def test_mentioning_an_endpoint_in_prose_is_not_gated():
    out, _ = run_guard(cursor_shell('echo "see POST /v1/workspaces/abc in the docs"'))
    assert cursor_permission(out) == "allow"


def test_non_sifflet_api_calls_are_not_gated():
    out, _ = run_guard(cursor_shell("curl -X DELETE https://api.github.com/repos/x/y"))
    assert cursor_permission(out) == "allow"


def test_api_gate_applies_on_claude_code_too():
    out, _ = run_guard(claude_bash(f"curl -X DELETE {API}/v1/workspaces/abc"))
    assert claude_permission(out) == "ask"


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


def test_mcp_readonly_tool_defers_to_platform_on_claude():
    # No decision emitted: Claude Code's own permission flow applies. An
    # explicit "allow" would bypass the user's permission settings.
    out, code = run_guard(claude_mcp("mcp__sifflet__search_asset"))
    assert code == 0
    assert out is None


def test_mcp_plugin_scoped_tool_name_asks():
    # A plugin-provided MCP server is keyed `plugin:<plugin>:<server>`, which
    # sanitizes into the tool name mcp__plugin_sifflet_sifflet__<tool>.
    out, _ = run_guard(claude_mcp("mcp__plugin_sifflet_sifflet__close_incident_by_id"))
    assert claude_permission(out) == "ask"


def test_mcp_plugin_scoped_readonly_defers():
    out, code = run_guard(claude_mcp("mcp__plugin_sifflet_sifflet__search_asset"))
    assert code == 0
    assert out is None


def test_hook_matcher_covers_both_mcp_name_shapes():
    """The hooks.json matcher must catch user-scope AND plugin-scope tool names.

    Claude Code names MCP tools mcp__<server>__<tool>. A plugin's server is
    keyed plugin:<plugin>:<server>, so its tools arrive as
    mcp__plugin_<plugin>_<server>__<tool>. A matcher anchored on "mcp__sifflet"
    silently misses the plugin's own tools.
    """
    import re

    hooks = json.loads(
        (GUARD.parent / "hooks.json").read_text(encoding="utf-8")
    )
    matchers = [
        entry["matcher"]
        for entry in hooks["hooks"]["PreToolUse"]
        if entry.get("matcher", "").startswith("mcp__")
    ]
    assert matchers, "no MCP matcher found in hooks/hooks.json"
    for shape in (
        "mcp__sifflet__close_incident_by_id",
        "mcp__plugin_sifflet_sifflet__close_incident_by_id",
    ):
        assert any(re.search(m, shape) for m in matchers), (
            f"no matcher in {matchers} covers {shape}"
        )


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


def test_claude_benign_command_emits_no_decision():
    out, code = run_guard(claude_bash("ls -la"))
    assert code == 0
    assert out is None


def test_claude_dangerous_non_sifflet_command_not_auto_approved():
    # The guard must never auto-approve commands outside its scope on Claude
    # Code; it stays silent and the platform's permission prompt applies.
    out, code = run_guard(claude_bash("rm -rf / --no-preserve-root"))
    assert code == 0
    assert out is None
