# load-governor: dynamic, starvation-proof throttling of builds and tests

`bin/load-governor` (Python 3 standard library only) watches the machine and, only while
it is overloaded, moves the heaviest build/test processes of the current user to
background QoS with `taskpolicy -b -p PID`. It puts each one back with `taskpolicy -B -p
PID`, always after a fixed cap and when the machine is calm again, so nothing starves.

Why it exists: on 2026-10-04 parallel agents' `swift-test`, `vitest`, `pytest` and
Gradle runs pushed an 8-core Mac (4P+4E) to load average 300-400 and 50% system time
(`memory/project_machine_load_diagnosis_2026-10-04.md`). A static `taskpolicy -b` on the
builds fixed the contention but ran the throttled process at about 0.02 of a core
against 0.52 for a normal one, for as long as it lasted, and starved other sessions'
tests for an hour. The throttle needs to be dynamic.

## Quick use

```
bin/load-governor --once                 # evaluate one sample, dry-run, change nothing
bin/load-governor -v                     # dry-run loop, decisions printed to stderr
bin/load-governor --apply                # run the loop and really throttle
bin/load-governor --status               # what the state file says is throttled
bin/load-governor --undo-all             # taskpolicy -B -p every pid ever recorded
bin/load-governor --print-config         # effective config as commented TOML
```

Default is **dry-run**: it logs `DRYRUN would run: taskpolicy -b -p PID` and runs nothing.
Everything is logged to `~/.local/state/load-governor/governor.log` (rotated at 5 MB) with
the reason for each decision. State is `~/.local/state/load-governor/state.json`.

Config is optional: `~/.config/load-governor/config.toml` (or `--config PATH`), any subset
of the keys that `--print-config` prints, each with a one-line explanation. Unknown keys
are an error. Python older than 3.11 has no `tomllib` and reads JSON instead.

## What it does, per sample (default every 5 s)

1. **Signals.** CPU idle% and system-time share from `host_statistics(HOST_CPU_LOAD_INFO)`
   via `ctypes` (no process is spawned; `top -l` is the fallback), 1-minute load average
   divided by cores, and, from one `ps -axww` snapshot, the recent CPU of every process
   (difference of cumulative CPU time over the snapshot interval).
2. **Overloaded sample:** idle < 15% **and** (load/core >= 2.0 **or** system time >= 35%).
   **Calm sample:** idle > 35%. Anything else is neutral and resets both runs.
3. **Hysteresis.** Engage after 3 consecutive overloaded samples; release (restore
   everything at once) after 6 consecutive calm samples. Release uses idle only: the
   1-minute load average lags by a minute and would hold the throttle on long after
   the machine had recovered.
4. **Graduated.** When engaged, throttle the heaviest K eligible processes by recent CPU.
   K starts at 2 and goes up by one every 3 samples while still engaged, up to 6. The
   rest are left alone.
5. **Starvation cap.** A pid throttled continuously for 90 s is released (`-B`) and left
   alone for a 45 s grace window; after that it is eligible again. The freed slot goes to
   the next heaviest process, so the throttle rotates instead of parking on one victim.
   Worst case a pid is throttled about 2/3 of the time and always makes progress.
6. **Inheritance.** `taskpolicy -b` is inherited by children spawned afterwards, and
   `-B` on the parent does not undo it for them. So allow-listed descendants that
   started after their ancestor was throttled are tracked too (log `INHERIT`), released
   by the same cap, and released together with their ancestor. Without this, a
   `swift-test` child could stay background forever.

## Scope: what may and may never be touched

A process is eligible only if all hold: owned by the current user; not pid 1, not the
governor, not a descendant of the governor; not a zombie; at least 5 s old; used at
least 10% of a core since the last sample; its command line matches the **allow-list**
(swift-frontend/-build/-test, xctest, xcodebuild, vitest, jest, pytest, `-m pytest`,
go test/build and the Go toolchain, Gradle and Kotlin daemons/workers, cargo/rustc,
make/ninja/cmake, clang/gcc/ld, tsc/eslint/prettier/esbuild/webpack..., basedpyright/
mypy/ruff/pylint/flake8/black...). `ruff server` is excluded because it is an editor
language server.

The **deny-list always wins** over the allow-list. It matches *identity names* (the basename
of argv0, plus the first non-flag argument when argv0 is an interpreter such as node or
python, so `node .../codex.js exec pytest` is `node` + `codex.js`) with `fullmatch`, so a
test file called `test_claude.py` is not denied but `claude` is. Denied by name: WindowServer,
Finder, Dock, launchd, kernel_task, system daemons, every agent TUI (claude, codex,
copilot, cursor-agent, opencode, hermes, muse, agy, zcode, grok), Orca, Ghostty,
CodexBar, OpenUsage, the governor itself, shells, tmux, ssh, terminals, browsers. Denied by
command line: any `.app/Contents/MacOS/` executable (a GUI app is interactive) **except**
framework Python, whose real binary is `Python.app/Contents/MacOS/Python` and which is how
`python -m pytest` shows up in `ps` under Homebrew (found during the live check: without
the exception, every Homebrew-Python test run was invisible).

For a one-off pattern use `--allow-extra REGEX`; `--allow-only REGEX` *replaces* the
allow-list (deny-list still applies) and is what the tests and the live check use.

## Safety

1. Dry-run unless `--apply`.
2. Before every `-b` and `-B` the pid is re-checked with `ps -o lstart=,command= -p PID`
   against the start time recorded when it was seen. A different start time means pid
   reuse: it is logged (`REUSE` / `SKIP`) and **not touched**.
3. State (`state.json`) is rewritten atomically on each change: currently tracked pids and a
   bounded history (`ever_throttled`, 500 entries) of every pid it throttled, with start
   times. `--undo-all` restores each one whose pid and start time still match and
   skips the rest, then empties the file.
4. SIGTERM, SIGINT and normal exit restore everything. At startup in `--apply` mode it
   first runs the same restore for anything a crashed predecessor left behind.
5. One governor at a time (`flock` on `governor.lock`).
6. A failed `taskpolicy` call backs that pid off for 30 s instead of retrying every tick.

`--once --apply` is the exception to (4): it acts once and exits, **leaving the throttle
in place with no cap enforcement**, and prints a note to run `--undo-all`.

## Design notes and deviations from the first sketch

1. **Signals via `host_statistics`, not `top`.** The machine was spawning ~21k process
   events a second; the governor should not add to that. `top -l 2` is kept as fallback.
2. **Overload needs idle low *and* contention evidence.** idle < 15% alone also describes
   a healthy fully-used machine (eight cores each doing real work, load 8). Load/core >= 2
   or high system time says the work is *contending*, which is what hurt the UI.
3. **Time-stamping a `ps` snapshot at its midpoint.** Under load `ps` itself takes
   seconds; stamping the start or end skews every CPU rate.
4. **Inheritance tracking** (above) is new: it is a hole in the plain
   "throttle with -b, restore with -B" scheme that only shows up with real process trees.
5. **Efficiency-core placement is only available through `-b`.** macOS has no per-pid
   utility clamp, so "E-cores but still fair" cannot be had for an already-running
   process. The governor approximates it in time rather than in QoS: background while
   overloaded (E-cores, lowest priority), normal during the grace window. For new commands
   `bin/bg` (`-c utility`) remains the right thing. `bin/verify-ecores.sh` (needs `sudo`)
   measures which clusters none/utility/background actually land on.
6. **Release is all-at-once** on calm rather than one pid per calm sample. Simple, and
   the 6-sample calm requirement already damps it.

## Tests

```
python3 -m unittest tests/test_load_governor.py -v
```

Stdlib `unittest` (pytest is not installed here, and also runs these). A fake machine
(clock, process table, CPU counters, load, and a `taskpolicy` that records calls and
tracks which pids are "background") covers: engage/release hysteresis and the run-reset
rules, wraparound of 32-bit CPU counters, heaviest-K selection and escalation to max_k,
cap then grace then re-throttle, rotation to the next process, the worst-case bound on
continuous throttling, deny-list precedence over allow, governor-and-children immunity,
pid 1, other users and zombies, pid reuse (between ticks and between ps and the call),
dry-run issuing no calls and writing no state, taskpolicy failure back-off, inherited
children, state file contents, `--undo-all` (matching, reused, exited), shutdown restore,
`ps`/CPU-time parsing and config round-trip.

## Installing the launchd agent (not done; do it when you decide to)

The template is `docs/com.djbclark.load-governor.plist.example`. It runs
`/opt/homebrew/bin/python3 ~/ops/site-private/bin/load-governor --apply` with `RunAtLoad`,
`KeepAlive`, `Nice 5` and `LowPriorityIO`, and deliberately **not** `ProcessType
Background` (that would starve the governor exactly when it is needed).

```
# 1. watch it dry first for a day:  bin/load-governor -v   (or the plist without --apply)
cp docs/com.djbclark.load-governor.plist.example ~/Library/LaunchAgents/com.djbclark.load-governor.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.djbclark.load-governor.plist
# remove:
launchctl bootout gui/$(id -u)/com.djbclark.load-governor; bin/load-governor --undo-all
```

The log directory must exist before launchd starts it (`mkdir -p ~/.local/state/load-governor`).

## Known limits

1. The governor is itself a process on the overloaded machine. Under load average
   100+ its `ps` and `taskpolicy` calls took seconds, so reaction time stretches from
   the nominal 5 s to tens of seconds; the cap still bounds the damage.
2. `-b` throttles I/O and CPU priority as well as core placement, and children
   spawned while it is on inherit it. A short-lived child that is never sampled
   (< 5 s, or between ticks) still inherits it and is only caught if it lives to be tracked.
3. It only sees what `ps` calls a command line. A build launched through a wrapper that
   rewrites its argv will not match.
4. Per-process CPU is a sampled rate over one interval, so a bursty process can look
   light at the moment it is chosen.
5. No query API exists for a process's current QoS, so the governor cannot tell that a
   pid it did not throttle is already background (for example from the earlier manual
   `taskpolicy -b -p` sweep, or `bgb`). It never un-throttles what it did not record.
6. Idle > 35% means calm; a workload that keeps the machine below that even when
   throttled will keep it engaged, rotating by the cap and grace windows.
7. Replacing static throttling in `home-agents.md` (the "heavy builds run at background
   QoS" rule) is left to the operator; this tool does not edit it.
