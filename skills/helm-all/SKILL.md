---
name: helm-all
description: >-
  helm with ended sessions included: one queue of every open item in the fleet —
  running sessions of every TUI that wait on the operator, plus ended sessions
  that still hold open work (a handoff whose next steps nobody picked up, a last
  reply that asked a question) — ordered so the fleet gets the most unattended
  work out of each answer. Use when the operator types /helm-all, says "what is
  open anywhere", "including stopped sessions", "what did we leave hanging", or
  wants to restart handed-off work from one window.
---

# helm-all — every open item, including the sessions that stopped

Follow the `helm` skill exactly (same script, same prompt tool, same rules:
relay verbatim, never choose for him, report against the artifact). The one
difference is the collector call and two extra item kinds.

```bash
H="python3 -I $HOME/ops/site-private/skills/helm/helm.py"
L="python3 -I $HOME/ops/site-private/skills/session-finder/launch.py"
$H scan --ended [--days 14]      # open items, running + ended, ranked by minutes unlocked
$H wait --auto-audit             # then the ordinary helm wait; ended items do not change on their own
```

## 1. Start

1. `$H scan --ended`. Show the queue as a short numbered list (project, kind, where
   or "ended", `~N min unlocked`). Ended items appear only when they hold open work
   (`helm.py` → `fleet.ended_open`): a `handoff` whose Next steps are non-empty and
   whose repo has no live session, or an `ended-question`.
2. Walk the open items in the order given (the answer that unlocks the most
   unattended work first; one session's items stay together).
3. Then `$H wait --auto-audit` as in `helm` section 3; rerun `scan --ended` when he
   asks what else is open, not on a timer.

## 2. The two extra kinds

1. **`handoff`** — a chain with next steps and nobody live in its directory. Offer
   exactly: **Start a /baton session now** (first; say the agent and model you
   would pick per session-finder's vendor rules), **Skip** (`$H skip <id>`), or
   **Leave it**. On start: `$L --baton --cwd <dir> --agent <A> --model <M> --name
   "<project>: <active work>" -p "<the next steps, verbatim from the item, plus
   anything he adds>"`. Run `fleet.py conflicts --cwd <dir>` first; launch.py
   refuses when another session is working there — relay that instead.
2. **`ended-question`** — a session that stopped on a question nobody answered.
   Relay the question as the prompt text with options **Answer in a fresh
   session** (`$L --agent claude --cwd <dir> --model <M> -p "<the question> —
   operator's answer: <his text>; continue from there"`), **Resume it** (only when
   the item's transcript size is under 2 MB, see session-finder 3d; give the
   `claude --resume` command for him to run in the pane he picks), **Skip**.

Started sessions come back through the queue as `done` or `reply` items (helm
section 2.5), so the walk continues without you watching them.

## 3. Keep it cheap

Ended items are read from logs and transcripts only; nothing is re-opened until
he says so. Do not summarise a handoff beyond its Active-work line and next steps
as printed. A helm-all session relays and does not judge: a cheaper model is enough.
