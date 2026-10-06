#!/usr/bin/env bash
# verify-ecores.sh -- which cores does each QoS policy actually use?
#
#   sudo bash ~/ops/site-private/bin/verify-ecores.sh [LOOPS] [SECONDS]
#
# For each policy -- (a) none, (b) `taskpolicy -c utility`, (c) `taskpolicy -b` --
# it starts LOOPS busy loops (default 4), lets them settle, samples
#   powermetrics --samplers cpu_power,tasks -n 1 -i <SECONDS*1000>
# and prints the P-cluster versus E-cluster active residency and frequency, plus the
# CPU of exactly those loops (powermetrics per-process rows by pid, and a ps cputime
# delta as a cross-check). Read-only: it changes nothing but its own loops, and an EXIT
# trap kills them even on Ctrl-C. powermetrics needs root, hence sudo.
#
# Run it when the machine is otherwise quiet, or the other work lands in the same
# clusters and muddies the residency. Test hooks (no root, canned data):
#   POWERMETRICS=/path/to/fake  ALLOW_NONROOT=1
set -u
LOOPS="${1:-4}"
SECS="${2:-5}"
POWERMETRICS="${POWERMETRICS:-/usr/bin/powermetrics}"
TASKPOLICY=/usr/sbin/taskpolicy

if [ "$(id -u)" -ne 0 ] && [ -z "${ALLOW_NONROOT:-}" ]; then
  echo "powermetrics needs root: run  sudo bash $0 $*" >&2
  exit 2
fi

PIDS=()
cleanup() {
  if [ "${#PIDS[@]}" -gt 0 ]; then
    kill "${PIDS[@]}" 2>/dev/null
    wait "${PIDS[@]}" 2>/dev/null
  fi
  PIDS=()
}
trap cleanup EXIT
trap 'exit 130' INT TERM

start_loops() { # $@ = optional policy prefix
  PIDS=()
  local i
  for ((i = 0; i < LOOPS; i++)); do
    "$@" /usr/bin/perl -e 'while (1) { }' verify-ecores-loop &
    PIDS+=("$!")
  done
}

cputime_s() { # total cputime of PIDS in seconds
  ps -o time= -p "$(IFS=,; echo "${PIDS[*]}")" 2>/dev/null |
    awk '{n=split($1,a,":"); s=0; for(i=1;i<=n;i++) s=s*60+a[i]; t+=s} END{printf "%.2f", t}'
}

run_phase() { # $1 = label, rest = policy prefix
  local label="$1"; shift
  echo
  echo "=== $label ==="
  start_loops "$@"
  sleep 3 # let QoS settle and the scheduler place the threads
  local out c0 c1 w0 w1
  out="$(mktemp -t verify-ecores)"
  c0="$(cputime_s)"; w0="$(date +%s)"
  "$POWERMETRICS" --samplers cpu_power,tasks -n 1 -i "$((SECS * 1000))" >"$out" 2>&1
  c1="$(cputime_s)"; w1="$(date +%s)"
  echo "-- clusters (active residency / frequency):"
  grep -E 'Cluster (HW )?active (residency|frequency)|Cluster Power' "$out" | sed 's/^/   /'
  echo "-- per-CPU active residency:"
  grep -E '^CPU [0-9]+ (active residency|frequency)|^CPU [0-9]+ active residency' "$out" | sed 's/^/   /' | head -40
  echo "-- the ${LOOPS} test loops (powermetrics 'tasks' rows, by pid; CPU ms/s):"
  local p
  for p in "${PIDS[@]}"; do
    grep -E "^[^ ].*[[:space:]]${p}[[:space:]]" "$out" | head -1 | sed 's/^/   /'
  done
  awk -v c0="$c0" -v c1="$c1" -v w="$((w1 - w0))" -v n="$LOOPS" \
    'BEGIN { if (w > 0) printf "-- ps cputime cross-check: %.2f cores per loop (%.2fs over ~%ds)\n", (c1-c0)/w/n, c1-c0, w }'
  rm -f "$out"
  cleanup
}

echo "verify-ecores: $LOOPS busy loops per phase, ${SECS}s powermetrics window, $(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
echo "cores: $(sysctl -n hw.perflevel0.logicalcpu 2>/dev/null) P + $(sysctl -n hw.perflevel1.logicalcpu 2>/dev/null) E; load: $(sysctl -n vm.loadavg)"
run_phase "(a) no policy"
run_phase "(b) taskpolicy -c utility" "$TASKPOLICY" -c utility
run_phase "(c) taskpolicy -b (background)" "$TASKPOLICY" -b
echo
echo "How to read it: a cluster's 'HW active residency' is the share of time it had cores running."
echo "If (b) shows P-cluster residency like (a), utility QoS is NOT confined to E-cores;"
echo "if (c) shows the loops only on the E-cluster, background QoS is."
