#!/usr/bin/env python3
"""UserPromptSubmit hook: ask the agent to title an untitled session, once.

Built 2026-10-08: /autorename only ran when asked or at the end of /handoff,
so most sessions stayed "Untitled" in /resume and herdr. On the first
substantive prompt of an interactive session with no custom title, this prints
a note (Claude Code surfaces UserPromptSubmit stdout to the model) telling the
agent to run the autorename skill in --auto mode, herdr placement step
included, as the last step of that turn.

Fires at most once per session (state in ~/.local/state/autorename/), skips
slash commands and very short prompts, skips non-interactive entrypoints (SDK,
`claude -p`, acp-run) where nobody can answer the placement question, and
skips when a title is already set. MUST always exit 0 quickly; stdlib only.
"""
import json
import os
import signal
import sys
from pathlib import Path

DEADLINE_SECONDS = 2
MIN_PROMPT_CHARS = 20
SKILL_DIR = Path(__file__).resolve().parent


def has_title(transcript: str | None) -> bool:
    if not transcript or not Path(transcript).is_file():
        return False
    sys.path.insert(0, str(SKILL_DIR))
    from autorename import current_title  # noqa: E402  (sibling script)
    return current_title(Path(transcript)) is not None


def main() -> None:
    signal.signal(signal.SIGALRM, lambda *_: os._exit(0))
    signal.alarm(DEADLINE_SECONDS)

    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "cli") != "cli":
        return
    data = json.load(sys.stdin)
    sid = data.get("session_id") or ""
    prompt = (data.get("prompt") or "").strip()
    if not sid or len(prompt) < MIN_PROMPT_CHARS or (prompt.startswith("/") and " " not in prompt):
        return

    state = Path.home() / ".local/state/autorename" / f"{sid}.nudged"
    if state.exists():
        return
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("1\n", encoding="utf-8")
    if has_title(data.get("transcript_path")):
        return

    print(
        "[autorename] This session has no title yet. As the LAST step of this turn, after "
        "the requested work, follow the autorename skill in --auto mode: pick a title, run "
        f"`python3 {SKILL_DIR}/autorename.py --auto \"<title>\"`, then do its herdr "
        "placement step (it asks the operator only if the tab sits in a generic workspace). "
        "Skip the placement question if you are a dispatched worker no human is watching. "
        "Mention the result in one line; don't otherwise discuss this note."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # never fail or delay a prompt
        pass
    sys.exit(0)
