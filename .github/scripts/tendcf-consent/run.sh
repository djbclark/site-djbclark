#!/usr/bin/env bash
# Nix side of the tendcf consent job (.github/workflows/tendcf-consent.yml).
#
#   run.sh export    git-archive nixos/ at the base and the head commit into $WORK
#   run.sh export-head  the same for the head only (the push job needs no base)
#   run.sh summary   SUMMARY: services.cfengine-tendcf as JCS JSON at base and head
#   run.sh checks    the two hard checks, on the head configuration
#   run.sh effect    build both toplevels, nix store diff-closures
#
# Env: BASE_SHA (not for export-head, checks), HEAD_SHA, WORK (scratch dir); HOST (default
# vps-primary).
# Both sides are evaluated as `path:` flakes from a clean export, so neither carries a git
# revision and the closure diff shows content only. Design: docs/tendcf-consent.md.
set -euo pipefail

: "${HEAD_SHA:?}" "${WORK:?}"
HOST="${HOST:-vps-primary}"
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

flake() { printf 'path:%s/%s/nixos' "$WORK" "$1"; }

do_export() {
  rm -rf "${WORK:?}/head"
  mkdir -p "$WORK/head"
  git archive "$HEAD_SHA" nixos | tar -x -C "$WORK/head"
  if [ "${1:-both}" = both ]; then
    : "${BASE_SHA:?}"
    rm -rf "${WORK:?}/base"
    mkdir -p "$WORK/base"
    git archive "$BASE_SHA" nixos | tar -x -C "$WORK/base"
  fi
}

do_summary() {
  : "${BASE_SHA:?}"
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

  # Each eval is guarded so both checks always report; an eval error is a FAIL (fail closed).
  # Hard check 2: the declared option set is exactly {enable, execd.enable, package}.
  want='{"execd":["enable"],"top":["enable","execd","package"]}'
  if nix eval --json "$(flake head)#nixosConfigurations.$HOST.options.services.cfengine-tendcf" \
    --apply 'o: { top = builtins.attrNames o; execd = builtins.attrNames o.execd; }' > "$WORK/check2.raw"; then
    got=$(jq -cS . "$WORK/check2.raw" || echo unparsable)
    if [ "$got" = "$want" ]; then
      echo "check 2 (declared option set): PASS $got" | tee -a "$out"
    else
      echo "check 2 (declared option set): FAIL got $got, want $want" | tee -a "$out"
      echo "::error::services.cfengine-tendcf declares options other than enable, execd.enable, package; the summary must cover a new option first"
      rc=1
    fi
  else
    echo "check 2 (declared option set): FAIL eval error" | tee -a "$out"
    echo "::error::could not evaluate the declared options of services.cfengine-tendcf"
    rc=1
  fi

  # Hard check 1: no cf-execd unit and nothing that runs cf-execd or cf-agent: system and user
  # service and timer fields, the rendered text of every unit, units shipped in systemd.packages,
  # activation scripts, boot.postBootCommands, tmpfiles rules, systemd-targeted environment.etc
  # entries and system cron jobs (check1.nix). The `scanned` counts must all be above zero, so a
  # scan that saw nothing cannot pass.
  if nix eval --json "$(flake head)#nixosConfigurations.$HOST.config" \
    --apply "$(cat "$HERE/check1.nix")" > "$WORK/check1.json"; then
    if jq -e '.execdUnitPresent == false and ([.hits, .rawHits, .packageHits, .scriptHits] | all(type == "array" and length == 0)) and ([.scanned[] | . > 0] | all) and (.scanned | length) == 5' \
      "$WORK/check1.json" > /dev/null; then
      echo "check 1 (no cf-execd/cf-agent unit): PASS" | tee -a "$out"
    else
      echo "check 1 (no cf-execd/cf-agent unit): FAIL $(jq -c . "$WORK/check1.json" || cat "$WORK/check1.json")" | tee -a "$out"
      echo "::error::the $HOST configuration runs, or cannot be proven free of, cf-execd/cf-agent"
      rc=1
    fi
  else
    echo "check 1 (no cf-execd/cf-agent unit): FAIL eval error" | tee -a "$out"
    echo "::error::could not evaluate the units, scripts and cron jobs of $HOST"
    rc=1
  fi
  return "$rc"
}

do_effect() {
  : "${BASE_SHA:?}"
  local attr="nixosConfigurations.$HOST.config.system.build.toplevel" base head
  base=$(nix build --print-out-paths --no-link --print-build-logs "$(flake base)#$attr")
  head=$(nix build --print-out-paths --no-link --print-build-logs "$(flake head)#$attr")
  echo "base toplevel $base"
  echo "head toplevel $head"
  nix store diff-closures "$base" "$head" > "$WORK/effect.txt"
  cat "$WORK/effect.txt"
}

case "${1:-}" in
  export) do_export both ;;
  export-head) do_export head ;;
  summary) do_summary ;;
  checks) do_checks ;;
  effect) do_effect ;;
  *) echo "usage: run.sh export|export-head|summary|checks|effect" >&2; exit 2 ;;
esac
