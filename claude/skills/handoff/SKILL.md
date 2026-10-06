---
name: handoff
description: Create a deep Tier 2 handoff document — chain-tagged, DAG-linked, mined from the full conversation. Lands in site-private/memory/handoffs/ for the ops-djbclark suite, or inside the current project's own repo otherwise. Use when pausing substantial work, before ending a long session, or when the operator says "do a handoff", "create a handoff", "save session context".
---

# Handoff — Tier 2 deep recovery document

Spec: `~/ops/site-private/docs/session-handoff-compaction-spec.md` (v0.3).

## Project scope

Two regimes — pick this first, it determines the output path and Step 6's
commit flow:

- **ops-djbclark suite** (target repo is `stayturgid`, `site-djbclark`,
  `site-private`, `Shizuku`, or `ops-djbclark`): unchanged existing
  behavior. Output `~/ops/site-private/memory/handoffs/<target-repo>/` —
  committed DIRECTLY TO MASTER under site-private's own memory-data
  exception, pushed immediately (Step 6 below).
- **Any other project**: output lives inside that project's own repo, at
  `<repo-root>/docs/handoffs/`. Commit locally in that repo (Step 6 below)
  — do **not** push automatically. Pushing to a project you don't have an
  explicit standing exception for is a "visible to others" action per the
  general action-care policy; site-private's push-immediately rule is a
  specific, deliberate carve-out that repo's own AGENTS.md/CLAUDE.md
  declared, not a default other repos inherit. If that project's own
  AGENTS.md/CLAUDE.md declares an equivalent "memory is data, commit (and
  push) in place" exception, follow it and push; otherwise leave the
  commit local and tell the operator it's ready to push whenever they want.

## Guards

- Only the workspace-owning session runs this. Sub-agents never do.
- Never generate handoff-like documents freeform outside this skill.
- Only when the operator (or owning orchestrator) explicitly wants a
  handoff created now. If ambiguous, ask.
- Not in plan mode.

## Step 1 — Gather external state (parallel Bash, never agents)

`git log --oneline -15`, `git diff --stat`, `git status -s | head -30`,
`git branch --show-current`, `git rev-parse HEAD`; Beads state if
available and this is an ops-djbclark-suite repo (`bd list
--status=in_progress`) — skip this bullet entirely for other projects
unless that project also uses Beads; list existing handoffs at the
Project-scope-resolved output directory for this target repo (e.g. `ls
~/ops/site-private/memory/handoffs/<repo>/` or `ls
<repo-root>/docs/handoffs/`).

## Step 2 — Chain tag and lineage

Chain tag, first match: (1) Beads epic ID; (2) 1–4 bead IDs (list);
(3) `standalone-{4-hex}` (`python3 -c "import secrets;print(secrets.token_hex(2))"`).

Lineage is an explicit DAG:
- `handoff_id`: fresh 4-hex id.
- `parent_handoff_ids`: if this session started from a resume prompt
  naming a parent handoff file, that file's id (deterministic — primary).
  Else grep this target repo's Project-scope-resolved output directory for
  the chain tag as RECOVERY ONLY: a shared bead is a candidate, not proof — read
  the candidate's "Where We're Going"; only clear continuation makes it
  a parent, and the new doc must say `lineage: inferred`. Doubt → ask
  the operator. No parent → `[]`.

## Step 3 — Mine the conversation

Announce pass choice: Quick (<100K context) / Deep (100K–500K) /
Chunked map-reduce (500K+).

**Scope narrowed 2026-08-23: capture position and intent, not the
transcript.** Every session is archived losslessly in S1 (448k events,
indexed), so re-narrating what happened is duplicated effort that also
drifts from the record. Write what S1 cannot reconstruct — the state in
your head:

- goals, and where you actually are against them;
- work completed, concretely (files, functions, numbers);
- **FAILED approaches + why** — still the most expensive thing to
  rediscover, and the one thing a transcript buries rather than surfaces;
- decisions + the alternatives rejected, with the reason;
- open questions, blockers, dependencies, and the intended next move.

**Do not** transcribe discoveries, gotchas, signatures, or constants that
the session already contains — link to them instead. Recover any of it
with:

```bash
~/ops/site-djbclark/bin/s1_search.py search '<phrase>' --mode trigram
~/ops/site-djbclark/bin/s1_search.py neighbours <event_id> --window 5
```

Durable machine facts belong in the curated layer, not a handoff: an
operator-verified fact goes to `docs/` or the relevant skill; model-mined
leads land in `~/basic-memory/mined/` via `bin/mine_sessions.py`. A
handoff that carries them becomes a second canon that nobody updates.

## Step 4 — Write the file

Path: `<output-dir>/HANDOFF_{chain}_{slug}_{YYYY-MM-DD}_{handoff_id}.md`,
where `<output-dir>` is `~/ops/site-private/memory/handoffs/<repo>/` for
the ops-djbclark suite or `<repo-root>/docs/handoffs/` otherwise (slug:
2–4 kebab words; multi-bead chains use the primary bead in the filename).
`mkdir -p <output-dir>` if needed.

    ---
    schema_version: 1
    handoff_id: <4 hex>
    parent_handoff_ids: []
    lineage: deterministic|inferred|none
    chain: [<ids>]
    repo: <target repo>
    workspace: <task dir name>
    branch: <branch>
    head_sha: <sha>
    created_at: <ISO 8601 with offset>
    writer: claude-code
    ---
    # Handoff — <title>
    ## The Goal
    ## Where We Are
    ## What We Tried            <- failed approaches, chronological, with why
    ## Key Decisions            <- chosen AND rejected
    ## Evidence & Data          <- real numbers, file paths
    ## Operator Feedback
    ## Where We're Going        <- ordered; item 1 is THE next action
    ## Quick Start              <- exact commands for the next session

## Step 5 — Validation gate (all required; line count is NOT the gate)

- [ ] Objective stated
- [ ] Exact git state (branch, head_sha, dirty list)
- [ ] Files changed this session
- [ ] Tests run + results (or explicit "none run")
- [ ] Decisions + rejected alternatives
- [ ] Failed approaches + why
- [ ] Blockers / open questions
- [ ] ONE explicit next action at the top of Where We're Going
- [ ] Parent linkage (ids, or explicit none)
- [ ] Redaction: no credentials, tokens, .env values, key material,
      anywhere in the doc

Any unchecked box: fix before proceeding. Thin sections: expand from the
conversation, don't pad.

## Step 6 — Commit

**ops-djbclark suite target (memory exception flow, EXACTLY this):**

1. `cd ~/ops/site-djbclark && just ops-memory-sync`
2. `cd ~/ops/site-private && git add memory/handoffs/ && git commit -m "memory: handoff <repo>/<filename>"`
   — memory-only commit; NOTHING else staged.
3. `git push` immediately. Leave the tree clean.

**Any other project target:**

1. `cd <repo-root> && git add docs/handoffs/ && git commit -m "docs: handoff <slug>"`
   — handoff-only commit; nothing else staged.
2. Push only if that project's own AGENTS.md/CLAUDE.md declares an
   equivalent memory-is-data exception (see Project scope above);
   otherwise leave it committed locally and say so to the operator.

## Step 7 — Update Tier 1

Via the `session-handoff` skill's writer protocol: set `latest_handoff` to
the new handoff file's path (site-private-relative for the ops-djbclark
suite, repo-relative otherwise), refresh Current State, add a history
entry. Then report to the operator: file path, chain + lineage,
validation outcome, the next action, and (for a non-ops-djbclark target)
whether the commit was pushed or is waiting locally.
