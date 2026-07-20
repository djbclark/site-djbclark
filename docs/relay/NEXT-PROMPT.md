# NEXT: RESIDUAL-EF — E5 mini/VPS residual (difficulty 15/100)

**Funding plan context:** FUND-B Phase D, REVIEW-1, Phase E (E1–E5), Phase F
(F1–F4), and REVIEW-EF are all closed with zero must-fix findings
(`docs/relay/reviews/REVIEW-EF-findings.md`). Of the three original
operator-gated residuals: **F2 (brew-services) closed 2026-07-20** via
operator sign-off + mechanical execution (`docs/relay/LEDGER.md` row
`RESIDUAL-EF-F2`). **F3 (Immich) closed 2026-07-20 — but by full retirement,
not restoration:** the operator decided they no longer want Immich at all;
it was completely uninstalled (LaunchDaemons, `/opt/services/immich`,
`/var/log/immich`, the dedicated `immich` service user/group, the site
Ansible role/playbook/justfile recipes, and both registry claims), with a
dependency sweep confirming nothing else on the system was left orphaned
because of it (full detail: ledger row `IMMICH-RETIRE`). **Only E5 remains.**
This is **not** a further implementation step in the AI relay chain — it is
a light triage baton that checks whether `mac-mini-intel` or `vps-primary`
have come online, and executes the mechanical follow-through if so. If
neither has moved, the correct action is to say so and stop; do not invent
new work.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
quota snapshot taken 2026-07-20T16:55Z via `cswap list --json` +
`codexbar usage --format json --provider <name>` — **recheck live**, do not
trust this snapshot):

- **Primary —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — use **`cswap` account 2
  (djbclark@mit.edu)** (active; 5h **41%**, 7d **22%**, 7d reset Jul 25
  ~05:00 local). This is mechanical triage, not judgment — Sonnet 5 is
  correctly sized. **Note: Claude Fable 5 is no longer part of the monthly
  plan and is very expensive per-use — do not recommend it for the eventual
  project-level final review or anywhere else unless nothing else will
  work.** Prefer Sonnet 5 at `xhigh` effort or `/code-review ultra` for that
  step instead (see step2 §10, updated 2026-07-20). Original gmail account:
  5h **2%**, 7d **70%** (reset Jul 24 ~06:00) — fine as an alternate if the
  mit.edu account is busy.
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
- `docs/relay/reviews/REVIEW-EF-findings.md` (what was verified clean — do
  not re-review E1–F4)
- `docs/relay/LEDGER.md` (tail — `RESIDUAL-EF-F2` and `IMMICH-RETIRE` rows
  have the F2/F3 close-out detail; F3 is CLOSED, do not re-open)
- `docs/plans/site-djbclark-step2-junior-execution-plan-v1.md` §0 ground
  rules + §10 (final review is separate and may wait)

---

You are triaging **one specific, pre-existing operator-gated residual**: E5
(mini/VPS coming online). F2 and F3 are both closed — do not touch
`human/F2-BREW-SERVICES-DECISIONS.md` again, and do not attempt to restore
Immich (it was deliberately and fully removed by operator decision on
2026-07-20 — there is no `roles/immich`, `playbooks/immich.yml`, or
`human/F2`-style doc for it; if you find any reference to Immich anywhere
outside `docs/relay/` historical records, that's a bug, not a residual to
act on). Do not re-open REVIEW-EF's scope (E1–F4 code) — that review is
done and clean.

## E5 mini/VPS coming online

Check whether `mac-mini-intel` or `vps-primary` are reachable
(`tailscale status`, or try
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
- If you touched **nothing** (E5 still blocked), that is a valid, complete
  session — do not manufacture work.

## End of session

Follow `docs/relay/PROTOCOL.md`: append exactly one `RESIDUAL-EF` ledger row
recording whether E5 moved and what you did.
Rewrite `NEXT-PROMPT.md`:

- If you executed real work (E5 came online) → if it's now fully resolved,
  write the **project-level final review** baton (`/code-review ultra` per
  repo, or Sonnet 5 at `xhigh` effort reading step1 + step2 + every diff
  since the last whole-repo review — **not Fable 5**, no longer worth the
  cost per step2 §10 updated 2026-07-20) — there are no more residuals once
  E5 closes.
- If nothing moved (E5 still blocked) → re-issue this same `RESIDUAL-EF`
  baton essentially unchanged (fresh quota snapshot, same single check) —
  there is no reason to escalate model tier for a "nothing changed" triage.

Commit/push straight to master, print the new baton in chat, and copy it to
the clipboard:

```bash
pbcopy < docs/relay/NEXT-PROMPT.md
```
