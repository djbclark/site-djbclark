# NEXT: E1 — LiteLLM role (Phase E AI stack) (difficulty 50/100)

**Funding plan context:** FUND-B revised Phase D recovery is done (M1-R → M1-F
→ M1-Q → R3 closed Phase D). D9 just closed the last step2-plan §5 box that
FUND-B never scheduled. **Phase E begins** per step2 plan §6.

**Recommended AI** (full rows from `docs/reference/available-ai-models.md`;
recheck quotas with `codexbar usage --format json --provider all` to a file in
the background before starting — never pipe through `head`):

- **Primary —** Grok 0.2.103 (TUI) · xAI / SpaceXAI · Grok 4.5 · `grok-4.5` ·
  Low, Medium, High (default High) · _Flagship for code + agentic work_ —
  effort **High** (role + config + live verify; step2 row's "Codex (high)" is
  preferred once weekly resets ~Jul 25 — until then Grok is the working
  flagship). Self-passoff from D9 is fine.
- **Alternate —** Claude 2.1.205 (Mac GUI) · Anthropic · Claude Sonnet 5 ·
  `claude-sonnet-5` · Adaptive Thinking + Effort (default High on Claude
  Code/API) · _Default for most plans_ — **original account**, High.
- **Escalation / preferred after reset —** Codex 0.144.6 (oauth) · OpenAI ·
  GPT-5.6 Sol · `gpt-5.6-sol` · Light, Medium, High, Extra High, Max, Ultra ·
  _Flagship; complex coding, computer use, research, cybersecurity_ — **High**,
  **prefer after the ~Jul 25 weekly reset** (step2 plan's named pick for E1).

**Working dir:** `/Users/djbclark/ops/site-djbclark` (LiteLLM is a **site**
role under `roles/`, not stayturgid). stayturgid only if you need the
homebrew-prefix / launchd patterns as reference. `git fetch origin --prune &&
git pull --ff-only origin master` in both before starting. Required reading:
`docs/relay/PROTOCOL.md`, step2 plan §0 ground rules + §2 risk register + §6
E1 row (`docs/plans/site-djbclark-step2-junior-execution-plan-v1.md`), and
step0 AI-stack design as amended (header note + risk register in step2).

---

You are running **E1 — `roles/litellm`** per the step2 plan §6:

> `roles/litellm`: uv tool install (pin ≥1.94), config template (Auto Router
> v2 syntax verified against **live docs**, not memory),
> `com.djbclark.litellm` plist, secretspec entries, port 4000.

## Task

1. Implement `roles/litellm` in the site repo: uv tool install with pinned
   LiteLLM ≥1.94, config template, launchd plist label `com.djbclark.litellm`,
   secretspec entries for provider keys (no secrets in git), registry port
   **4000**.
2. **Verify Auto Router v2 syntax against current LiteLLM docs** (fetch live
   docs; do not invent router YAML from memory).
3. Wire into site inventory / just recipes as the existing serverapp / role
   patterns do (mirror Grafana/OliveTin adapter style only where it fits —
   LiteLLM is site-owned, not a stayturgid product fragment).
4. Self-verify (FUND-B: no human gate):
   - `curl -sS http://127.0.0.1:4000/v1/models` succeeds when the service is up
   - A SIMPLE and a REASONING prompt route to **different** tiers (check
     LiteLLM logs for model selection evidence)
   - `bin/registry_lint.py` clean; port 4000 claimed in `registry/ports.yml`
   - secretspec resolves; no world-readable secret files (0600)
   - rollback path noted in the ledger (bootout new label; leave any prior
     path intact until a later session)

## Constraints

- Small, focused PR/commit scope: LiteLLM role + registry + secretspec +
  docs checklist stubs only. Do not start E2 (Goose) in this session.
- Never commit API keys. Operator key entry is E4's human checklist; E1
  should leave secretspec keys defined and empty/placeholder-safe.
- Site repo: straight to master. stayturgid: branch+PR only if you truly need
  a product change (you should not for E1).

## Carry-forward (not E1 work unless free)

- **Next project code review MUST cover (2026-07-19 fleet batch):** stayturgid#29 (sticky a11y detect, catastrophic-alert 2h window, Fire OS skip-catastrophic); AutoJs6#1 sticky rebind + debug17 LeakCanary-off; ASCII-only on-device path policy and retirement of `/sdcard/脚本/stayturgid` + `/sdcard/Scripts/stayturgid` mirrors (p7a SyntaxError Invalid quantifier). Do not drop these from the review scope.

- **OPERATOR decision still open — D7 route scheme (§11 #9):** Caddy route
  naming + whether grafana/OO/olivetin get front-door routes. Forwarded since
  D7 through R3; still operator-owned. If decided mid-session, record
  accepted-as-is or queue a tiny baton — do not expand E1 into Caddy work.
- **D9 fleet notes:** s24/p7a dual-write code is deployed (repair+log.js match
  master); AutoJs6 watchdog still not cycling on s24/p7a (device-ops). p7a
  still has a11y/bootloop flags in fleet-health. hd8 otelcol disabled
  (pending-incompatible-runtime). `deploy-termux` hits a pre-existing CFEngine
  `cf-serverd.cf` Jinja template parse error — owner stayturgid termux_userland
  (deferred from D9).
- Verification baseline at D9 close: stayturgid `node tests/js/log.test.js`
  24/24; dual-write live on all three devices for **repair**; full `just test`
  was 497 passed / 1 skipped at M1-Q/R3 (re-run if you touch stayturgid).

## End of session

Per `docs/relay/PROTOCOL.md`: self-verify with recorded evidence, one `E1`
ledger line, rewrite `NEXT-PROMPT.md` for **E2** (Goose), commit/push (site
straight to master; stayturgid only if needed, then merge PR same-session and
end on pulled master), print the new baton in chat and
`pbcopy < docs/relay/NEXT-PROMPT.md`.
