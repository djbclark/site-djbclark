# site-djbclark

Private **site repo** for djbclark's machines (M1 MacBook Air, Intel Mac
mini, Linux VPSs) — the identity/allocation authority in a two-repo system
whose public product side is [stayturgid](https://github.com/djbclark/stayturgid).
Base layout: `~/ops/stayturgid` + `~/ops/site-djbclark` (permanent; see
stayturgid ADR 005).

| Where | What |
| --- | --- |
| `docs/relay/NEXT-PROMPT.md` | **Start here to continue the work** — the baton: which AI to use and the exact prompt to paste ([protocol](docs/relay/PROTOCOL.md), [ledger](docs/relay/LEDGER.md)) |
| `docs/plans/site-djbclark-step1-segmentation-architecture-v1.md` | Architecture + decision log (2026-07-18) |
| `docs/plans/site-djbclark-step2-junior-execution-plan-v1.md` | Phased execution plan: steps, difficulty, AI routing, risk register |
| `docs/plans/site-djbclark-step0-plan-v1.md` | Goose + LiteLLM AI-stack plan (see amendment header) |
| `registry/ports.yml`, `registry/paths.yml` | Port and path/namespace allocation authorities — check before adding either; lint with `bin/registry_lint.py` |

## LiteLLM proxy (Phase E1)

The site-owned LiteLLM proxy runs as `com.djbclark.litellm` on
`127.0.0.1:4000`. Apply it with `just litellm-apply`, dry-run it with
`just litellm-check`, and inspect it with `just litellm-status`.

Provider keys are optional until E4. Once a SecretSpec provider is configured,
inject them only for the apply process; the role writes them into the live
mode-0600 LaunchAgent and never into Git:

```bash
secretspec run --reason "apply LiteLLM provider keys" -- just litellm-apply
```

See `roles/litellm/README.md` for model routing, verification, and rollback.

## OliveTin user actions (unused on this site)

`stayturgid`'s D6 OliveTin projection (`control/site_contract/olivetin_projection.py`,
`USER_ACTIONS_RELATIVE`) merges an optional site-local action file into the
live OliveTin config alongside the product's own fragment:

- Product actions: `generated/stayturgid/fragments/olivetin/stayturgid_actions.yaml`
  (rendered by site-sync, `stayturgid_`-prefixed ids).
- Site actions (optional, **not present on this site**): `olivetin/user-actions.yaml`
  at this repo's root, never touched by the product, ids must be `user_`-prefixed.

To add a site-only OliveTin action (e.g. a djbclark-specific button not worth
upstreaming), create `olivetin/user-actions.yaml` here with `user_`-prefixed
action ids; the next `just site-sync apply` merges it into the live config.
No file exists yet because no such action has been needed (D6 residual,
M1-Q).

## Caddy route naming

The existing Phase D route scheme is the site convention: the public hostname
root serves the network landing page, while product UIs use stable lowercase
noun paths (`/dashboard/`, `/stats/`, `/opencode/`, and `/vlm/`). Internal
service health and observability ports remain loopback-only and do not receive
public route names. D7 adopts this scheme as-is; M1 may revisit the naming as an
architecture improvement without changing the current route contract.
