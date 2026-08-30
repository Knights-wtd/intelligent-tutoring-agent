#!/usr/bin/env bash
set -euo pipefail

origin="${AGENT_RUNTIME_ORIGIN:-http://127.0.0.1:8765}"
token="${AGENT_RUNTIME_TOKEN:-}"
timeout="${AGENT_RUNTIME_SMOKE_TIMEOUT_SECONDS:-10}"

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || fail "Node.js 24 is required but node was not found on PATH."
# Required smoke toolchain: Node.js 24 and pnpm 11.
pnpm_command="$(command -v pnpm 2>/dev/null || command -v pnpm.cmd 2>/dev/null || true)"
[[ -n "$pnpm_command" ]] || fail "pnpm 11 is required but pnpm was not found on PATH."
command -v curl >/dev/null 2>&1 || fail "curl is required but was not found on PATH."

node_version="$(node --version)"
node_major="$(printf '%s' "$node_version" | sed -E 's/^v([0-9]+).*/\1/')"
[[ "$node_major" == "24" ]] || fail "Expected Node.js 24, found $node_version"
pnpm_version="$("$pnpm_command" --version)"
pnpm_major="${pnpm_version%%.*}"
[[ "$pnpm_major" == "11" ]] || fail "Expected pnpm 11, found $pnpm_version"
[[ "$timeout" =~ ^[1-9][0-9]*$ ]] || fail "AGENT_RUNTIME_SMOKE_TIMEOUT_SECONDS must be a positive integer."

node - "$origin" <<'NODE' || fail "Runtime smoke origin must be an absolute loopback http URL without credentials, path, query, or fragment."
const value = process.argv[2];
const url = new URL(value);
if (url.protocol !== "http:" || !["127.0.0.1", "::1", "localhost"].includes(url.hostname)) process.exit(1);
if (url.username || url.password || (url.pathname && url.pathname !== "/") || url.search || url.hash) process.exit(1);
NODE
origin="${origin%/}"

curl_args=(--fail --silent --show-error --connect-timeout 3 --max-time "$timeout")
health="$(curl "${curl_args[@]}" "$origin/v1/health")"
printf '%s' "$health" | node -e '
let body = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => body += chunk);
process.stdin.on("end", () => {
  const health = JSON.parse(body);
  if (health.status !== "ok" || health.protocol_version !== "1.0" || !/^24\./.test(health.node_version || "")) process.exit(1);
});
' || fail "Runtime health contract failed."

code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --connect-timeout 3 --max-time "$timeout" "$origin/v1/diagnostics")"
[[ "$code" == "401" ]] || fail "Expected unauthenticated diagnostics to return 401, found $code"

if [[ -n "$token" ]]; then
  [[ "$token" != *$'\n'* && "$token" != *$'\r'* ]] || fail "Runtime token contains an unsafe control character."
  escaped_token="${token//\\/\\\\}"
  escaped_token="${escaped_token//\"/\\\"}"
  diagnostics="$({ printf 'header = "Authorization: Bearer %s"\n' "$escaped_token"; } | curl "${curl_args[@]}" --config - "$origin/v1/diagnostics")"
  printf '%s' "$diagnostics" | node -e '
let body = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => body += chunk);
process.stdin.on("end", () => {
  const diagnostics = JSON.parse(body);
  if (!["ok", "degraded"].includes(diagnostics.status)) process.exit(1);
});
' || fail "Unexpected authenticated diagnostics status."
fi

printf 'Agent Runtime smoke passed: Node %s, pnpm %s.\n' "${node_version#v}" "$pnpm_version"
