#!/usr/bin/env python3
"""Site-side Herdr agent-state prototype for coding-agent TUIs Herdr cannot
identify by process name yet (goose, aider — see site-djbclark#12).

Herdr has no built-in "kind" for goose/aider (`herdr agent start --kind`
does not list them) and local `~/.config/herdr/agent-detection/*.toml`
overrides only re-tune screen-detection rules for agents Herdr already
recognizes by process name — they cannot invent a new agent id. Until an
upstream Herdr release adds native support, this script self-reports pane
lifecycle state over the documented `herdr pane report-agent` /
`release-agent` API instead (see docs/reference/herdr-workstation.md).

Usage:
    herdr_agent_wrapper.py <agent-label> -- <real-command> [args...]
    herdr_agent_wrapper.py --notify-idle <agent-label>

The second form is used as an aider `--notifications-command` target; it
reports one idle transition and exits, it does not wrap a process.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time

POLL_INTERVAL_SECONDS = float(os.environ.get("HERDR_AGENT_POLL_INTERVAL", "2.0"))
STABLE_POLLS_BEFORE_IDLE = 2
READ_LINES = 40

# Best-effort confirm/permission-prompt detection, tuned against the actual
# prompts observed live from both tools (2026-07-29 empirical pass — see the
# handoff doc), not guessed from docs. Deliberately generic: catches common
# yes/no and clack-style (goose) confirmation UIs. False negatives (missing a
# novel prompt phrasing) are expected and safe — the pane just stays
# "working" a beat longer than ideal, it never gets stuck falsely blocked.
BLOCKED_PATTERNS = (
    r"\(y\)es\s*/\s*\(n\)o",  # aider: "(Y)es/(N)o", "(Y)es/(N)o/(D)on't ask again"
    r"[●○]\s*(yes|no)\b",  # goose clack-style toggle prompts
    r"\by/n\b",
    r"\ballow\b.{0,40}\?",
)


def _herdr_bin() -> str | None:
    return shutil.which("herdr")


def _in_herdr_pane() -> tuple[str, str] | None:
    """Return (pane_id, herdr_bin) if running inside a Herdr pane, else None."""
    if os.environ.get("HERDR_ENV") != "1":
        return None
    pane_id = os.environ.get("HERDR_PANE_ID")
    socket_path = os.environ.get("HERDR_SOCKET_PATH")
    herdr_bin = _herdr_bin()
    if not pane_id or not socket_path or not herdr_bin:
        return None
    return pane_id, herdr_bin


def _report_agent(
    herdr_bin: str,
    pane_id: str,
    source: str,
    agent: str,
    state: str,
    message: str | None = None,
) -> None:
    # NOTE: `herdr pane report-agent` requires PANE_ID as the *first* argument,
    # before any --flags — passing it last (as the --help usage line shows)
    # is rejected with "unknown option: <value>" on herdr 0.7.5. Confirmed
    # live 2026-07-29; keep pane_id first here regardless of what --help says.
    cmd = [
        herdr_bin,
        "pane",
        "report-agent",
        pane_id,
        "--source",
        source,
        "--agent",
        agent,
        "--state",
        state,
        "--seq",
        str(time.time_ns()),
    ]
    if message:
        cmd += ["--message", message[:200]]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _release_agent(herdr_bin: str, pane_id: str, source: str, agent: str) -> None:
    # --seq must be freshly monotonic: a release without a seq higher than the
    # last report-agent call's seq is silently ignored (last-write-by-seq-wins),
    # leaving a stale label on a pane whose agent already exited. Confirmed
    # live 2026-07-29 — omitting --seq here reproduced exactly that bug.
    cmd = [
        herdr_bin,
        "pane",
        "release-agent",
        pane_id,
        "--source",
        source,
        "--agent",
        agent,
        "--seq",
        str(time.time_ns()),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _read_pane(herdr_bin: str, pane_id: str) -> str:
    cmd = [herdr_bin, "pane", "read", pane_id, "--source", "recent", "--lines", str(READ_LINES)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=3, text=True, check=False)
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _looks_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in BLOCKED_PATTERNS)


def classify_next_state(
    snapshot: str,
    last_snapshot: str | None,
    stable_polls: int,
    last_reported_state: str,
) -> tuple[str, int]:
    """Pure state-transition step for one poll. Returns (state, new_stable_polls).

    Content-quiescence heuristic: unchanged screen content for
    STABLE_POLLS_BEFORE_IDLE consecutive polls means idle; any change means
    working; a confirm/permission-prompt pattern always wins as blocked.
    Generic on purpose — no goose/aider-specific screen regions, unlike
    Herdr's own manifest rules for agents it natively detects.
    """
    if _looks_blocked(snapshot):
        return "blocked", 0
    if snapshot == last_snapshot:
        stable_polls += 1
        state = "idle" if stable_polls >= STABLE_POLLS_BEFORE_IDLE else last_reported_state
        return state, stable_polls
    return "working", 0


def _monitor(
    herdr_bin: str,
    pane_id: str,
    source: str,
    agent: str,
    stop_event: threading.Event,
) -> None:
    last_snapshot = None
    last_reported_state = "working"
    stable_polls = 0
    while not stop_event.wait(POLL_INTERVAL_SECONDS):
        snapshot = _read_pane(herdr_bin, pane_id)
        if not snapshot:
            continue
        state, stable_polls = classify_next_state(
            snapshot, last_snapshot, stable_polls, last_reported_state
        )
        last_snapshot = snapshot
        if state != last_reported_state:
            _report_agent(herdr_bin, pane_id, source, agent, state)
            last_reported_state = state


def run_notify_idle(agent: str) -> int:
    """Entry point for aider's `--notifications-command` hook: one idle report."""
    ctx = _in_herdr_pane()
    if ctx is None:
        return 0
    pane_id, herdr_bin = ctx
    _report_agent(herdr_bin, pane_id, f"site:{agent}", agent, "idle")
    return 0


def run_wrapped(agent: str, real_cmd: list[str]) -> int:
    ctx = _in_herdr_pane()
    if ctx is None or not real_cmd:
        # Not in a Herdr pane (or nothing to run) — transparent passthrough,
        # never block the agent on Herdr being unavailable.
        if not real_cmd:
            print(f"herdr_agent_wrapper: no command given for {agent}", file=sys.stderr)
            return 1
        os.execvp(real_cmd[0], real_cmd)  # noqa: S606 - intentional exec passthrough
        return 1  # unreachable if exec succeeds

    pane_id, herdr_bin = ctx
    source = f"site:{agent}"
    _report_agent(herdr_bin, pane_id, source, agent, "working")

    stop_event = threading.Event()
    monitor_thread = threading.Thread(
        target=_monitor,
        args=(herdr_bin, pane_id, source, agent, stop_event),
        daemon=True,
    )
    monitor_thread.start()

    child = subprocess.Popen(real_cmd)  # noqa: S603 - real_cmd is the intended agent binary
    try:
        # Some agents (aider: "^C again to exit") swallow the first SIGINT
        # for their own confirm-to-quit UX and keep running. Ctrl+C reaches
        # both this wrapper and the child (same foreground process group),
        # so re-wait after each KeyboardInterrupt instead of exiting early —
        # otherwise release-agent fires while the wrapped agent is still
        # alive in the pane. Confirmed live with aider, 2026-07-29.
        while True:
            try:
                returncode = child.wait()
                break
            except KeyboardInterrupt:
                continue
    finally:
        stop_event.set()
        # Join before releasing: otherwise a report already in flight from the
        # monitor's last poll can land *after* release-agent and resurrect a
        # stale label for a pane whose agent has already exited (observed
        # live, 2026-07-29 — see the handoff doc).
        monitor_thread.join(timeout=POLL_INTERVAL_SECONDS + 3)
        _release_agent(herdr_bin, pane_id, source, agent)
    return returncode


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--notify-idle":
        return run_notify_idle(argv[1])

    if "--" not in argv:
        print("usage: herdr_agent_wrapper.py <agent-label> -- <real-command> [args...]", file=sys.stderr)
        return 2
    split = argv.index("--")
    agent_args = argv[:split]
    real_cmd = argv[split + 1 :]
    if len(agent_args) != 1:
        print("usage: herdr_agent_wrapper.py <agent-label> -- <real-command> [args...]", file=sys.stderr)
        return 2
    return run_wrapped(agent_args[0], real_cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
