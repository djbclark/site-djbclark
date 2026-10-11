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
# Usage: funnel_probe.sh [LABEL...]. No labels: the Funnel set (ENDPOINTS),
# which watchdogd.d/funnel.toml checks and heals. A label may also name an
# endpoint in SEPARATE, which has its own watchdogd check (funnel-beeper.toml).
#
# Mode "any": any HTTP reply counts as up (a code outside the regex is a WARN);
# it proves the Funnel ingress chain. Mode "strict": a code outside the regex
# counts as DOWN. beeper-10000 is strict (djbclark 2026-10-11): with Beeper's
# local API off, Funnel answers 502 for :10000, and that must be reported, not
# counted as up.
#
# Exit 0: at least one selected endpoint is up from some vantage (prints a summary).
# Exit 1: every selected endpoint failed from every vantage.
# Exit 2: an unknown label.
# Exit 75 (EX_TEMPFAIL): this Mac cannot reach the internet, so a Funnel
# failure would mean nothing; watchdogd counts it as a skip.
set -uo pipefail
HOST="${FUNNEL_HOST:-mac.greyhound-sidemirror.ts.net}"
INGRESS_IPS=(209.177.145.97 209.177.145.192)
# label|port|path|expected-code-regex|mode
ENDPOINTS=(
  "hermes-mcp|8443|/hermes-mcp/mcp|401|any"
  "saner-mcp|8443|/saner-mcp/mcp|401|any"
  "claude-mcp|8443|/claude-mcp/mcp|401|any"
)
# Probed only when named; each has its own watchdogd check. Beeper Desktop's
# local API (127.0.0.1:23373) answered 302 when up (2026-09-24); 5xx = down.
SEPARATE=(
  "beeper-10000|10000|/|[1-4][0-9][0-9]|strict"
)

selected=()
if [ $# -eq 0 ]; then
  selected=("${ENDPOINTS[@]}")
else
  for want in "$@"; do
    found=""
    for e in "${ENDPOINTS[@]}" "${SEPARATE[@]}"; do
      [ "${e%%|*}" = "$want" ] && found=$e
    done
    if [ -z "$found" ]; then
      echo "unknown endpoint label: $want" >&2
      exit 2
    fi
    selected+=("$found")
  done
fi

if ! curl -sS -o /dev/null --max-time 10 https://1.1.1.1/ 2>/dev/null &&
  ! curl -sS -o /dev/null --max-time 10 https://www.apple.com/ 2>/dev/null; then
  echo "internet unreachable from this Mac; not a Funnel verdict"
  exit 75
fi

probe() { # label port path expect mode; 0 if any vantage got an acceptable reply
  local label=$1 port=$2 path=$3 expect=$4 mode=$5 ok=1 detail="" code rc via
  for via in "${INGRESS_IPS[@]}" dns; do
    local args=()
    [ "$via" != dns ] && args=(--resolve "$HOST:$port:$via")
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 ${args[@]+"${args[@]}"} "https://$HOST:$port$path" 2>/dev/null)
    rc=$?
    if [ $rc -eq 0 ] && [ "$code" != 000 ]; then
      if [[ "$code" =~ ^($expect)$ ]]; then
        ok=0
      elif [ "$mode" = strict ]; then
        detail+=" bad($via http=$code)"
      else
        ok=0
        detail+=" WARN($via http=$code want=$expect)"
      fi
    else
      detail+=" fail($via curl_rc=$rc)"
    fi
  done
  echo "$label:$([ $ok -eq 0 ] && echo up || echo DOWN)$detail"
  return $ok
}

up=0 total=0 summary=""
for e in "${selected[@]}"; do
  IFS='|' read -r l p pa ex mo <<<"$e"
  out=$(probe "$l" "$p" "$pa" "$ex" "$mo")
  r=$?
  total=$((total + 1))
  [ $r -eq 0 ] && up=$((up + 1))
  summary+=" [$out]"
done
echo "$up/$total endpoints up:$summary"
[ "$up" -gt 0 ]
