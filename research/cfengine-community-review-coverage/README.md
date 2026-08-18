# CFEngine community review coverage via whitespace-only minification — idea stage, not started

Captured 2026-08-18 from a tendcf session working the CFEngine upstream
fix queue (see `djbclark/tendcf` `docs/architecture/upstream-register.md`).
Written down so the tradeoffs don't need to be re-derived in a future
conversation — **this is not a plan to execute yet**, see Status below.

## The idea

Ultrareview (`/code-review ultra`) caps at 500 files / 12,000 lines, lines
binding first. `cfengine/core` is far larger than that in total. Proposal:

1. Run a whitespace-only compactor (comments + blank lines stripped, **no
   identifier renaming**) over logical subsystems of `cfengine/core`.
2. Segment the compacted output into chunks that each fit under the
   ultrareview cap.
3. Publish a guide (tool choice, segmentation, how to run ultrareview
   against a chunk) so that other CFEngine contributors — not just this
   session's operator — can each spend their own ultrareview usage on a
   different chunk.
4. Aggregate results into a public coverage map: which subsystems have
   been AI-reviewed, which haven't, so nobody duplicates effort.

Goal: maximize total upstream code reviewed per dollar spent, spread
across multiple contributors' accounts rather than one.

## Why whitespace-only, not full minification

C only requires physical newlines around preprocessor directives
(`#include`, `#define`, ...); everything else between tokens can be
collapsed. Two tool categories came up researching this:

- **Renaming minifiers** (e.g. `minify-C` by chrehall68, `shortC`) shrink
  structs/fields/vars to short names *and* strip whitespace. Rejected:
  this project's whole verification discipline runs on `file.c:line`
  citations against real upstream master (every panel brief, every Jira
  correction, every register row cites exact lines) — renamed identifiers
  and shifted line numbers break that traceability outright.
- **Whitespace/comment-only compactors** (e.g. `cminify` by Scylardor,
  `C-Minifier` by BaseMax) preserve every identifier, only removing
  comments/blank lines and packing statements onto fewer physical lines.
  Names survive, so a real finding can still be re-located in the true
  source by `grep`-ing the name — at the cost of needing to re-derive the
  true line number before citing it anywhere public. Neither tool has
  been vetted for correctness (string-literal/macro handling, round-trip
  fidelity) — that would be the first real step if this goes forward.

## Open premises — unverified, block starting work

1. **"Free ultrareview credits" for CFEngine contributors** — the idea
   that other contributors have some free/allotted ultrareview usage to
   spend. This was the operator's framing; it has not been confirmed to
   actually exist as an Anthropic program or CFEngine-specific grant. Do
   not write a guide premised on this until confirmed.
2. **Whether minification meaningfully increases coverage per pass at
   all.** cfengine/core's C is already fairly dense (see the traps
   documented in the register — this isn't sparse, comment-heavy code in
   most of the hot files). The real yield from whitespace-only packing
   hasn't been measured against a real subsystem.
3. **Whether a chosen compactor round-trips cleanly** — no tool from the
   research pass has been run against real cfengine source yet.

## Why this wasn't started immediately

This session's register shows near-zero upstream maintainer engagement
(one reply each from `larsewi` and `nickanderson` across the whole
2026-08-18 session; most filed tickets/PRs sit untouched). Standing up a
public guide + tooling + segmentation plan and asking the wider
contributor base to adopt a new AI-assisted workflow, before anyone
upstream has asked for it or shown appetite, risks landing the same way
an unprompted mass PR would. Recommended sequencing if this goes forward:
float the idea informally first (a comment on an existing ticket already
being discussed with an engaged maintainer, not a cold announcement),
gauge appetite, *then* invest in the guide.

## Alternative that needs no minification at all

If the real constraint per contributor is "cost of running ultrareview
repeatedly," multi-pass coverage already solves it without touching the
source: run ultrareview once per coherent subsystem (the `exec_timeout`/
`ALARM_PID` family — `unix.c`, `pipes_unix.c`, `timeout.c`,
`verify_exec.c` — as one pass; the mount/NFS family — `nfs.c`,
`verify_storage.c` — as another; etc.), each naturally under the line cap,
no compression risk, every finding directly citable. This only fails to
suffice if the actual constraint is "one ultrareview invocation total per
contributor" (ties back to open premise 1) — worth confirming before
assuming minification is even the right lever.

## Status

**Idea stage. Not started.** Next step, if picked back up: verify premise
1 (free-credits claim) and premise 3 (pick one whitespace-only compactor,
run it against one real cfengine subsystem, check it round-trips and
measure actual line-count reduction) before writing any guide or
segmentation plan.
