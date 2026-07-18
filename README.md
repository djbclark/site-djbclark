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
