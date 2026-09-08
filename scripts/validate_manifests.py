#!/usr/bin/env python3
"""Static validation for the Sifflet plugin repository.

Checks that every JSON manifest parses, that files referenced by manifests and
hook configs actually exist, and that skills/commands carry valid frontmatter.
Run from the repository root:  python3 scripts/validate_manifests.py
Exits non-zero on the first category of failure (all failures are printed).
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors = []


def fail(msg):
    errors.append(msg)


def check_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as e:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {e}")
    return None


def check_exists(rel, source):
    if not (ROOT / rel).exists():
        fail(f"{source} references missing path: {rel}")


def check_frontmatter(path, required=("name", "description")):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        fail(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
        return
    body = m.group(1)
    for key in required:
        if not re.search(rf"^{key}\s*:", body, re.MULTILINE):
            fail(f"{path.relative_to(ROOT)}: frontmatter missing '{key}'")


# --- every .json in the repo must parse -------------------------------------
for p in sorted(ROOT.rglob("*.json")):
    if ".git" in p.parts:
        continue
    check_json(p)

# --- Claude Code plugin manifests -------------------------------------------
plugin = check_json(ROOT / ".claude-plugin" / "plugin.json")
if plugin:
    for key in ("name", "version", "description"):
        if key not in plugin:
            fail(f".claude-plugin/plugin.json missing '{key}'")

marketplace = check_json(ROOT / ".claude-plugin" / "marketplace.json")
if marketplace:
    for entry in marketplace.get("plugins", []):
        src = entry.get("source", "")
        if src and not (ROOT / src).exists():
            fail(f".claude-plugin/marketplace.json plugin source missing: {src}")

# --- Cursor plugin manifest ---------------------------------------------------
cursor = check_json(ROOT / ".cursor-plugin" / "plugin.json")
if cursor:
    for key in ("logo", "hooks"):
        if key in cursor:
            check_exists(cursor[key], ".cursor-plugin/plugin.json")

# --- hook configs must reference the guard script that exists -----------------
GUARD = "hooks/guard-sifflet-destructive.py"
check_exists(GUARD, "repository")
for hooks_file in ("hooks/hooks.json", "hooks/cursor-hooks.json"):
    data = check_json(ROOT / hooks_file)
    if data and GUARD.split("/")[-1] not in json.dumps(data):
        fail(f"{hooks_file} does not reference {GUARD}")

# --- Claude Code hooks must be fail-closed ------------------------------------
claude_hooks = check_json(ROOT / "hooks" / "hooks.json")
if claude_hooks:
    for matcher_entry in claude_hooks.get("hooks", {}).get("PreToolUse", []):
        for hook in matcher_entry.get("hooks", []):
            if not hook.get("command", "").rstrip().endswith("|| exit 2"):
                fail("hooks/hooks.json: command lacks '|| exit 2' fail-closed wrapper")

# --- MCP configs ---------------------------------------------------------------
for mcp_file in ("mcp.json", ".mcp.json"):
    data = check_json(ROOT / mcp_file)
    if data and "sifflet" not in data.get("mcpServers", {}):
        fail(f"{mcp_file}: no 'sifflet' entry under mcpServers")

# --- skills and commands frontmatter -------------------------------------------
for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
    check_frontmatter(skill)
for command in sorted((ROOT / "commands").glob("*.md")):
    check_frontmatter(command)

# --- report --------------------------------------------------------------------
if errors:
    print(f"FAIL: {len(errors)} problem(s)")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("OK: all manifests parse, referenced paths exist, frontmatter valid")
