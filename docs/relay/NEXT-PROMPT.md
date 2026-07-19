# NEXT: G1 — gate-debt retro-verification (difficulty 25/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md` § Gate-debt remediation).
No human gates — self-verify per PROTOCOL.md. This is mechanical re-running of
checklist claims, not architecture judgment.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account
  (djbclark@gmail.com)**, effort **Medium/Low** (mechanical command-running,
  not judgment). Do not burn Fable 5 quota here.
- **Alt —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` · Low,
  Medium, High (default High) · _Flagship for code + agentic work._ Use
  **Low** if Claude original-account quota is tight.
- **Escalation:** only if mechanical re-runs hit a systemic tooling break
  (broken venv, missing master, unreadable logs) that blocks the audit
  document itself — not for individual failed claims (record them and
  continue).

**Working dir:** `/Users/djbclark/ops/site-djbclark` (audit output + relay) +
`/Users/djbclark/ops/stayturgid` (re-run product checks; stay on master).

---

You are executing **G1** (gate-debt remediation): re-verify every mechanically
checkable checklist claim from ALL ledger stages to date, then hand off to R1.

## Why this exists

Human gates were confirm-stamped without inspection for the entire project.
Every "human-verified" checklist claim in LEDGER.md (B1–B6, B-review, C1–C6,
D0-design, D1) is actually unverified. G1 is the cheap mechanical audit so R1
(Fable 5) only judges failures/flags + D1 architecture — not re-runs checks.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session;
   merge-your-own-PR if you touch stayturgid; site repo → master).
2. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-phase-d-funding-plans-v1.md`
   § Gate-debt remediation (G1 scope + output format) and § Review checkpoints
   (R1 after G1).
3. `/Users/djbclark/ops/site-djbclark/docs/relay/LEDGER.md` — **walk every row
   from the first entry**; extract every checklist / verification claim.
4. Ground rules: step2 plan
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 (do not rediscover known gotchas; do not redesign).
5. D1 live state context (for claims about caddy): design notes
   `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   §1.9; expect `com.djbclark.caddy` running, old plist retained.

## Task

1. Parse LEDGER.md for every stage B1–B6, B-review, C1–C6, D0-design, D1 (and
   any earlier step0/step1 stamps if present). For each verification claim
   that is **mechanically checkable today**, re-run it.
2. Typical checkable claims (non-exhaustive — ledger is authoritative):
   - `just check` / `just test` green in stayturgid (on **pulled master**)
   - pre-commit / hosted CI green on merged master
   - `bin/registry_lint.py` in site repo
   - `just validate-identity` / strict identity clean
   - site-sync second run no-op; Entangled parity / `just site-contract-check`
   - registry seeds `--check`; overlay + upstream-only strict identity
   - health endpoints still up (`curl` caddy 8080, HTTPS front door if claimed)
   - branch hygiene: stayturgid on master, no leftover step branches for done steps
   - file existence claims (generated/, site_ns in group_vars, etc.)
3. **Do not** try to re-prove historical one-shot migration events that cannot
   be re-run without cutting over again — mark those
   `not-mechanically-checkable` with a short why.
4. **Do not** fix failures unless they are trivial and in-scope for a cheap
   audit (e.g. re-run after stale cache). Real failures go in the audit as
   `failed` for R1 to judge (correctness/safety must-fix; arch/style defer).
5. Output: **`docs/relay/reviews/gate-debt-audit.md`**
   - One row per claim: stage id | claim text (short) | verified-now | failed |
     not-mechanically-checkable | evidence (command + key output / hash)
   - Summary counts at top
   - List of `failed` rows that R1 must treat as must-fix candidates

## Constraints

- No device contact required; keep it that way.
- No secrets in any commit.
- Do not redesign adapters or re-open D1 architecture (R1 owns that).
- Site `registry/paths.yml` still uses step1 schema — note if it blocks a
  claim; do not "fix" drive-by.
- uv-shebang: broken venv → `rm -rf` + `just test-venv`, never hand-edit.

## Verification (self-verify)

- Audit file exists and covers every ledger stage row that made a checklist claim.
- Every `verified-now` row has re-run evidence from this session (not copied
  from old ledger prose alone).
- stayturgid left on pulled master if you checked it out; site commits on master.
- No open stayturgid PR unless you made a must-fix and merged it (prefer record
  failure for R1 over drive-by fixes).

## End of session

Follow PROTOCOL.md exactly:

1. Append ledger line `G1` with path to audit + summary counts + any
   `DEVIATION:` notes.
2. Rewrite `NEXT-PROMPT.md` as the **R1 review baton**:
   - **Recommended AI:** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
     `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
     Auto) · _Next-gen long-running agents_ — **new second-Pro account**,
     effort **Medium**.
   - **Scope:** (a) G1 failures/flags from `gate-debt-audit.md`; (b) D1
     architecture review proper against
     `docs/design/phase-d-adapter-design-notes.md` (correctness/safety
     must-fix; architecture/style deferred to ledger per FUND-B).
   - Commits in scope: stayturgid PR #17 / master after D1 merge; site D1
     commits; G1 audit.
3. Commit/push site repo (straight to master). If stayturgid changes were
   needed and PR'd, merge + delete branch + end on pulled master.
4. Print the new baton in chat and
   `pbcopy < docs/relay/NEXT-PROMPT.md`.
