# Relay protocol — self-promulgating session chain

Each work session is one link in a chain. The chain survives context loss
because the **baton** is a committed file, not a conversation.

## The three files (all in `docs/relay/`)

| File | Purpose |
| --- | --- |
| `PROTOCOL.md` | This file — the rules every session follows |
| `NEXT-PROMPT.md` | **The baton.** Always contains exactly one prompt: the one to paste into the next AI. Never contains history |
| `LEDGER.md` | Append-only log: one line per completed step |

## Human ritual (start of each session)

1. Open `~/ops/site-djbclark/docs/relay/NEXT-PROMPT.md`.
2. The **header** names the recommended AI (primary / alternate / escalation)
   and the working directory. Recheck quotas (CodexBar) — if the primary's
   pool is empty, use the alternate; band logic is in the step2 plan §1.
3. Paste the **body** (everything below the `---` line) into that AI.

## AI ritual (end of each session)

A session may end only in one of two states:

**A. Step complete.** In order:

1. Present the step's verification checklist to the human with evidence
   (command outputs, URLs, commit hashes). **Wait for the human to confirm
   each check.** Do not self-certify.
2. Append one line to `LEDGER.md`:
   `| <date> | <step id> | <AI used> | <commits/PR> | <notes, incl. anything deferred> |`
3. Rewrite `NEXT-PROMPT.md` for the **next step** in
   `docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`, using the
   template below. Carry forward: any deferred sub-items, any new gotchas
   discovered, the step's row (difficulty, AI, notes) from the step2 plan.
   If the next step is marked **OPERATOR GATE**, say in the header what the
   human must do or approve before pasting the prompt.
4. Commit and push everything (this repo: master; stayturgid: branch + PR
   per its AGENTS.md).
5. Print the new NEXT-PROMPT.md contents in chat, so the human can hand it
   straight to the next AI.

**B. Blocked / escalating.** Rewrite `NEXT-PROMPT.md` for the **same step**,
addressed to the escalation model, with a findings section (what was tried,
exact errors). Ledger line gets `ESCALATED`. Commit, push, print.

## NEXT-PROMPT.md template

```markdown
# NEXT: <step id> — <title>   (difficulty <n>/100)

**Recommended AI:** <primary> · alt: <alternate> · escalate to: <model>
**Working dir:** <path>   **Operator gate:** <none | what the human must approve>

---
<self-contained prompt body: role, files to read (absolute paths), exact
task spec, constraints, verification commands, human-verification checklist,
and the instruction to follow docs/relay/PROTOCOL.md at session end>
```

## Invariants

- Prompts are self-contained: absolute paths, no "as discussed", no secrets.
- One step per session unless the step2 plan row says otherwise.
- The ground rules in step2 plan §0 and the risk register in §2 are part of
  every session's required reading — every prompt body links them.
- Editing this protocol requires the operator.
