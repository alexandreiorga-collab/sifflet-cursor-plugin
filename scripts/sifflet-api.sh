#!/usr/bin/env bash
# Call the Sifflet REST API without ever exposing the access token.
#
# The token is read from the environment or ~/.sifflet/config.ini inside this
# script and passed straight to curl. It is never printed, never echoed, and
# never has to pass through an agent's context.
#
#   scripts/sifflet-api.sh GET  /ui/v1/lineages/<urn>/downstreams
#   scripts/sifflet-api.sh GET  /v1/workspaces
#   scripts/sifflet-api.sh POST /ui/v1/assets/search --data '{"textSearch":"orders"}'
#   scripts/sifflet-api.sh --yaml GET /v1/rules/_all-as-code?mode=STRICT
#
# Options:
#   --yaml          request application/x-yaml instead of application/json
#   --verbose       print the request line (never the token) to stderr
#   any other flags are passed through to curl
#
# Exit codes: curl's, plus 2 for usage/config errors.

set -uo pipefail

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

ACCEPT="application/json"
VERBOSE=0
ARGS=()
METHOD=""
ENDPOINT=""

# Leading options, then METHOD, then ENDPOINT positionally, then curl passthrough.
# Taking the method and endpoint positionally avoids mistaking a flag's argument
# for the endpoint: `--output /tmp/out.bin /v1/workspaces` used to read
# /tmp/out.bin as the endpoint.
while [ $# -gt 0 ]; do
  case "$1" in
    --yaml)    ACCEPT="application/x-yaml"; shift ;;
    --verbose) VERBOSE=1; shift ;;
    -h|--help) usage ;;
    *) break ;;
  esac
done

case "${1-}" in
  GET|POST|PUT|PATCH|DELETE|HEAD) METHOD="$1"; shift ;;
  *) echo "sifflet-api: first argument must be an HTTP method (got '${1-}')" >&2; usage ;;
esac

case "${1-}" in
  /*) ENDPOINT="$1"; shift ;;
  *) echo "sifflet-api: second argument must be an endpoint path starting with / (got '${1-}')" >&2; usage ;;
esac

# Anything curl would use to dump headers would print the Authorization header,
# which defeats the entire point of this script. Refuse rather than leak.
while [ $# -gt 0 ]; do
  case "$1" in
    -v|--verbose-curl|--trace|--trace-ascii|--trace-config|--trace-ids|--trace-time|--libcurl)
      echo "sifflet-api: refusing '$1' — it would print the Authorization header." >&2
      echo "             Use --verbose for the request line without the token." >&2
      exit 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

[ -n "$METHOD" ]   || { echo "sifflet-api: no HTTP method given" >&2; usage; }
[ -n "$ENDPOINT" ] || { echo "sifflet-api: no endpoint path given (must start with /)" >&2; usage; }

# ── Credentials ───────────────────────────────────────────────────────────────
# Same resolution order as the MCP launcher: explicit env wins, then the file
# written by `sifflet configure`. Placeholder values like ${env:FOO} are treated
# as unset, which is what an IDE leaves behind when it cannot resolve a variable.
for name in SIFFLET_API_TOKEN SIFFLET_TOKEN SIFFLET_BACKEND_URL; do
  v="${!name-}"
  if [ -n "$v" ] && [[ "$v" == *'${'* ]]; then unset "$name"; fi
done

TOKEN="${SIFFLET_API_TOKEN:-${SIFFLET_TOKEN:-}}"
BASE="${SIFFLET_BACKEND_URL:-}"
CFG="${SIFFLET_CONFIG_INI:-$HOME/.sifflet/config.ini}"

if { [ -z "$TOKEN" ] || [ -z "$BASE" ]; } && [ -f "$CFG" ] && command -v python3 >/dev/null 2>&1; then
  eval "$(python3 - "$CFG" <<'PY'
import configparser, os, shlex, sys
cp = configparser.ConfigParser()
cp.read(sys.argv[1], encoding="utf-8")
app = cp["APP"] if "APP" in cp else {}
tenant = (app.get("tenant") or "").strip()
backend = (app.get("backend_url") or "").strip()
token = (app.get("token") or "").strip()
out = []
if token and not (os.environ.get("SIFFLET_API_TOKEN") or os.environ.get("SIFFLET_TOKEN")):
    out.append("TOKEN=" + shlex.quote(token))
if not os.environ.get("SIFFLET_BACKEND_URL"):
    url = backend if backend.startswith(("http://", "https://")) else (
        "https://" + backend.lstrip("/") if backend else
        (f"https://{tenant}.siffletdata.com/api/" if tenant else "")
    )
    if url:
        out.append("BASE=" + shlex.quote(url))
print("\n".join(out))
PY
)"
fi

[ -n "$TOKEN" ] || { echo "sifflet-api: no access token. Run 'sifflet configure' or set SIFFLET_API_TOKEN." >&2; exit 2; }
[ -n "$BASE" ]  || { echo "sifflet-api: no backend URL. Run 'sifflet configure' or set SIFFLET_BACKEND_URL." >&2; exit 2; }

# ── Base URL shapes ───────────────────────────────────────────────────────────
# SaaS:        https://<tenant>.siffletdata.com/api  + /v1/...  or /ui/v1/...
# Self-hosted: same host as the UI, also under /api
# Self-hosted with a custom backendApiUrl Helm value: the /api prefix is dropped.
# Normalise so the caller always passes paths like /v1/... or /ui/v1/...
BASE="${BASE%/}"
if [[ "$BASE" != */api ]] && [[ "${SIFFLET_API_NO_PREFIX:-0}" != "1" ]]; then
  BASE="$BASE/api"
fi
URL="$BASE$ENDPOINT"

[ "$VERBOSE" -eq 1 ] && printf '[sifflet-api] %s %s\n' "$METHOD" "$URL" >&2

# The Authorization header goes in via curl's stdin config, not argv, so the token
# is never visible in `ps` to other processes owned by the same user.
# Consequence: this script cannot stream a request body from stdin (`--data @-`).
# Pass bodies as a literal or a file path instead: --data '{...}' or --data @file.
curl --silent --show-error --fail-with-body \
     --config - \
     --request "$METHOD" \
     --header "Accept: $ACCEPT" \
     --header "Content-Type: application/json" \
     "${ARGS[@]+"${ARGS[@]}"}" \
     "$URL" <<CURL_CONFIG
header = "Authorization: Bearer $TOKEN"
CURL_CONFIG
