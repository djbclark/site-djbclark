# Session Handoff & Context-Compaction Spec (v0.4)

**Status:** v0.1–v0.3 built and in use; v0.4 built 2026-08-04.
**Note (2026-10-09, #137 C2.3):** the "`~/ops` stays deploy-only, pinned to tagged
releases" and `~/src/ops-worktrees/` assumptions below were retired 2026-08-23
(`~/ops` is edited in place on `master`). The live protocol is the `session-handoff`
skill in `~/src/djbclark-ade/skills/session-handoff/`.
**Author:** Claude Code, 2026-08-03/04, at the operator's request.
**History:** v0.1 = original two-tier synthesis of REMvisual/claude-handoff
+ davidshaevel/session-handoff. v0.2 = revision after four independent
external reviews (no local-environment context). v0.3 = re-examination with
full local-environment knowledge; supersedes both in place. v0.4 = fixes a
real gap v0.3 shipped with: one workspace per session was the wrong
assumption (§0a).

## 0a. What changed in v0.4 and why

**The gap:** v0.3's Tier 1 design (§3) keyed one `SESSION_LOG.md` per
`(repo, task)` directory, one git anchor each. In practice a session
routinely touches two locations *at once* — a worktree task and the
matching `~/ops` deploy checkout (checking PR merge status, running a
release) — which produced two independent files to remember to update and
two to check on resume, with nothing tying them together except the
`chain` field a writer had to remember to copy by hand into both. First
surfaced 2026-08-04 when the operator pushed back on treating
`~/src/ops-worktrees/` and `~/ops/` as two equally-valid places for the
*handoff procedure* to live, even though the directories themselves stay
split by design (`[[feedback_ops_worktrees_only]]` — pinned-release deploy
vs. tracking `master`, confirmed still correct and explicitly not being
merged).

**The fix:** the durable log becomes chain-canonical, not
directory-canonical.

- One real log per chain, at
  `~/.local/state/handoffs/chains/<chain-key>/SESSION_LOG.md`, holding a
  `workspaces:` list — one entry per touched location, each with its own
  `repo`/`task`/`dir`/`branch`/`head_sha`/`dirty`, so per-workspace
  staleness checking (§3's whole reason for being out-of-tree and
  git-anchored) still works for every location, not just the one the
  reading agent happens to be sitting in.
- Every touched directory still gets a file at the old conventional path
  (`~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md`), now a **thin
  pointer** (`redirect: chains/<chain-key>/SESSION_LOG.md`) instead of a
  full log. This is what preserves the §3 discovery behavior (`ls` the
  repo directory, read whatever's there) and the herdr bootstrap-packet
  convention (§7) of naming a path under a specific workspace.
- One write (`session_log.py write`) now takes a `workspaces` list and
  updates the canonical file plus every pointer atomically in one call —
  the two-files-to-keep-in-sync problem is closed by construction, not by
  discipline.
- A pointer with no `redirect` key is a pre-v0.4 legacy log, read as
  already-canonical — old files keep working unmigrated; migration is
  opt-in per directory, done the next time that workspace is written
  through the new tool (§9).

**What did not change:** the directories themselves. `~/ops` stays
deploy-only, pinned to tagged releases; `~/src/ops-worktrees/` stays where
code moves. That split is real (confirmed 2026-08-04: `~/ops` checkouts
sit at `ops-v1.2.6` while the matching worktree `main/` checkouts are
ahead on `master`) and this spec was never proposing to touch it — only
the *handoff bookkeeping* about sessions that legitimately straddle both.

## 0. What changed in v0.3 and why

The four external reviews fixed v0.1's mechanical bugs (dangling pointers,
merge races, padding-prone validation). What they could not do — reviewing
blind — is notice that this environment already contains the correct
answers to the questions they raised. v0.3 makes three structural changes
on that basis:

1. **Tier 2 handoff docs move to `site-private/memory/handoffs/`** —
   committed directly to master under the existing memory-data exception —
   instead of `docs/handoffs/` inside each project repo on task branches.
   Rationale: handoff docs are *agent operational memory*, not project
   documentation. This one move resolves, at once: the abandoned-branch
   durability hole (docs live on master, not on branches that may never
   merge); the redaction exposure for public repos (`site-djbclark` and the
   `Shizuku` fork are public on GitHub — mined session context must never
   default into them); the PR-merge dependency for durability; per-repo
   directory sprawl across five repos; and cross-repo grep (one directory
   holds every chain for every repo). Push-immediately, already required by
   memory policy, gives off-machine backup the moment a handoff exists.
   **Policy note:** this stretches the "memory files only" exception's
   *purpose* while staying inside its letter (files under `memory/`).
   Requires explicit operator ratification — flagged in §10.
2. **Both derived index files from v0.2 are cut** (`SESSION_INDEX.md` per
   task, `ACTIVE_WORKSPACES.md` in `main/`). A maintained index is a
   staleness bug with a filename; a generated file inside `main/`
   contradicts main's reference-only role that this same spec relies on.
   Discovery becomes a *behavior*: at session start in any ops worktree,
   scan `~/.local/state/handoffs/` (one `ls` + a few short reads). Nothing
   can go stale because nothing is stored.
3. **Ownership rule corrected** from "only Claude Code writes" to **one
   writer per task workspace** — the session that owns the workspace
   (usually the orchestrator, but equally a solo Claude Code session
   running directly in a worktree). Herdr/ralph sub-agents never write
   either tier; they return completion reports and the owning session
   writes. The v0.2 rule broke in the common case of unorchestrated solo
   sessions and said nothing about two concurrent orchestrators; this rule
   covers both.

Everything else from v0.2 that survived review is retained: out-of-tree
Tier 1, git-SHA staleness anchoring, `schema_version`, ISO 8601 timestamps
with seconds+offset, required-fields validation instead of line counts,
count+age+size history caps, DAG lineage with explicit parent IDs,
collision-proof filenames, minimal PreCompact hook in scope, atomic
temp-file+rename writes, bootstrap-when-missing, the acceptance test, and
the dropped `.envrc`/`CLAUDE.local.md` merge logic (stays dropped —
config management is not session handoff).

## 1. Problem (unchanged)

Claude Code, ralph-tui, and herdr-driven vendor agents have no durable,
structured session-continuity mechanism. Today: ad hoc chat summaries, the
unstructured `docs/operations/sessions/handoff-*.md` convention in
stayturgid, and live Herdr prompts with no file backing — the confirmed
failure mode being a handoff prompt referencing tool-backed state a fresh
session couldn't see (`[[feedback_herdr_live_handoff_over_clipboard]]`).
Hermes has already solved this for itself (dual compression +
`long-context-hygiene`); it is out of scope here.

Prior art synthesized: **REMvisual/claude-handoff** (deep single-recovery:
chain-tagged immutable docs, 12-item mining checklist, context-size-scaled
extraction, PreCompact hook) and **davidshaevel/session-handoff** (cheap
cross-tool continuity: one mutable log, worktree awareness). Tier 2 below
descends from the former, Tier 1 from the latter; both diverge
substantially from their sources on placement and lifecycle.

## 2. Decisions of record

- Replace `docs/operations/sessions/handoff-*.md` — one system, not two
  (operator, 2026-08-03). Old files archive in place (§9).
- Build order: Tier 1 pointer file → herdr-orchestration skill wiring →
  ralph-tui → other vendors (operator, 2026-08-03).
- Tier 2 centralizes in `site-private/memory/handoffs/` (v0.3, pending
  operator ratification per §10.1).
- Ownership: one writer per task workspace; sub-agents report, never
  write (v0.3).

## 3. Tier 1 — pointer file + chain-canonical log (out-of-tree, mutable, cheap)

**v0.4 shape:** two kinds of file, both plain files in XDG state — never
inside a git tree, never committed. Covered by the home-directory Arq
backup (`[[project_arq_backup_paused]]` — verified working, not paused,
despite the filename).

1. **Canonical log**, one per chain:
   `~/.local/state/handoffs/chains/<chain-key>/SESSION_LOG.md`
   (`<chain-key>` = the first tag in `chain`, filesystem-slugified). This
   is the real, durable record — Current State, Recent History, and a
   `workspaces` list with one entry per touched location.
2. **Pointer file**, one per touched location, at the original
   conventional path:
   `~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md` (`<task>` =
   task-workspace directory name under `~/src/ops-worktrees/`; `main` for
   the reference checkouts, `ops` for `~/ops`). Contains only frontmatter
   — `redirect: chains/<chain-key>/SESSION_LOG.md` — plus a one-line note.
   A pointer with **no** `redirect` key is a pre-v0.4 legacy full log,
   read as already-canonical (§9).

**Why out-of-tree** (settled in v0.2, restated once): in-worktree +
gitignored state dangles across `git checkout` and is destroyed by
`git worktree remove`; both failure classes vanish when the file's
lifetime is decoupled from the worktree's.

**Ownership & writes:** any agent may read. Exactly one session — the
chain owner — writes, always atomically (temp file + `mv` rename), and one
write updates the canonical file *and every pointer for every workspace it
lists*, in the same `session_log.py write` invocation. No locks needed at
one writer; the atomic rename is crash-safety, not concurrency control.

**Canonical log format:**

```markdown
---
schema_version: 2
updated_at: 2026-08-04T14:22:17-04:00
session_id: <herdr pane id or uuid>
writer: claude-code
chain: [standalone-a1b2c3d4]          # list — tasks can span beads
latest_handoff: memory/handoffs/site-private/HANDOFF_standalone-a1b2c3d4_spec_2026-08-03_9f2c.md
workspaces:
  - repo: site-private
    task: session-handoff-compaction-spec
    dir: /Users/djbclark/src/ops-worktrees/session-handoff-compaction-spec/site-private
    branch: feature/session-handoff-compaction-spec
    head_sha: 824fca4…
    dirty: true
  - repo: site-private
    task: ops
    dir: /Users/djbclark/ops/site-private
    branch: master
    head_sha: ff5268c…
    dirty: false
---

## Current State
- Active work: [bead ID + description, or free text]
- Blockers: [list or "None"]
- Next steps: [bullets — every item must be a path, runnable command,
  or ID resolvable from cold start; never "as discussed" or bare
  references to tool-backed state]

## Recent History
### 2026-08-04T14:22:17-04:00 — claude-code
- [max 3 bullets]
```

**Pointer file format:**

```markdown
---
schema_version: 2
updated_at: 2026-08-04T14:22:17-04:00
chain: [standalone-a1b2c3d4]
redirect: chains/standalone-a1b2c3d4/SESSION_LOG.md
---

This is a pointer file — the durable log lives at the path in `redirect`
above. See site-private docs/session-handoff-compaction-spec.md §3.
```

`latest_handoff` is a repo-relative path *within site-private* — always
resolvable from master, never dangling on an unmerged branch (this is a
direct consequence of the §0.1 move).

**Reader protocol** (the half v0.1 forgot; extended in v0.4 for the
pointer hop): on start, (1) read the pointer file at the conventional
`<repo>/<task>` path if present; (2) if it has a `redirect`, follow it to
the canonical log — that file's `workspaces` list is the full picture,
not just the workspace you started from; (3) compare each listed
workspace's `head_sha` to its actual `HEAD` — any mismatch or `dirty`
drift demotes the file from briefing to lead for that workspace; (4)
state a resume plan to the operator before touching anything; (5) if the
pointer is missing or unparseable, bootstrap a minimal one from
`git status`/`git log -1` and note "no prior context found" — absence is
a state, not an error. `session_log.py read --state-root … --dir …` does
steps 1–3 mechanically and returns per-workspace staleness in its JSON.

**Caps:** 10 history entries AND nothing older than 30 days AND ≤3
bullets per entry, on the canonical log. Current State is replaced
wholesale each write, never accumulated. `workspaces` is also replaced
wholesale each write — a write declares the full set of locations still
active for that chain; a workspace not restated drops off the list (its
own pointer file keeps working, just stops getting fresh git-anchor data
until the chain includes it in a write again).

**Discovery:** no index files anywhere. Session-start behavior in the
skills: `ls ~/.local/state/handoffs/<repo>/` (or the whole root) and read
frontmatter of whatever's there — a pointer's frontmatter is enough to
show which chain it belongs to even before following the redirect.
Sub-second, cannot go stale.

## 4. Tier 2 — deep handoff docs (centralized, immutable, committed)

**Path:**
`site-private/memory/handoffs/<repo>/HANDOFF_{chain}_{slug}_{date}_{shortid}.md`
— committed **directly to master** under the memory-data exception
(`just ops-memory-sync` first, memory-only commit, push immediately, per
existing policy). One directory per target repo; `shortid` = 4 hex chars
against same-day collisions.

**Authoring:** Claude Code only, via `/handoff` (manual) — the 12-item
mining checklist and quick/deep/chunked context-size scaling carry over
from claude-handoff unchanged. Other vendors consume, never author.

**Lineage:** explicit DAG. Frontmatter carries `handoff_id` and
`parent_handoff_ids` (list; empty for roots; siblings from a shared parent
are legal). Deterministic parenting (resume prompt named the parent) is
primary; grep-by-chain-tag is recovery-only and must be labeled as
inferred in the doc it produces. Chain tags: Beads epic ID → bead ID(s) →
`standalone-{hex}`, unchanged.

**Validation gate — required fields, all present or the handoff is not
done:** objective; exact git state (branch, `head_sha`, dirty list);
files changed; tests run + results; decisions + rejected alternatives;
failed approaches + why; blockers/open questions; ONE explicit next
action; parent linkage (or explicit "none"); redaction check passed.
Line counts are a soft thinness signal only.

**Redaction:** never write credentials, tokens, `.env` values, or key
material into any handoff — site-private being private is defense in
depth, not permission. The public-repo exposure class from v0.2 is
structurally gone (nothing handoff-shaped is written to project repos at
all), which is cleaner than policing it per-write.

## 5. Worktree cleanup (now nearly trivial)

- Tier 2 docs are on site-private master from the moment they're written
  — branch/PR fate of the *task* repos is irrelevant to handoff
  durability. The v0.2 "abandoned branch loses its handoffs" gap is
  closed, not deferred.
- On teardown: delete `~/.local/state/handoffs/<repo>/<task>/` for each
  repo the task touched. If work was abandoned, write one final Tier 2
  doc first ("abandoned: why") — abandonment rationale is precisely the
  failed-approach data this whole system exists to preserve.
- `.envrc` / `CLAUDE.local.md`: out of scope, permanently, from this
  spec's perspective. If drift ever hurts, it gets its own design.

## 6. Hooks (minimal PreCompact, in scope)

`PreCompact` hook (Python 3, stdlib-only, registered in
`~/.claude/settings.json`): write a standalone **sidecar checkpoint
file** (`precompact-<utc-ts>.md`, atomic temp+rename) next to
`SESSION_LOG.md` — timestamp, `compacted: true`, trigger, current
branch/`head_sha`/dirty-list, transcript path from the hook's JSON
input. The hook never edits `SESSION_LOG.md` itself: in-place mutation
of a structured file from a must-never-fail script is the wrong risk to
take, and an append-only sidecar cannot corrupt anything. The next
owned write folds sidecars into Recent History and deletes them;
readers treat sidecars newer than `updated_at` as superseding the log's
recency. Exit 0 unconditionally. Installed globally.

**Scope (revised 2026-08-03, supersedes the §10.2 ratification below):**
the hook now fires for every compaction in every session, not just ones
resolving under `~/src/ops-worktrees/` or `~/ops/`. `resolve_workspace()`
never returns "not applicable" — the two recognized ops-path shapes
still get their existing clean `(repo, task)` derivation; anything else
falls back to a git-root-relative key (repo = git root directory name,
task = the sub-path within it, or `root` at the top) or, if there's no
git repository at all, a key derived from the literal directory path.
Operator's call, reversing the original scope-limited recommendation:
uniform behavior everywhere was worth more than avoiding sidecar files
in non-ops directories, and the sidecar write itself is cheap
(stdlib-only, no network, no model call). The optional enrichment step
(next paragraph) scales with this too — the operator explicitly chose
"everything everywhere" over scoping enrichment's quota cost separately
from the sidecar's scope.

**Detached enrichment (added 2026-08-03, operator authorized SDK +
library use):** after writing the sidecar, the hook fires one detached
background process (`start_new_session`, never blocking or failing the
compaction) that uses the Claude Agent SDK with Haiku to mine the
session *transcript* — which the hook receives the path to — into a
`*-enriched.md` companion sidecar: goal, failed approaches, decisions,
raw measurements, next steps. This closes the gap the original design
deferred: unplanned compaction previously kept only git state and lost
conversational nuance; the transcript has that nuance and a cheap model
can extract it after the fact. Kill switch: `HANDOFF_ENRICH=0`.
Synchronous *in-hook* extraction remains permanently out of scope. The
hook itself stays stdlib-only — SDK and other dependencies live in the
separate `handoff-tools` venv the hook merely shells out to if present.

## 7. herdr-orchestration wiring (build step 2)

Amend `~/.claude/skills/herdr-orchestration/SKILL.md` "Session-to-session
handoffs" section:

- Owner writes Tier 1 (and Tier 2 if warranted) *before* spawning the
  next session.
- The spawn prompt is a **bootstrap packet**, not a context dump: repo +
  workspace path, one-line objective, absolute Tier 1 path, instruction
  to report whether the file was found and whether `head_sha` matches,
  and a 2-3 line critical-fallback summary in case the path is wrong.
  This keeps a broken path from producing a context-free agent — the
  exact failure the file-based design exists to prevent, one level down.
- Vendor awareness is explicit work, not free: one pointer line per
  vendor rules file (`AGENTS.md`, `.cursorrules`, `GEMINI.md`, …) naming
  the Tier 1 path convention and reader protocol. The plain-markdown
  format is portable; the *convention* must be installed per vendor.
- Sub-agents report; the owner writes. Unchanged policy, now with a
  mechanism.

## 8. Acceptance criteria

v0.1-build is done when: kill an owning session mid-task with no
`/handoff`. Give a fresh agent only the Tier 1 absolute path. It must
read, staleness-check against real `HEAD`, state a resume plan, and ask
the operator nothing the file already answers. Then repeat via a real
compaction with the §6 hook installed. Then repeat cross-vendor: a
herdr-spawned non-Claude agent must pass the same test from the bootstrap
packet alone.

## 9. Migration

Existing `stayturgid/docs/operations/sessions/handoff-*.md` files stay as
frozen archive; add one README line there pointing at the new convention.
New handoffs go exclusively to `site-private/memory/handoffs/` from
adoption day. No retroactive conversion — the old docs' value doesn't
justify the churn, and the new system's chain lineage starts clean.

**v0.4 Tier 1 migration:** no forced conversion either. Existing
pre-v0.4 `SESSION_LOG.md` files (full logs, no `redirect` key) keep
reading as already-canonical (§3) until the next real
`session_log.py write` through that workspace, which naturally produces
a canonical-log-plus-pointer pair and folds the old file's history in.
The two files live at adoption time —
`~/.local/state/handoffs/site-private/ops/` and
`~/.local/state/handoffs/site-private/add-context-nudge-hook/`, both
already sharing `chain: [standalone-ecc2]` — were hand-merged into one
canonical file under `chains/standalone-ecc2/` as part of the v0.4
change, since they were already mid-session at the same chain and hand
verification was cheap for exactly two files.

## 10. Open questions (now two, both genuinely the operator's)

1. **Ratify the memory-exception stretch.** Tier 2 in
   `site-private/memory/handoffs/` keeps to the letter of the "memory
   files only" rule but broadens its traffic: handoffs will be written
   far more often than memory facts, and each write is a master commit +
   push in the deploy checkout. If that commit cadence on `~/ops`
   master feels wrong, the fallback is the same path *authored via the
   normal worktree flow batched at natural boundaries* — durability then
   lags authoring by one PR cycle, which weakens the §5 guarantee. My
   recommendation: ratify the direct-to-master path; the memory exception
   exists precisely because operational agent state can't wait on release
   cadence, and handoffs are the most operational state there is.
2. **PreCompact hook scope: global or opt-in per directory?** ~~A global
   hook fires in every Claude Code session on this machine, including
   ones with no workspace concept (e.g., this home-directory session).
   Recommendation: install globally but make the script a no-op unless
   cwd resolves inside `~/src/ops-worktrees/` or `~/ops` — one `case`
   statement, and non-ops sessions stay untouched.~~ **Superseded
   2026-08-03** (see §6): operator decided the hook should fire
   everywhere, not just recognized ops paths — including the optional
   enrichment step, not just the cheap sidecar write. `resolve_workspace()`
   now falls back to a git-root-relative or path-derived key instead of
   returning "not applicable" for anything outside the two ops shapes.
   Left struck through rather than deleted so the original reasoning
   (and that it was a deliberate, ratified choice before being
   deliberately reversed) stays visible.

Everything the four reviews raised is now either adopted, rejected with
stated reasoning (§0), or closed by construction (§4 redaction class,
§5 abandoned-branch class).
