# NEXT: D0-design — Phase D architecture front-load (difficulty 55/100)

**Funding plan in force:** FUND-B revised (see
`docs/plans/site-djbclark-phase-d-funding-plans-v1.md`). No human gates —
self-verify per PROTOCOL.md.

**Recommended AI** (rows from `docs/reference/available-ai-models.md`; quote
the whole row, not a bare name):

- **Primary —** Claude 2.1.205 (web) · Anthropic · Claude Fable 5 ·
  `claude-fable-5` · Low, Medium, High, Extra, Max, Ultra (GUI picker; no
  Auto) · _Next-gen long-running agents._ **Use the ORIGINAL Claude account (djbclark@gmail.com)** — ~60% of
  its Fable 5 weekly remains and this is its designated spend (highest-leverage
  session in Phase D; the new second-Pro account's weekly is reserved for R1,
  D6 escalation, and M1). **Set the GUI effort picker to High** (not
  Extra/Max/Ultra — quota burn; not Low/Medium — this is a judgment session).
  Leave the lower-left yellow "Auto" control alone (safety/routing, not
  effort).
- **No alt.** If Fable 5 is unavailable on the original account, stop and tell
  the operator — do not run this design session on a lesser model; the entire
  point of Plan B is that this one session is Fable-5-authored.

**Working dir:** `/Users/djbclark/ops/site-djbclark` (deliverable lands here) +
`/Users/djbclark/ops/stayturgid` (read-only this session)

---

You are executing **step D0-design** of Phase D under funding Plan B: a
design-only session that front-loads all Phase D architecture judgment into
one Fable 5 sitting, so cheaper models (Grok 4.5, Codex, Composer) can
implement D1–D8 against a written design. **Write no implementation code and
make no changes to the stayturgid repo.** Your sole deliverable is one
committed design document in the site repo.

## Read first

1. `/Users/djbclark/ops/site-djbclark/docs/relay/PROTOCOL.md` (note: human
   gates removed — self-verify with evidence; self-passoff rule).
2. `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-phase-d-funding-plans-v1.md`
   — Plan B sequencing, relaxed quality bar, account split.
3. Ground rules + Phase D rows (D1–D8) in
   `/Users/djbclark/ops/site-djbclark/docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`
   §§0–2 and §5.
4. Site contract spec:
   `/Users/djbclark/ops/stayturgid/docs/architecture/site-contract.md`
   §§5.1–5.4, and ADR 005
   (`/Users/djbclark/ops/stayturgid/docs/architecture/adr/005-two-repo-topology.md`).
5. Existing contract code the design must fit:
   `/Users/djbclark/ops/stayturgid/control/site_contract/site_map.py`
   (serverapps.{caddy,...}.{mode,config,fragment_dir} already validated,
   modes own/inject/off — consume this, don't invent new config),
   `site_sync.py` (manifest/lockfile/plan-then-act pattern adapters must
   extend), `sync_manifest.yml`.
6. Live Caddy state on this Mac (read-only discovery): Caddyfile location,
   `com.stayturgid.caddy` launchd label, ports in site `registry/ports.yml`.
7. Relay ledger C6 + FUND-B lines.

## Exact task

Write `/Users/djbclark/ops/site-djbclark/docs/design/phase-d-adapter-design-notes.md`
covering, concretely enough that a mid-tier model can implement without
re-deciding:

1. **D1 adapter pattern** (this is the template D2–D5 clone): mode-selection
   order (site-map serverapps var → detect existing → own default), own/inject
   behavior split, exit-code contract (0/1/2 matching site-sync semantics),
   launchd namespace rule (`com.<site_ns>.<app>`), fragment dir layout under
   `generated/stayturgid/`, generated-header format, how the adapter wires
   into `sync_manifest.yml`, and the no-cutover rule (new label up before old
   label retired; rollback command documented).
2. **D6 projection design**: inventory→fragment projection rules and blast-
   radius limits (what a single inventory edit is allowed to rewrite; how
   drift/lockfile semantics contain it).
3. **D8 rollout order**: edge otelcol deploy sequence, one-device-first rule,
   offline-device handling, verify condition (device logs visible in
   OpenObserve after an offline/reconnect cycle).
4. **Deviation protocol**: implementers may deviate where the design proves
   awkward (relaxed bar), but every deviation gets a ledger note for M1-R to
   re-judge.

Do not gold-plate: decisions and rationale, not prose. Target ≤300 lines.

## Verification (self-verify; no human gate)

- Design doc exists, is Prettier-clean (`prettier --check`), ≤~300 lines,
  and covers all four sections above.
- No stayturgid working-tree changes (`git -C ~/ops/stayturgid status` clean).
- No production secrets or fleet-device contact.
- Design consumes existing `site_map.py` serverapp keys rather than defining
  new config surface.

## End of session

Follow PROTOCOL.md exactly (self-verified variant). Append a `D0-design`
ledger line. Rewrite `NEXT-PROMPT.md` as the **D1 implementation baton**:
carry over the D1 content from the execution-plan row and the C6/FUND-B
carry-forward gotchas (site justfile wrappers export STAYTURGID_SITE_DIR;
site-example deleted; registry paths.yml schema mismatch; uv-shebang lint;
Codex burn authorized then OpenRouter GPT-5.6 Sol fallback), point it at the
design notes as its spec, recommend **Grok 4.5 High (grok-web, 75% weekly)**
as primary quoted as a full catalog row (self-passoff applies if Grok is
already the runner), and route D1's end-of-session to the **R1 review baton**
(Fable 5 at **Medium** effort, **new second-Pro account**) per the checkpoint
table — R1's scope must also include the one-time gate-debt remediation
(funding-plans doc § Gate-debt remediation: re-run the mechanically checkable
C2–C6 checklist claims and record evidence). Commit/push
this repo, print the new baton in chat, and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
