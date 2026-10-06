#!/usr/bin/env python3
"""context_size_nudge.py — proactive context-fullness nudge.

Registered under UserPromptSubmit. Reads Claude Code hook JSON on stdin,
extracts the current session's most recent cache_read_input_tokens from its
transcript, and if it crosses a threshold that hasn't already fired for this
session, prints a plain-text note (Claude Code surfaces UserPromptSubmit
stdout back to the model as a system-reminder) so the agent proactively
raises it with the user -- and past a higher threshold, also pings the user
directly via `hermes send`, since a busy session might not otherwise pause to
mention it.

Built 2026-08-03 after a real gap: a marathon session grew to 670k+ cached
tokens (already compacted once, then grown huge again) with nothing catching
it until the user asked directly. reference_token_self_check.md's guidance
("glance at context fullness... at natural checkpoints") existed only as
inert memory content with no enforcement -- this hook is the enforcement.

Reworded 2026-08-23 (operator ruling: the stop-work /handoff ritual is a
bug): nudges now direct the AGENT to externalize heavy work and keep state
durable while CONTINUING -- auto-compaction plus precompact_handoff.py
bridge context windows without stopping. The hermes ping at the hard
threshold is an FYI, not a call to action. Doctrine and rationale:
memory/feedback_continuous_operation_over_handoff.md.

MUST always exit 0 -- never fail or delay a prompt, no matter what.
Python 3 stdlib only, matching precompact_handoff.py's convention.

Fail-fast (2026-10-05): on 2026-10-05 ~21:00 the load average hit 223 on 8
cores and this hook was killed at its 10 s configured timeout, delaying every
prompt. It now (a) reads only the transcript's tail, newest line first, and
stops at the first usage block; (b) never waits on `hermes send` (detached
Popen); (c) arms a DEADLINE_SECONDS alarm that exits 0 with no output, so a
starved machine costs the prompt ~2 s at most. The settings.json timeout stays
as a backstop.
"""
import json
import os
import signal
import sys
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "state" / "context-nudges.json"

# Thresholds are cache_read_input_tokens (the whole-conversation cache Claude
# re-reads every turn) -- not a fraction of any specific model's context
# window, which varies (200k standard, up to 1M in long-context mode, as this
# session's own 670k+ reading demonstrates). The point isn't "about to hit a
# hard wall" -- per reference_token_self_check.md, a big context inflates
# burn rate well before any wall, so the nudge point is deliberately well
# below where a hard cutoff would bite.
SOFT_THRESHOLD = 150_000
HARD_THRESHOLD = 350_000
HERMES_TARGET = "telegram:838808636:22158"

# Internal deadline: past this the hook exits 0 silently (see module docstring).
DEADLINE_SECONDS = 2

# Tail-read windows, smallest first. Newest usage block is almost always in the
# first window; the last one matches the original 2 MB scan.
_TAIL_WINDOWS = (128 * 1024, 2 * 1024 * 1024)


def _on_deadline(signum, frame):
    # os._exit: no unwinding, no buffered partial output, no chance of a hang.
    os._exit(0)


def _usage_from_line(line):
    """cache_read_input_tokens from one transcript line, or None."""
    if b"cache_read_input_tokens" not in line:
        return None  # cheap reject: skips json.loads for most lines
    try:
        obj = json.loads(line)
    except Exception:
        return None
    message = obj.get("message") if isinstance(obj, dict) else None
    usage = message.get("usage") if isinstance(message, dict) else None
    if isinstance(usage, dict) and isinstance(usage.get("cache_read_input_tokens"), int):
        return usage["cache_read_input_tokens"]
    return None


def _last_cache_read_tokens(transcript_path):
    """Best-effort: the most recent usage block's cache_read_input_tokens.

    Reads a small window off the end of the file and scans it newest line
    first, returning at the first hit; only widens the window (up to 2 MB, the
    original limit) when the small one had none. A huge transcript is never
    read or parsed forward."""
    try:
        with Path(transcript_path).open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            tried = 0
            for window in _TAIL_WINDOWS:
                chunk_size = min(size, window)
                if chunk_size <= tried:
                    break
                f.seek(size - chunk_size)
                data = f.read(chunk_size)
                tried = chunk_size
                lines = data.split(b"\n")
                if chunk_size < size:
                    lines = lines[1:]  # first line may be cut mid-record
                for line in reversed(lines):
                    value = _usage_from_line(line)
                    if value is not None:
                        return value
                if chunk_size >= size:
                    break
    except Exception:
        return None
    return None


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state):
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state))
    except Exception:
        pass


def _send_hermes(message):
    """Fire and forget: the page must never hold the prompt."""
    try:
        import subprocess
        subprocess.Popen(
            ["hermes", "send", "-t", HERMES_TARGET, message],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return

    session_id = data.get("session_id") or "unknown"
    transcript_path = data.get("transcript_path") or ""
    if not transcript_path:
        return

    tokens = _last_cache_read_tokens(transcript_path)
    if tokens is None:
        return

    state = _load_state()
    session_state = state.get(session_id, {})

    if tokens >= HARD_THRESHOLD and not session_state.get("hard"):
        print(
            f"Context is very large ({tokens:,} cached tokens). Do NOT stop "
            "work or suggest a session restart: externalize remaining heavy "
            "work to subagents/background tasks, keep committing state to "
            "disk, and continue -- auto-compaction plus the PreCompact "
            "handoff hook bridge context windows automatically. If the "
            "operator is present, a deliberate /compact at a natural "
            "boundary preserves more than the automatic one. Mention the "
            "size once; do not turn it into a wrap-up ritual.",
            flush=True,
        )
        session_state["soft"] = True
        session_state["hard"] = True
        state[session_id] = session_state
        _save_state(state)
        _send_hermes(
            f"FYI: Claude Code session context is very large ({tokens:,} "
            "cached tokens). Agent instructed to externalize and continue; "
            "auto-compact + PreCompact handoff will bridge. No action needed."
        )
    elif tokens >= SOFT_THRESHOLD and not session_state.get("soft"):
        print(
            f"Context is getting large ({tokens:,} cached tokens). Keep "
            "working -- do not advise a wrap-up or fresh session. Tighten "
            "context hygiene instead: push heavy work into subagents or "
            "background workflows (their tokens stay out of this session), "
            "and checkpoint durable state (commits, memory, docs) as you "
            "go. Auto-compaction + the PreCompact handoff hook handle "
            "continuity.",
            flush=True,
        )
        session_state["soft"] = True
        state[session_id] = session_state
        _save_state(state)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGALRM, _on_deadline)
        signal.alarm(DEADLINE_SECONDS)
    except Exception:
        pass  # no SIGALRM (non-POSIX): run without the internal deadline
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
