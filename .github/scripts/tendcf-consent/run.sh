#!/usr/bin/env bash
# Nix side of the tendcf consent job (.github/workflows/tendcf-consent.yml).
#
#   run.sh export    git-archive nixos/ at the base and the head commit into $WORK
#   run.sh summary   SUMMARY: services.cfengine-tendcf as JCS JSON at base and head
#   run.sh checks    the two hard checks, on the head configuration
#   run.sh effect    build both toplevels, nix store diff-closures
#
# Env: BASE_SHA, HEAD_SHA, WORK (scratch dir); HOST (default vps-primary).
# Both sides are evaluated as `path:` flakes from a clean export, so neither carries a git
# revision and the closure diff shows content only. Design: docs/tendcf-consent.md.
set -euo pipefail

: "${BASE_SHA:?}" "${HEAD_SHA:?}" "${WORK:?}"
HOST="${HOST:-vps-primary}"
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

flake() { printf 'path:%s/%s/nixos' "$WORK" "$1"; }

do_export() {
  rm -rf "${WORK:?}/base" "${WORK:?}/head"
  mkdir -p "$WORK/base" "$WORK/head"
  git archive "$BASE_SHA" nixos | tar -x -C "$WORK/base"
  git archive "$HEAD_SHA" nixos | tar -x -C "$WORK/head"
}

do_summary() {
  # shellcheck disable=SC2016  # a Nix expression: ${c.package} is Nix interpolation
  local apply='c: { enable = c.enable; execd.enable = c.execd.enable; version = c.package.version; package = builtins.unsafeDiscardStringContext "${c.package}"; }'
  local side present
  for side in base head; do
    present=$(nix eval --json "$(flake "$side")#nixosConfigurations.$HOST.options.services" \
      --apply 'o: o ? "cfengine-tendcf"')
    if [ "$present" != true ]; then
      # Only the base may lack the module (the PR that adds it); the head must have it.
      [ "$side" = base ] || { echo "::error::$side has no services.cfengine-tendcf option"; return 1; }
      echo '{"absent":"services.cfengine-tendcf does not exist at base"}' > "$WORK/summary-$side.json"
      continue
    fi
    nix eval --json "$(flake "$side")#nixosConfigurations.$HOST.config.services.cfengine-tendcf" \
      --apply "$apply" > "$WORK/summary-$side.raw"
    jq -cS . "$WORK/summary-$side.raw" > "$WORK/summary-$side.json"
  done
  echo "base: $(cat "$WORK/summary-base.json")"
  echo "head: $(cat "$WORK/summary-head.json")"
}

do_checks() {
  local rc=0 out="$WORK/checks.txt" want got
  : > "$out"

  # Hard check 2: the declared option set is exactly {enable, execd.enable, package}.
  want='{"execd":["enable"],"top":["enable","execd","package"]}'
  nix eval --json "$(flake head)#nixosConfigurations.$HOST.options.services.cfengine-tendcf" \
    --apply 'o: { top = builtins.attrNames o; execd = builtins.attrNames o.execd; }' > "$WORK/check2.raw"
  got=$(jq -cS . "$WORK/check2.raw")
  if [ "$got" = "$want" ]; then
    echo "check 2 (declared option set): PASS $got" | tee -a "$out"
  else
    echo "check 2 (declared option set): FAIL got $got, want $want" | tee -a "$out"
    echo "::error::services.cfengine-tendcf declares options other than enable, execd.enable, package; the summary must cover a new option first"
    rc=1
  fi

  # Hard check 1: no cf-execd unit and no unit that runs cf-execd or cf-agent.
  nix eval --json "$(flake head)#nixosConfigurations.$HOST.config.systemd" \
    --apply "$(cat "$HERE/check1.nix")" > "$WORK/check1.json"
  if jq -e '.execdUnitPresent == false and (.hits | length) == 0' "$WORK/check1.json" > /dev/null; then
    echo "check 1 (no cf-execd/cf-agent unit): PASS" | tee -a "$out"
  else
    echo "check 1 (no cf-execd/cf-agent unit): FAIL $(jq -c . "$WORK/check1.json")" | tee -a "$out"
    echo "::error::the $HOST configuration runs, or cannot be proven free of, cf-execd/cf-agent"
    rc=1
  fi
  return "$rc"
}

do_effect() {
  local attr="nixosConfigurations.$HOST.config.system.build.toplevel" base head
  base=$(nix build --print-out-paths --no-link --print-build-logs "$(flake base)#$attr")
  head=$(nix build --print-out-paths --no-link --print-build-logs "$(flake head)#$attr")
  echo "base toplevel $base"
  echo "head toplevel $head"
  nix store diff-closures "$base" "$head" > "$WORK/effect.txt"
  cat "$WORK/effect.txt"
}

case "${1:-}" in
  export) do_export ;;
  summary) do_summary ;;
  checks) do_checks ;;
  effect) do_effect ;;
  *) echo "usage: run.sh export|summary|checks|effect" >&2; exit 2 ;;
esac
