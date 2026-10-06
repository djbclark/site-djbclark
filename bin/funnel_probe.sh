#!/bin/bash
# funnel_probe.sh: is the public Tailscale Funnel reachable? (watchdogd probe)
#
# The probe half of ~/.local/libexec/funnel-healthcheck/check.sh (LaunchAgent
# com.djbclark.funnel-healthcheck), moved here when watchdogd absorbed it
# (watchdogd.d/funnel.toml holds the heal: quit and reopen the Tailscale app).
# Background: on 2026-09-24 Funnel ingress died after a Wi-Fi flap while the
# daemon stayed "up"; only quitting and reopening the app fixed it.
#
# Each endpoint is tried straight at Tailscale's public ingress IPs (curl
# --resolve) and through normal DNS. No secrets: an unauthenticated request
# gets 401 on the MCP paths, which proves the whole Funnel -> Mac -> Caddy chain.
#
# Exit 0: at least one endpoint answered from some vantage (prints a summary).
# Exit 1: every endpoint failed from every vantage.
# Exit 75 (EX_TEMPFAIL): this Mac cannot reach the internet, so a Funnel
# failure would mean nothing; watchdogd counts it as a skip.
set -uo pipefail
HOST="${FUNNEL_HOST:-mac.greyhound-sidemirror.ts.net}"
INGRESS_IPS=(209.177.145.97 209.177.145.192)
# label|port|path|expected-code-regex
ENDPOINTS=(
  "hermes-mcp|8443|/hermes-mcp/mcp|401"
  "saner-mcp|8443|/saner-mcp/mcp|401"
  "claude-mcp|8443|/claude-mcp/mcp|401"
  "beeper-10000|10000|/|[1-5][0-9][0-9]"
)

if ! curl -sS -o /dev/null --max-time 10 https://1.1.1.1/ 2>/dev/null &&
  ! curl -sS -o /dev/null --max-time 10 https://www.apple.com/ 2>/dev/null; then
  echo "internet unreachable from this Mac; not a Funnel verdict"
  exit 75
fi

probe() { # label port path expect; 0 if any vantage got an HTTP reply
  local label=$1 port=$2 path=$3 expect=$4 ok=1 detail="" code rc via
  for via in "${INGRESS_IPS[@]}" dns; do
    local args=()
    [ "$via" != dns ] && args=(--resolve "$HOST:$port:$via")
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 ${args[@]+"${args[@]}"} "https://$HOST:$port$path" 2>/dev/null)
    rc=$?
    if [ $rc -eq 0 ] && [ "$code" != 000 ]; then
      ok=0
      [[ "$code" =~ ^($expect)$ ]] || detail+=" WARN($via http=$code want=$expect)"
    else
      detail+=" fail($via curl_rc=$rc)"
    fi
  done
  echo "$label:$([ $ok -eq 0 ] && echo up || echo DOWN)$detail"
  return $ok
}

up=0 total=0 summary=""
for e in "${ENDPOINTS[@]}"; do
  IFS='|' read -r l p pa ex <<<"$e"
  out=$(probe "$l" "$p" "$pa" "$ex")
  r=$?
  total=$((total + 1))
  [ $r -eq 0 ] && up=$((up + 1))
  summary+=" [$out]"
done
echo "$up/$total endpoints up:$summary"
[ "$up" -gt 0 ]
