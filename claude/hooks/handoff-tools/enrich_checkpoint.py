#!/usr/bin/env python3
"""enrich_checkpoint.py — mine a compacting session's transcript into an
enriched checkpoint. Launched detached by precompact_handoff.py.
Best-effort: failures are logged (stderr -> enrich.log) and harmless.

Usage: enrich_checkpoint.py <sidecar.md> <transcript.jsonl>
Writes <sidecar-stem>-enriched.md next to the sidecar.
"""
import json
import sys
from pathlib import Path

import anyio
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions,
                              TextBlock, query)

MAX_CHARS = 150_000  # transcript tail cap fed to the model

PROMPT = """An AI coding session is being context-compacted. Below is \
the tail of its transcript. Extract, as terse markdown bullets under \
these exact headings, only what is actually present (omit empty \
headings). Preserve raw numbers, file paths, and command lines exactly.

## Goal
## Work completed
## Approaches tried (incl. failed, with why)
## Decisions (chosen and rejected)
## Evidence & measurements
## Operator feedback/preferences
## Next steps

Transcript tail:
"""


def transcript_text(path):
    pieces = []
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get("message") or {}
            role = msg.get("role") or obj.get("type") or "?"
            content = msg.get("content")
            if isinstance(content, str):
                pieces.append(f"[{role}] {content}")
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        pieces.append(f"[{role}] {b.get('text', '')}")
    except Exception:
        return ""
    return "\n".join(pieces)[-MAX_CHARS:]


async def amain(sidecar, transcript):
    text = transcript_text(transcript)
    if not text:
        return
    opts = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        max_turns=1,
        allowed_tools=[],
        system_prompt="You are a terse session archivist.",
    )
    out = []
    async for message in query(prompt=PROMPT + text, options=opts):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    out.append(block.text)
    if not out:
        return
    enriched = sidecar.with_name(sidecar.stem + "-enriched.md")
    tmp = enriched.with_suffix(".tmp")
    tmp.write_text(
        "# Enriched checkpoint (haiku, best-effort)\n\n"
        + "\n".join(out) + "\n")
    tmp.replace(enriched)


def main():
    if len(sys.argv) != 3:
        sys.exit(2)
    anyio.run(amain, Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()
