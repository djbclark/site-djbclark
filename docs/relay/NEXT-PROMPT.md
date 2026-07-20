# NEXT: RESIDUAL-EF — operator-gated residuals from Phase E/F (difficulty 25/100)

**Funding plan context:** FUND-B Phase D, REVIEW-1, Phase E (E1–E5), Phase F
(F1–F4), and REVIEW-EF are all closed with zero must-fix findings
(`docs/relay/reviews/REVIEW-EF-findings.md`). This is **not** a further
implementation step in the AI relay chain — it is a light triage baton that
checks whether any of the three known operator-gated residuals have been
unblocked, and executes the mechanical follow-through if so. If none have
moved, the correct action is to say so and stop; do not invent new work.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
quota snapshot taken 2026-07-20T15:59Z via `cswap list --json` +
`codexbar usage --format json --provider <name>` — **recheck live**, do not
trust this snapshot):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — use **`cswap` account 2
  (djbclark@mit.edu)** (active; 5h **29%**, 7d **21%**, 7d reset Jul 25
  ~05:00 local). This is mechanical triage, not judgment — Sonnet 5 is
  correctly sized; save Fable 5 for the eventual project-level final
  review. Original gmail account: 5h **2%**, 7d **70%** (reset Jul 24
  ~06:00) — fine as an alternate if the mit.edu account is busy.
- **Alternate —** Grok 0.2.106 (TUI) · xAI / SpaceXAI · Grok 4.5 ·
  `grok-4.5` · Low, Medium, High (default High) · _Flagship for code +
  agentic work_ — SuperGrok weekly **71%** used, reset Jul 23 ~2:41am ET
  (`2026-07-23T06:41:20Z`).
- **Escalation —** Cursor (GUI) · Cursor · Composer 2.5 · Composer 2.5 ·
  Agent Thinking · _Native agentic coding_ — Cursor Pro primary pool
  ~**59%** monthly used (secondary ~52%, tertiary 100%); provider cost
  $1.47/$2; resets Aug 2 ~7:22pm. **Codex 0.144.6 (oauth) · GPT-5.6 Sol ·
  weekly 100% used until Jul 25 ~5:17pm ET — avoid.**

**Quota-check procedure (carry forward verbatim in substance):**

- CodexBar does **not** hang; it can take a long time to reply. Give every
  invocation a hard **two-minute timeout**. Query relevant non-Claude
  providers separately, background output to files, and never pipe it
  through `head`, e.g.:
  `timeout 120 codexbar usage --format json --provider grok > /tmp/grok-usage.json`.
- **Ignore everything CodexBar says about Claude.** Two Claude accounts are
  managed by `cswap`; use **`cswap list --json`** as the authority for both
  accounts' usage and name the selected account in any recommendation.
- Recheck live rather than trusting this snapshot.

**Working dir:** `/Users/djbclark/ops/site-djbclark`

```bash
cd /Users/djbclark/ops/site-djbclark
git fetch origin --prune
git pull --ff-only origin master
```

Required reading:

- `docs/relay/PROTOCOL.md`
- `docs/relay/reviews/REVIEW-EF-findings.md` (what was just verified clean —
  do not re-review E1–F4, only check the three residuals below)
- `docs/relay/LEDGER.md` (tail — F2/F3/E5/REVIEW-EF rows)
- `human/F2-BREW-SERVICES-DECISIONS.md`
- `docs/relay/audits/F3-immich-adoption.md`
- `docs/plans/site-djbclark-step2-junior-execution-plan-v1.md` §0 ground
  rules + §10 (final review is separate and may wait)

---

You are triaging **three specific, pre-existing operator-gated residuals**.
For each: check whether it has moved; if yes, do the mechanical
follow-through; if no, leave it alone and say so in the ledger note. Do not
re-open REVIEW-EF's scope (E1–F4 code) — that review is done and clean.

## 1. F2 brew-services keep/kill sign-off

Check `human/F2-BREW-SERVICES-DECISIONS.md` — all 9 rows were blank as of
REVIEW-EF. If the operator has filled in any "Operator decision" cells:

- For each **Accept**ed or **Override**n row, execute exactly the command(s)
  the row calls for (the audit doc
  `docs/relay/audits/F2-brew-services-audit.md` has the suggested commands
  for the default recommendations; an Override may need a different
  command — use judgment, but never touch a service whose row is still
  blank).
- Re-run `brew services list` before/after each change; update
  `registry/paths.yml` `brew_services` claims and `registry/ports.yml` to
  match the new live state (e.g. drop the `redis` port claim if
  stopped+uninstalled); `bin/registry_lint.py` after every registry edit.
- If **all** rows are still blank, do nothing here — note it in the ledger
  and move on.

## 2. F3 Immich app restore

Check `test -d /opt/services/immich/app` (or re-run `just immich-status`).
If the app tree is now present (restored out-of-band by the operator/native
installer):

- `just immich-apply-sudo` (GUI askpass; needs `become`/root for the
  system-domain LaunchDaemons).
- Verify: both `com.immich*` labels bootstrap+enable, `just immich-status`
  shows them running, `curl -fsS http://127.0.0.1:3001/api/server/ping`
  succeeds, `registry/ports.yml` 3001/3002/3003 flip `status: planned` →
  `active`.
- If the app tree is still absent, do nothing — note it and move on.

## 3. E5 mini/VPS coming online

Check whether `mac-mini-intel` or `vps-primary` are reachable
(`ping`/`tailscale status`, or just try
`ANSIBLE_CONFIG=$PWD/ansible.cfg ansible -i inventory/hosts.yml <host> -m ping`).
If either is now reachable:

- Flip `site_host_status: online` for that host in `inventory/hosts.yml`
  and fill in the real `ansible_host` (Tailscale IP/MagicDNS).
- `just litellm-apply-secrets -- --limit <host>` (or `LITELLM_HOSTS=<host>
  just litellm-apply-secrets`), verify `/v1/models` 200 on that host, and
  flip its `registry/ports.yml` port-4000 row `status: planned` → `active`.
- If both hosts are still offline, do nothing — note it and move on.

## Self-verification checklist (record evidence for whatever you touched)

- `bin/registry_lint.py` clean after any registry edit.
- Any daemon you started/changed: health-curl + `launchctl print` evidence.
- `git status` clean at session end; nothing left half-applied.
- If you touched **nothing** (all three residuals still blocked), that is a
  valid, complete session — do not manufacture work.

## End of session

Follow `docs/relay/PROTOCOL.md`: append exactly one `RESIDUAL-EF` ledger row
recording which of the three residuals (if any) moved and what you did.
Rewrite `NEXT-PROMPT.md`:

- If you executed real work (any of the three) → same `RESIDUAL-EF` shape
  for whatever's still outstanding, OR if all three are now fully resolved,
  write the **project-level final review** baton (Fable 5 Max, or
  `/code-review ultra` per repo, reading step1 + step2 + every diff since
  the last whole-repo review) per step2 §10.
- If nothing moved (all three still blocked) → re-issue this same
  `RESIDUAL-EF` baton essentially unchanged (fresh quota snapshot, same
  three checks) — there is no reason to escalate model tier for a "nothing
  changed" triage.

Commit/push straight to master, print the new baton in chat, and copy it to
the clipboard:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
