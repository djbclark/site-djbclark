# Hindsight Deployment for #92 — Phase 1/2 Matrix

Checked 2026-08-08. Workspace: `feature/hindsight-deployment-92`.

## Current truth

- Hermes built-in `MEMORY.md` / `USER.md`: still active.
- Hermes external provider: **not active**. The earlier setup attempt installed `hindsight-client>=0.6.1`, then cancelled before saving configuration.
- Hindsight service: installation in progress in isolated operational environment `~/.hindsight/venv`; no daemon started and no credentials written.
- Hermes source checkout has separate, unrelated local crash-loop protection changes; they are not part of this site-djbclark workspace and are preserved.

## Policy freeze

- Canonical truth remains git artifacts, ADRs, issues, handoffs, and session logs; Hindsight is a derived index.
- No Hindsight Cloud, new paid memory service, Docker, or required local LLM.
- Use one loopback Hindsight service shared by Hermes, Claude Code/Herdr, Codex, OpenCode, and other MCP clients.
- Keep built-in Hermes memory enabled until live rollback and cross-client tests pass.
- Disable automatic retain during initial admission testing; retain only compact approved facts after redaction, normalization, idempotency, provenance, and designated-writer checks.
- Suggested namespaces: `dan:global`, `dan:<project>`, `herdr:shared`, plus explicit agent/run metadata. Workers nominate; one owner/orchestrator commits shared memory.
- Credentials stay in safe OAuth/secretspec paths and never enter tracked files, issue comments, logs, or shell history.

## Official evidence checked

| Requirement | Evidence | Result / caveat |
|---|---|---|
| Bare-metal, no Docker | https://hindsight.vectorize.io/developer/installation#bare-metal-pip | Official pip path exists; macOS Apple Silicon supported; embedded pg0 is development-oriented. |
| Hindsight release | https://hindsight.vectorize.io/developer/models | Current docs are 0.9; package resolution selected `hindsight-all==0.9.0`. |
| Existing Codex subscription | https://hindsight.vectorize.io/developer/models#openai-codex-setup-chatgpt-pluspro | Official `openai-codex`; uses ChatGPT Plus/Pro OAuth, no OpenAI API billing; dedicated `CODEX_HOME` required for a long-lived service. |
| Existing Claude subscription | https://hindsight.vectorize.io/developer/models#claude-code-setup-claude-promax | Official `claude-code`; uses Claude Pro/Max via Agent SDK; docs explicitly restrict it to personal/local development and warn terms may change. Treat as compatibility/failover test, not production default. |
| Hermes | https://hindsight.vectorize.io/sdks/integrations/hermes | Current Hermes has a native provider; external-server mode is the correct shared-service shape. |
| Claude Code/agents | https://hindsight.vectorize.io/sdks/integrations/coding-agents | Current coding-agents integration supersedes legacy Claude-only plugin and supports shared per-repo banks across coding agents. |
| Embedded API | https://hindsight.vectorize.io/sdks/hindsight-all | `hindsight-all` / embedded APIs are available, but must not be installed into Hermes’ venv. |

## Package/install facts

- `hindsight-all==0.9.0` resolves 137 installs and would replace 4 packages in Hermes’ venv; that path is rejected.
- Dedicated install target: `~/.hindsight/venv`.
- Dedicated Codex OAuth file exists at `~/.hindsight/codex/auth.json` with mode 0600; contents were not read.
- No API key, OAuth token, or password was captured, copied, or written by this work.

## Live Results

- Package install: **PASS** — isolated Hindsight 0.9.0 environment.
- Server health: **PASS** — loopback `127.0.0.1:8888`, API 0.9.0, database connected.
- Synthetic retain/recall: **PASS** — CLI client stored and recalled a synthetic marker.
- Cross-client round-trip: **PASS (CLI + Python SDK)** — SDK writes were recalled through the shared API.
- Same-bank concurrency: **PASS** — 5/5 concurrent SDK writes succeeded.
- Provenance/source facts: **PASS** — document IDs, chunk IDs, context, metadata, and source-fact links returned.
- Private/shared isolation: **PASS** — private marker did not appear in shared-bank recall.
- Supersession: **PASS (replace semantics)** — updated same-document value recalled instead of baseline.
- Synthetic cleanup: **PASS** — all smoke-test banks deleted; bank list is empty.
- Hermes plugin external wiring: **PASS (isolated fixture)** — `local_external`, loopback URL, `auto_retain=false`, tools mode; active Hermes config unchanged.
- Hermes provider hook round-trip: **PASS** — actual `queue_prefetch()` → asynchronous recall → `prefetch()` returned the synthetic marker; test bank deleted.
- Hindsight service contract: **PASS (deployed)** — launchd-managed `com.djbclark.hindsight-api`, loopback `127.0.0.1:8888`, pinned venv, dedicated-auth gate, no `--replace`, 30-second throttle.
- Hindsight MCP: **PASS** — initialize + tools/list returned bank-scoped MCP server 0.9.0 with 29 tools.
- Claude Code MCP: **DEPLOYED/PASS** — user-scoped `hindsight-shared` endpoint connected.
- Codex MCP: **DEPLOYED** — global `hindsight-shared` URL registered; CLI reports local HTTP auth as unsupported, expected for open loopback endpoint.
- MCP → API cross-client round-trip: **PASS** — `sync_retain` via MCP, recall via API, document cleanup HTTP 200.
- Hermes ↔ Claude Code/Herdr round-trip: **PENDING** — Claude/Herdr hook adapter still needs implementation.
- Failure/retry and restore: **PASS** — Hindsight LaunchAgent booted out; Hermes provider returned empty safely; role restored healthy service.

## Acceptance gates

1. Synthetic secret/raw transcript rejection before retain.
2. Deterministic event IDs/content hashes make replay idempotent.
3. Same-bank concurrent writes preserve both facts and provenance. **PASS in initial probe.**
4. Hermes writes → fresh Claude/Herdr session recalls; Claude writes → fresh Hermes session recalls. **PENDING.**
5. Scope isolation across global/project/shared/agent/run namespaces. **Private/shared PASS; full namespace matrix pending.**
6. Hindsight outage does not make Hermes or Claude unusable. **PENDING.**
7. Export/restore into an empty instance and rebuild from canonical artifacts. **PENDING.**
8. Codex provider works with isolated `CODEX_HOME`; no pay-per-token fallback. **PASS for server startup and synthetic API use.**
9. Claude provider tested only within documented personal/local-development caveat. **PENDING.**
10. Resource/latency behavior measured on this Mac; versions pinned; rollback rehearsed. **Version pinned; measurements pending.**

## Next actions

1. Add non-secret operational Hindsight role/service contract to this task workspace.
2. Stage Hermes `local_external` configuration in an isolated config fixture; keep default provider unchanged.
3. Exercise Hermes plugin against the live endpoint, then test MCP and Claude Code/Herdr adapters.
4. Add outage, retry, export/restore, resource, and namespace-matrix probes.
5. Run repository tests, review, commit, open PR, and use the coordinated ops release path only after approval.

## Status

Phase 1: complete.
Phase 2 service + synthetic API gates: substantially complete.
Phase 2 client integration and operational deployment: in progress; no Hermes production provider change made.
