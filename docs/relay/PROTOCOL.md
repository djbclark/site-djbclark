# Relay protocol — self-promulgating session chain

Each work session is one link in a chain. The chain survives context loss
because the **baton** is a committed file, not a conversation.

## The three files (all in `docs/relay/`)

| File             | Purpose                                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------------------ |
| `PROTOCOL.md`    | This file — the rules every session follows                                                                  |
| `NEXT-PROMPT.md` | **The baton.** Always contains exactly one prompt: the one to paste into the next AI. Never contains history |
| `LEDGER.md`      | Append-only log: one line per completed step                                                                 |

## Human ritual (start of each session)

1. Open `~/ops/site-djbclark/docs/relay/NEXT-PROMPT.md`.
2. The **header** names the recommended AI (primary / alternate / escalation)
   and the working directory. Recheck quotas (CodexBar) — if the primary's
   pool is empty, use the alternate; band logic is in the step2 plan §1.
3. Paste the **body** (everything below the `---` line) into that AI.

## AI ritual (end of each session)

A session may end only in one of two states:

**A. Step complete.** In order:

1. Run the step's verification checklist yourself and record the evidence
   (command outputs, URLs, commit hashes) in the session and the ledger note.
   Human confirmation is **not** required (operator decision 2026-07-19 —
   FUND-B ledger line); for hard-to-reverse actions (TLS cutover, daemon
   retirement, fleet deploys), substitute extra verification commands for
   human eyes: health checks before and after, a tested rollback command
   noted in the ledger, and never delete the old path in the same session
   that stood up the new one.
2. Append one line to `LEDGER.md`:
   `| <date> | <step id> | <AI used> | <commits/PR> | <notes, incl. anything deferred> |`
3. Rewrite `NEXT-PROMPT.md` for the **next step** in
   `docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`, using the
   template below. Carry forward: any deferred sub-items, any new gotchas
   discovered, the step's row (difficulty, AI, notes) from the step2 plan.
   Steps marked **OPERATOR GATE** in older plan rows are no longer gated
   (FUND-B decision) — instead, carry the gate's substance into the body as
   extra self-verification: before/after health checks, a tested rollback
   command, and old-path retirement deferred to a later session.
4. Commit and push everything. This repo: straight to master. stayturgid:
   branch + PR — and then, **in the same session, once the checklist
   evidence is recorded: merge the PR
   (`gh pr merge <n> --merge --delete-branch`), run
   `git checkout master && git pull --ff-only` in `~/ops/stayturgid`, and
   verify the repo's check suite is green on merged master.** Never end a
   session with an open PR, an undeleted step branch, or the stayturgid
   checkout off master — the next session must start from a master that
   contains your work.
5. Print the new NEXT-PROMPT.md contents in chat, so the human can hand it
   straight to the next AI, **and copy the baton to the clipboard**:
   `pbcopy < docs/relay/NEXT-PROMPT.md`.

**B. Blocked / escalating.** Rewrite `NEXT-PROMPT.md` for the **same step**,
addressed to the escalation model, with a findings section (what was tried,
exact errors). Ledger line gets `ESCALATED`. Commit, push, print.

## NEXT-PROMPT.md template

```markdown
# NEXT: <step id> — <title> (difficulty <n>/100)

**Recommended AI:** <primary> · alt: <alternate> · escalate to: <model>
(full catalog rows; Claude picks name the account; self-passoff allowed)
**Working dir:** <path>

---

<self-contained prompt body: role, files to read (absolute paths), exact
task spec, constraints, verification commands, self-verification checklist
with recorded evidence, and the instruction to follow
docs/relay/PROTOCOL.md at session end —
including printing the next baton AND copying it to the clipboard with
`pbcopy < docs/relay/NEXT-PROMPT.md`>
```

## Review batons (end-of-stage code reviews)

Some steps are followed by a dedicated **review session** before work
continues. Review checkpoints are listed in
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md` (§ Review checkpoints)
— currently **R1 after D1**, **R2 after D4**, **R3 after D8**.

A review baton is a normal baton in every way: same template, same header
(recommended AI quoted as full catalog rows), same end-of-session ritual
(ledger line with step id `R<n>`, rewrite `NEXT-PROMPT.md` for the next step,
commit/push, print, `pbcopy`). The body differs only in task shape:

- Scope: all commits landed since the previous review checkpoint (both repos).
- Deliverables: findings fixed or explicitly deferred to the ledger line.
  **Correctness and safety findings must be fixed**; architecture and
  code-style findings may be deferred to the ledger (operator accepts lower
  quality now, recovered in month M1 — see the funding-plans doc).
- The session that completes the step _before_ a checkpoint writes the review
  baton as its NEXT-PROMPT.md, so the review is always the next session in
  the chain; it is not optional.

## Recommending an AI

When a baton header (or any answer to the operator) names a **recommended
AI**, draw it from `docs/reference/available-ai-models.md`. Each recommended
option must be quoted with its full row of information from that table —
source, vendor/make, model name, variant/ID, thinking levels, and notes — plus
any caveats or extra guidance worth adding.

**Self-passoff:** if the AI currently running is itself a reasonable recipient
for the next baton — judged primarily on cost, then architecture and code
quality fit — it may name itself as the recommended AI and continue in a fresh
session, rather than forcing a switch for its own sake.

**Claude accounts:** two Claude Pro accounts exist under Plan B — the
**original** (djbclark@gmail.com) and the **new** second Pro (held by a second
human). Any baton recommending a Claude-web model MUST say which account to
use. Default split: original account for Sonnet 5 and routine Claude work; new
account's weekly reserved for Fable 5 sessions (reviews, design, escalations).

## Invariants

- Prompts are self-contained: absolute paths, no "as discussed", no secrets.
- One step per session unless the step2 plan row says otherwise.
- The ground rules in step2 plan §0 and the risk register in §2 are part of
  every session's required reading — every prompt body links them.
- Editing this protocol requires the operator.
