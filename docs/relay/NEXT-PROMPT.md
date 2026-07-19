# NEXT: R1 — first-adapter architecture review (difficulty 55/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md` § Review checkpoints +
§ Gate-debt remediation). Quality bar: **correctness/safety must-fix only**;
architecture and code-style findings may be deferred to the ledger for M1.
No human gates — self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents_ — **new second-Pro account**, effort
  **Medium** (reading-heavy review; Medium is the get-away-with-it tier for
  reviews per funding plan).
- **Alt —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort — **original account**, if
  new-account Fable 5 is unavailable; still Medium effort.
- **Escalation:** Fable 5 Extra only if correctness findings are ambiguous
  and block a safe D2 clone pattern — not for style nits.

**Working dir:** `/Users/djbclark/ops/site-djbclark` (review write-up + relay)
+ `/Users/djbclark/ops/stayturgid` (read D1 code on pulled master; PR only if
you must-fix).

---

You are executing **R1** (end-of-D1 review checkpoint): judge G1's residual
flags + review the D1 caddy adapter architecture so D2–D5 can clone a sound
pattern.

## Why this exists

G1 already re-ran every mechanically checkable checklist claim across all
ledger stages. **Do not re-run green suites** unless you change code. Your
job is judgment: correctness/safety on D1 + G1 flags.

## Read first (absolute paths)

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (end-of-session;
   merge-your-own-PR if you touch stayturgid; site repo → master).
2. `/Users/djbclark/ops/site-djbclark/docs/relay/reviews/gate-debt-audit.md`
   — G1 output: summary counts, **Flags F1–F6**, claim table, R1 handoff notes.
3. `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
   — D0-design authority for adapter pattern (§1), D6/D8 context, deviation
   protocol (§4–5).
4. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-phase-d-funding-plans-v1.md`
   § Review checkpoints (R1 scope + relaxed quality bar).
5. Ground rules: step2 plan
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2.
6. Product specs: stayturgid `docs/architecture/site-contract.md` §5;
   ADR 005; `control/site_contract/{serverapps.py,site_map.py,site_sync.py,sync_manifest.yml}`;
   role `ansible/roles/serverapp_caddy/`.
7. Ledger: `/Users/djbclark/ops/site-djbclark/docs/relay/LEDGER.md` D0/D1/G1
   rows (incl. D1 DEVIATIONs).

## Commits in scope

| Repo       | Ref / commits                                                                 |
| ---------- | ----------------------------------------------------------------------------- |
| stayturgid | PR #17 → master `dc9ffaa` (merge); implementation `5055a93`                   |
| site       | D1 `a6cd64a` (`site_ns`, ports, justfile, caddy migration); G1 audit + baton |

## Task

### (a) G1 failures/flags

- **Failed rows:** G1 reported **0 failed**. Confirm nothing in the audit
  table is a silent must-fix you disagree with.
- **Flags F1–F6:** classify each as correctness/safety (must-fix now),
  architecture (fix if cheap else ledger for M1), or style (ledger). Do not
  re-open drive-by paths.yml schema migration unless safety requires it.

### (b) D1 architecture review proper

Against design notes §1 (and site-contract §5), review:

1. Mode selection order: site-map → foreign-config detect → own; generated
   header exclusion; exit 0/1/2.
2. Two-layer split: site-sync fragments vs `serverapps.py` + `serverapp_caddy`
   role; import of fragments from committed `generated/` (no copy).
3. Launchd namespace `com.<site_ns>.caddy`; validate-before-activate; legacy
   plist retained; documented rollback.
4. Live residual risks: control_node can re-render `com.stayturgid.caddy`
   until D7; second own-mode apply still invokes ansible ensure (D1 DEVIATION);
   bare YAML `off` coercion (D1 DEVIATION); no site-map.yml (source=default).
5. Clone-safety for D2 vector: what must D2 copy vs what is caddy-specific?

### Deliverables

1. Write review notes to
   `docs/relay/reviews/r1-d1-adapter-review.md` (findings table:
   severity, must-fix vs defer, file refs, disposition).
2. **Must-fix** correctness/safety: implement in the same session if cheap;
   stayturgid via branch+PR+merge per PROTOCOL; site straight to master.
   Prefer minimal diffs. Re-run only the checks needed to prove the fix.
3. Deferred findings: list explicitly in the ledger R1 line (and in the
   review doc) for M1-R.
4. If no must-fix: do not churn code; still write the review doc.

## Constraints

- No device contact required; keep it that way unless a safety finding
  forces a health re-check (curl 8080 / HTTPS / launchctl — read-only).
- No secrets in any commit.
- Do not redesign adapters or start D2 implementation (next baton is D2).
- paths.yml step1 schema: note only unless you classify as must-fix safety.
- uv-shebang: broken venv → `rm -rf` + `just test-venv`, never hand-edit.

## Verification (self-verify)

- Review file exists with findings + dispositions.
- Any must-fix merged; stayturgid ends on pulled master, no open PR.
- If you changed product code: `just check` green on stayturgid; site
  `bin/registry_lint.py` if you touched registry.
- Caddy still healthy if you touched launchd/config (curl /health + HTTPS).

## End of session

Follow PROTOCOL.md exactly:

1. Append ledger line `R1` with path to review, must-fix count, deferred
   list, commits/PR.
2. Rewrite `NEXT-PROMPT.md` as the **D2 baton** (vector adapter per step2
   plan Phase D row D2 + design notes). Recommended AI per FUND-B Plan B:
   Grok 4.5 Medium/High primary; carry G1/R1 residual notes that affect D2.
3. Commit/push site repo (straight to master). If stayturgid changes were
   needed and PR'd, merge + delete branch + end on pulled master.
4. Print the new baton in chat and
   `pbcopy < docs/relay/NEXT-PROMPT.md`.
)
