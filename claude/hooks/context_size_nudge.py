#!/usr/bin/env python3
"""context_size_nudge.py — early, escalating context-size prompts.

Registered under UserPromptSubmit. Reads Claude Code hook JSON on stdin, finds
the session's current context size in its transcript, and when it crosses a
tier that hasn't fired yet, prints a note (Claude Code surfaces
UserPromptSubmit stdout to the model as a system-reminder) telling the agent
what to do and what to recommend to the operator.

History:
- 2026-08-03: built after a session grew to 670k+ tokens unnoticed.
- 2026-08-23: reworded to "never suggest a wrap-up" (continuous operation).
- 2026-10-05: fail-fast tail read + 2 s internal deadline (load 223 killed it).
- 2026-10-08 (operator ruling, supersedes 2026-08-23): prompt earlier and
  harder, and DO recommend /compact, or /handoff then /new. The old single
  150k nudge fired too late. Separable work goes to /bigteam by default so it
  never lands in this context. memory/feedback_context_prompts_early.md.
- 2026-10-10: stop the compaction loop. Measured over 85 compactions in two
  days: a /compact took context from ~187k to ~104k (not the ~33k Claude Code
  reports as postTokens: tool listings, project context and re-attached files
  come back), so the old 150k / +70k tiers re-fired after ~40 requests, and
  sessions compacted every ~25 min (one 24 times in a day). Each compaction
  re-writes ~70k tokens at the 1-hour cache's 2x rate plus the summary, ~150-
  180k base-input-equivalent; with cache reads at 0.025x (Fable 5.1) / 0.05x
  (Opus/Sonnet 5.5) that pays back only after ~45-85 requests, so most were a
  net loss. Growth now counts from the floor after the latest compaction, the
  compact tier is +200k (or 400k total), and the early tier no longer
  recommends /compact. memory/feedback_self_compact.md.

Measure: input + cache_creation + cache_read tokens of the newest usage block,
i.e. the real context size (cache_read alone reads 0 after a cache miss).
Tiers count GROWTH since the floor: the first usage block of the session, or of
the conversation after its latest compaction (a compact_boundary record, or a
drop below SHRINK_RATIO of the last size seen). Baselines differ a lot: a
session started in ~ carries ~90k before any work, and a compacted one ~100k.
An absolute backstop still asks at ASK_TOTAL.

Levels: 1 = early (delegate from now on; no compaction yet);
2+ = compact (self-slash in herdr/Orca) or ask the operator at the next natural
boundary, again every REPEAT_EVERY of further growth. A compaction resets the
floor and the level, so the tiers fire again only after the same growth.

MUST always exit 0 -- never fail or delay a prompt. Python 3 stdlib only.
Fail-fast: reads only a head window (baseline, once per session) and a tail
window (newest usage), never waits on the Hermes ping (detached Popen), and
an alarm at DEADLINE_SECONDS exits 0 with no output.
"""
# Every failure is swallowed on purpose: a hook error must never block a prompt.
# ruff: noqa: BLE001, S110
import json
import os
import re
import signal
import sys
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "state" / "context-nudges.json"

# Compaction is not free (see History, 2026-10-10): only compact once the
# context has grown enough above the post-compaction floor to pay it back.
EARLY_GROWTH = 40_000   # level 1: start delegating
ASK_GROWTH = 200_000    # level 2: compact / ask the operator
ASK_TOTAL = 400_000     # level 2 regardless of floor
REPEAT_EVERY = 100_000  # level 3, 4, ...: again per this much more
PAGE_GROWTH = 300_000   # Hermes ping (once per climb), whichever comes first
PAGE_TOTAL = 500_000
SHRINK_RATIO = 0.75     # a size below this share of the last one = compacted
COMPACTED = "compacted"  # _last_context_tokens: boundary newer than any usage
# Unescaped quotes only: the same text inside a tool result is JSON-escaped.
_BOUNDARY = re.compile(rb'"subtype":\s*"compact_boundary"')
_SIDECHAIN = re.compile(rb'"isSidechain":\s*true')

PING_BIN = Path.home() / ".local" / "bin" / "hermes-ping"

# Internal deadline: past this the hook exits 0 silently (see module docstring).
DEADLINE_SECONDS = 2

# Tail-read windows, smallest first. Newest usage block is almost always in the
# first window; the last one matches the original 2 MB scan.
_TAIL_WINDOWS = (128 * 1024, 2 * 1024 * 1024)
_HEAD_WINDOW = 512 * 1024


def _on_deadline(signum, frame):
    # os._exit: no unwinding, no buffered partial output, no chance of a hang.
    os._exit(0)


def _usage_from_line(line):
    """Context size (input + cache creation + cache read) from one transcript
    line, or None. Sub-agent (sidechain) records are skipped."""
    if b"cache_read_input_tokens" not in line:
        return None  # cheap reject: skips json.loads for most lines
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict) or obj.get("isSidechain"):
        return None
    message = obj.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    parts = [usage.get(k) for k in
             ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    if not any(isinstance(p, int) for p in parts):
        return None
    return sum(p for p in parts if isinstance(p, int))


def _last_context_tokens(transcript_path):
    """Best-effort: the newest usage block's context size.

    Reads a small window off the end of the file and scans it newest line
    first, returning at the first hit; only widens the window (up to 2 MB)
    when the small one had none. A huge transcript is never read forward."""
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
                    if _BOUNDARY.search(line) and not _SIDECHAIN.search(line):
                        return COMPACTED  # no request since the compaction yet
                    value = _usage_from_line(line)
                    if value is not None:
                        return value
                if chunk_size >= size:
                    break
    except Exception:
        return None
    return None


def _first_context_tokens(transcript_path):
    """The session's first usage block (its starting context), or None."""
    try:
        with Path(transcript_path).open("rb") as f:
            data = f.read(_HEAD_WINDOW)
    except Exception:
        return None
    for line in data.split(b"\n"):
        value = _usage_from_line(line)
        if value is not None:
            return value
    return None


def _level(total, growth):
    """0 = quiet, 1 = early, 2+ = ask (one more per REPEAT_EVERY)."""
    steps = []
    if growth >= ASK_GROWTH:
        steps.append((growth - ASK_GROWTH) // REPEAT_EVERY)
    if total >= ASK_TOTAL:
        steps.append((total - ASK_TOTAL) // REPEAT_EVERY)
    if steps:
        return 2 + max(steps)
    return 1 if growth >= EARLY_GROWTH else 0


_COST_NOTE = (
    "A compaction is not free: it re-writes ~70k tokens at the 1-hour cache's "
    "2x rate plus the summary and leaves ~100k behind, so it pays back only "
    "after dozens of further requests on the same work."
)


def _early_message(total, growth):
    return (
        f"Context check: {total:,} tokens in context (+{growth:,} since this "
        "session started or last compacted). From now on, send discrete, "
        "separable work through /bigteam (Agent sub-agents for small lookups) "
        "so its tokens stay out of this session, and don't read large files or "
        "logs inline. Do not compact yet: cached context is cheap to re-read. "
        + _COST_NOTE
    )


def _ask_message(total, growth, repeat):
    lead = "Context is still growing" if repeat else "Context is large"
    if os.environ.get("HERDR_PANE_ID") or os.environ.get("ORCA_TERMINAL_HANDLE"):
        # A herdr pane or Orca terminal can queue its own /compact (standing
        # operator ruling 2026-10-09, memory/feedback_self_compact.md).
        return (
            f"{lead}: {total:,} tokens (+{growth:,} since the session started "
            "or last compacted). If you are continuing the same work, then at "
            "the next natural boundary (a task done, never mid-edit or with a "
            "sub-agent result unread) compact yourself without asking: save "
            "what the next turn needs, run ~/src/djbclark-ade/bin/self-slash "
            "\"/compact <focus>\" ONCE and end the turn. If the next task is a "
            "different topic, ask the operator for /handoff then /new instead "
            "(nothing to summarize). If self-slash refuses, ask for /compact. "
            + _COST_NOTE
        )
    return (
        f"{lead}: {total:,} tokens (+{growth:,} since the session started or "
        "last compacted). At the next natural boundary (before starting the "
        "next task, never mid-edit), ask the operator with AskUserQuestion: "
        "1) /compact (Recommended when continuing the same work); 2) /handoff "
        "then /new (topic change, or the conversation itself is the only "
        "state); 3) Continue here and send the rest to /bigteam. Until "
        "answered, start no new heavy work inline: delegate it. Exception: an "
        "unattended session with no operator present keeps going by "
        "delegating. " + _COST_NOTE
    )


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state):
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE_PATH)
    except Exception:
        pass


def _send_ping(message, cwd):
    """Fire and forget: the ping must never hold the prompt."""
    try:
        import subprocess
        subprocess.Popen(
            [str(PING_BIN), message],
            cwd=cwd if cwd and os.path.isdir(cwd) else None,
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
    if not isinstance(data, dict):
        return

    session_id = data.get("session_id") or "unknown"
    transcript_path = data.get("transcript_path") or ""
    if not transcript_path:
        return

    total = _last_context_tokens(transcript_path)
    if total is None:
        return

    state = _load_state()
    session_state = state.get(session_id)
    if not isinstance(session_state, dict):
        session_state = {}

    if total == COMPACTED:
        # Compacted, no request since: the next measured size is the new floor.
        session_state.update(baseline=None, level=0, paged=False, last=None)
        state[session_id] = session_state
        _save_state(state)
        return

    baseline = session_state.get("baseline")
    last = session_state.get("last")
    if isinstance(last, int) and total < last * SHRINK_RATIO:
        baseline = total  # compacted between two prompts: new floor
        session_state["level"] = 0
    if not isinstance(baseline, int):
        if "level" in session_state:
            baseline = total  # first size after a compaction
        else:
            baseline = _first_context_tokens(transcript_path) or total
    session_state["baseline"] = baseline
    session_state["last"] = total
    growth = max(0, total - baseline)

    level = _level(total, growth)
    fired = session_state.get("level", 0)
    if not isinstance(fired, int):
        fired = 0

    if level > fired:
        if level == 1:
            print(_early_message(total, growth), flush=True)
        else:
            print(_ask_message(total, growth, repeat=fired >= 2), flush=True)
    session_state["level"] = level

    if growth >= PAGE_GROWTH or total >= PAGE_TOTAL:
        if not session_state.get("paged"):
            session_state["paged"] = True
            repo = os.path.basename((data.get("cwd") or "").rstrip("/")) or "claude"
            _send_ping(
                f"{repo}: Claude Code context at ~{total // 1000}k "
                f"(+{growth // 1000}k since start or last compact); agent will ask you to "
                "/compact, or /handoff then /new, at its next boundary.",
                data.get("cwd"),
            )
    elif level < 2:
        session_state["paged"] = False  # compacted: page again on regrowth

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
