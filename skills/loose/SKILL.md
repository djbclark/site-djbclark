---
name: loose
description: >-
  Audit the current session for loose ends — unfinished work, unverified claims,
  leftover test artifacts, undocumented findings, unreported upstream bugs,
  deviations from the operator's own decisions — then step him through each one
  with /steps (one multiple-choice prompt at a time), and finally ask whether to
  /handoff or /quit. Use when the operator types /loose, asks "any loose ends?",
  "anything outstanding?", "did we finish everything?", or asks to be walked
  through what is left. Also use unprompted before a handoff or at the end of a
  long working session.
---

# loose — find what is unfinished, then make it decidable

Two halves, and the second is not optional. **Audit by verification, then prompt
him to choose.** A prose list of what you remember is the failure mode this skill
exists to replace.

## Rule 1 — verify, never recall

Your memory of the session is the *input* to the audit, not the audit. Every item
gets a command behind it before it reaches him. This matters more than it sounds:
in the session this skill came from, auditing by verification found a real gap
nobody had noticed (an always-loaded `AGENTS.md` pointer that never mentioned the
rule the whole session had established), confirmed two things that had only been
*assumed* true, and refuted one claim that had already been stated as fact.

Corollary: when a check contradicts something you told him earlier, **say so
plainly in the audit**. An audit that quietly preserves your earlier framing is
worthless.

## Rule 2 — the sweep

Work the list; each line is a command, not a memory.

1. **Repo state, every repo touched.** Dirty files, unpushed commits, detached
   heads: `git status --porcelain` and `git status -sb` per repo. Distinguish
   *yours* from another session's — in a shared checkout you cannot attribute by
   `git log --author`, so if you did not touch it, say "not mine" and leave it.
2. **Test and probe artifacts.** Everything you created to prove something:
   throwaway MCP servers, marker functions appended to source, backup files,
   scratch clones, index caches you deleted or built. Grep for your own probe
   names. A marker function left in a tracked file is the worst kind of leftover.
3. **Background work.** Tasks still running, agents idle with output you never
   collected. An agent that looks finished with nothing delivered means *not yet
   delivered* — re-task it to write a file; never reconstruct what it would have
   said.
4. **Claims you made but did not verify.** Scan your own replies for assertions
   stated flatly. Anything you inferred rather than observed either gets checked
   now or gets downgraded to "assumed" in the audit.
   A pass you read through a pipe (`cmd | tail`) is in this class: the exit
   status was the last stage's, not the command's. Re-run it to a file with
   `echo "rc=$?"`, or downgrade it.
5. **Findings that exist only in chat.** A measurement, a defect, a workaround,
   a decision and its reasoning — if it is not in a repo, a doc, or memory, it is
   gone at session end. Put it somewhere durable before reporting the loose end.
6. **Docs that reality has overtaken.** Did this session's work falsify a
   standing note, an always-loaded instruction, or a pointer? Check the files
   that *load every session* specifically — a rule nobody reads is not a rule.
7. **Upstream bugs found and not reported.** Any third-party defect you hit with
   a clean reproduction. **Search existing issues and PRs first** (open and
   closed, several terms) — the existing thread often explains the behaviour or
   even hands you the fix.
8. **Deviations from his decisions.** Anything you did that cut against a choice
   he had already made, even reversibly. Disclose it in the audit if you have not
   already; do not let it surface later.
9. **Deferred by him, not by you.** List these so they are not mistaken for
   oversights — and do not re-litigate them.
10. **Verified-closed items.** One line, so the same questions do not come back
    next time.

## Rule 3 — then step through them with `/steps`, do not prose

Once the sweep is reported, **invoke the `steps` skill automatically** on the
live decisions; don't wait for him to ask. That skill picks the prompt tool
(`AskUserQuestion` on Claude-class agents, `clarify` / Telegram buttons on
Hermes), asks one item per prompt with the recommended option first, and does
each small chosen action before asking the next. Hand it the audit's items in
order of consequence, each with the finding and the recommendation you already
worked out, so it doesn't redo the audit. Include a genuine "leave it as is"
option where that is a real choice, and spell out the consequence.

Prose is for the context he needs to choose *with* — the numbers, the risk, what
you found. Not for the choosing.

Categories 9 and 10 are **not** questions. Report them and move on.

## Rule 4 — close by asking: /handoff or /quit

Once `/steps` has finished (its summary table, and any queued work done), end
with one more prompt using the **same tool as `/steps`**, every time, even when
the audit found nothing:

1. **`/handoff`** — write a Tier 2 handoff so a later session can resume.
   Recommend it when anything is still open or deferred, or the session was long
   or produced context that is not already durable.
2. **`/quit`** — end the session. Recommend it when the audit closed everything
   and all work is committed and pushed.
3. **Keep working** — stay in the session; nothing else happens.

Put the recommended one first with `(Recommended)` and give the reason in its
description, e.g. "2 items deferred; a handoff keeps them findable".

Then act on the answer. For `/handoff`, invoke the `handoff` skill. You cannot run
`/quit` yourself, since it is a built-in CLI command and not a skill, so tell him
to type it. If the handoff was chosen, offer the same quit prompt again once it is
written.

## Silent mode, before a handoff

The `handoff` skill runs Rule 2 by itself first (its Step 0): sweep for your
own eyes, fix the small items, carry the rest into the handoff. No report, no
prompts, no Rule 4 question in that case.

## What this is not

- Not a handoff. Use `handoff` / `session-handoff` for persisting context so work
  can resume; this is about deciding what is still owed. Rule 4 only *offers* one
  at the end.
- Not task verification. Use `verify-and-stop` to prove one task meets its
  acceptance conditions; this sweeps the whole session, including things nobody
  set acceptance conditions for.
- Not a scope expansion. Finding a loose end does not license fixing it. The
  exception is category 5 — make a finding durable before you report it, because
  reporting it is useless if the record dies with the session.

## Prior art, if a more comprehensive tool is wanted

Nothing local covers this. Externally, closest first:

- **[conclude-it](https://github.com/DevOtts/conclude-it)** (DevOtts) — the most
  comprehensive: one door for session close, pairing a ship pipeline (test gate →
  deploy → prod gate) with a close core of debrief, ledger, sweep and an honest
  verdict. Per-repo setup interview, config in `CLAUDE.md` / `AGENTS.md` /
  `.conclude-it/config.md`. Worth adopting if session-close should also *ship*.
- **glitchwerks session-analysis** — assesses whether the agent stayed on task and
  what it acknowledged leaving undone. Narrower, and retrospective rather than
  decision-producing.
- **petekp claude-code-audit** — audits many past sessions for step-change
  workflow improvements. A different altitude: meta-level, not this-session.

This skill deliberately keeps the decision-prompting half, which none of those
do, and stays out of deploy.
