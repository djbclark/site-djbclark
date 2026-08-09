#!/usr/bin/env bash
# Verify the provider APIs used by the Bluehost migration inventory.
# The migration itself is complete; this is a reusable, read-only health check.

set -euo pipefail

: "${HETZNER_CLOUD_TOKEN:?HETZNER_CLOUD_TOKEN is not available through SecretSpec}"
: "${SPACESHIP_API_TOKEN:?SPACESHIP_API_TOKEN is not available through SecretSpec}"
: "${SPACESHIP_API_SECRET:?SPACESHIP_API_SECRET is not available through SecretSpec}"

workdir=$(mktemp -d "${TMPDIR:-/tmp}/migration-api-test.XXXXXX")
trap 'rm -rf "$workdir"' EXIT

printf '%s\n' '=== Migration API Test (read-only) ==='

printf '%s' 'Hetzner Cloud API: '
hz_status=$(curl -sS --fail-with-body --max-time 20 \
  -o "$workdir/hetzner.json" -w '%{http_code}' \
  -H "Authorization: Bearer ${HETZNER_CLOUD_TOKEN}" \
  'https://api.hetzner.cloud/v1/servers/131169181')
printf 'HTTP %s\n' "$hz_status"
if [[ "$hz_status" != 200 ]]; then
  jq -r '.error.message // .message // "request failed"' "$workdir/hetzner.json" 2>/dev/null || true
  exit 1
fi
jq -c '{name: .server.name, status: .server.status, public_ip: .server.public_net.ipv4.ip, image: .server.image.name}' \
  "$workdir/hetzner.json"

printf '%s' 'Spaceship Domains API: '
sp_status=$(curl -sS --fail-with-body --max-time 20 \
  -o "$workdir/spaceship.json" -w '%{http_code}' \
  -H "X-Api-Key: ${SPACESHIP_API_TOKEN}" \
  -H "X-Api-Secret: ${SPACESHIP_API_SECRET}" \
  -H 'Accept: application/json' \
  'https://spaceship.dev/api/v1/domains?take=100&skip=0')
printf 'HTTP %s\n' "$sp_status"
if [[ "$sp_status" != 200 ]]; then
  jq -r '.error.message // .message // "request failed"' "$workdir/spaceship.json" 2>/dev/null || true
  exit 1
fi
jq -c 'if type == "array" then . else (.domains // .items // []) end | .[] | {domain: (.domain // .name), expirationDate, autoRenew, status: (.status // .lifecycleStatus)}' \
  "$workdir/spaceship.json"

printf '%s\n' 'All provider checks passed.'
