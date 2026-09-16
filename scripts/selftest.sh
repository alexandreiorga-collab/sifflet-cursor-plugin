#!/usr/bin/env bash
# Offline self-test for the Sifflet plugin's safety guardrail.
#
# Verifies the installed guard hook without touching Sifflet: no token, no
# tenant, no network. Run it after installing or updating the plugin.
#
#   bash scripts/selftest.sh                 # from a clone of this repo
#   bash <path-to-installed-plugin>/scripts/selftest.sh
#
# Exit code 0 = all checks passed.

set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GUARD="$ROOT/hooks/guard-sifflet-destructive.py"
HOOKS="$ROOT/hooks/hooks.json"
pass=0; fail=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
head_() { printf '\n%s\n' "$1"; }

[ -f "$GUARD" ] || { echo "guard script not found at $GUARD"; exit 1; }
command -v python3 >/dev/null || { echo "python3 not on PATH (the guard needs it)"; exit 1; }

# decision <json-event>  -> prints the guard's stdout
decision() { printf '%s' "$1" | python3 "$GUARD" 2>/dev/null; }

expect_ask() {  # name, event
  local out; out=$(decision "$2")
  case "$out" in *'"ask"'*) ok "$1" ;; *) bad "$1 (got: ${out:-<empty>})" ;; esac
}
expect_silent() {  # name, event  — no decision: platform permissions apply
  local out; out=$(decision "$2")
  [ -z "$out" ] && ok "$1" || bad "$1 (expected no output, got: $out)"
}
expect_allow() {  # name, event  — Cursor-shaped explicit allow
  local out; out=$(decision "$2")
  case "$out" in *'"allow"'*) ok "$1" ;; *) bad "$1 (got: ${out:-<empty>})" ;; esac
}

cursor() { printf '{"hook_event_name":"beforeShellExecution","command":%s}' "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")"; }
bash_ev() { printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":%s}}' "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")"; }
mcp_ev()  { printf '{"hook_event_name":"PreToolUse","tool_name":"%s","tool_input":{}}' "$1"; }

head_ "Destructive actions must ASK"
expect_ask "sifflet apply"                  "$(bash_ev 'sifflet code workspace apply --file workspace.yaml')"
expect_ask "sifflet apply --auto-approve"   "$(bash_ev 'sifflet code workspace apply --file w.yaml --auto-approve')"
expect_ask "workspace delete"               "$(bash_ev 'sifflet code workspace delete --id abc')"
expect_ask "rm -rf monitors/"               "$(bash_ev 'rm -rf monitors/')"
expect_ask "read ~/.sifflet/config.ini"     "$(bash_ev 'cat ~/.sifflet/config.ini')"
expect_ask "config.ini comment-smuggled"    "$(bash_ev 'cat ~/.sifflet/config.ini  # sifflet configure')"

head_ "MCP mutations must ASK (both tool-name shapes)"
expect_ask "user-scope server"              "$(mcp_ev 'mcp__sifflet__close_incident_by_id')"
expect_ask "plugin-scope server"            "$(mcp_ev 'mcp__plugin_sifflet_sifflet__close_incident_by_id')"

head_ "Safe actions must NOT be blocked"
expect_silent "read-only MCP tool"          "$(mcp_ev 'mcp__plugin_sifflet_sifflet__search_asset')"
expect_silent "benign shell command"        "$(bash_ev 'ls -la')"
expect_allow  "sifflet plan (Cursor event)" "$(cursor 'sifflet code workspace plan --file workspace.yaml')"

head_ "Guard must never auto-approve on Claude Code"
expect_silent "dangerous non-Sifflet command" "$(bash_ev 'rm -rf / --no-preserve-root')"

head_ "Hook config"
if [ -f "$HOOKS" ]; then
  python3 - "$HOOKS" <<'PY' && ok "fail-closed wrapper + matcher covers both MCP shapes" || bad "hooks.json misconfigured"
import json, re, sys
h = json.load(open(sys.argv[1]))
entries = h["hooks"]["PreToolUse"]
assert all(e["hooks"][0]["command"].rstrip().endswith("|| exit 2") for e in entries)
ms = [e["matcher"] for e in entries if e.get("matcher","").startswith("mcp__")]
assert ms
for shape in ("mcp__sifflet__close_incident_by_id",
              "mcp__plugin_sifflet_sifflet__close_incident_by_id"):
    assert any(re.search(m, shape) for m in ms), shape
PY
else
  bad "hooks/hooks.json not found"
fi

out=$( (PATH=/nonexistent python3 "$GUARD" >/dev/null 2>&1 || exit 2); echo $? )
[ "$out" = "2" ] && ok "fails closed when python3 is unavailable" \
                 || bad "fail-closed check returned $out, expected 2"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
