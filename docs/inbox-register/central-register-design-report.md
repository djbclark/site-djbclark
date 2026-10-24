STATUS: complete

# Design: one register for Telegram inbox destinations

Checklist: [x] recon (read-only) [x] design A–G [x] first steps. No files outside this report were changed.

## 0. What I found (this is what the plan rests on)

1. **The IDs are already public.** `chat_id=838808636` and `message_thread_id=44130` appear as literals in 4 workflows of the **public** `site-djbclark` repo, and `telegram:838808636:4413x` appears in public `site-djbclark/bin/{hermes-ping,fleet-watch,basic_memory_watchdog.py}`. The only secret is `TELEGRAM_BOT_TOKEN`, which stays a repo secret / secretspec item.
2. **There's already a convention to follow.** `site-djbclark/registry/{ports.yml,paths.yml}` is the site register. `bin/registry_lint.py` checks it in `just lint` and in CI. **stayturgid already reads it** through site discovery (`control/landing/discover.py:_resolve_site`, which uses `STAYTURGID_SITE_DIR` / `ANSIBLE_CONFIG`). That gives a sanctioned way for the product to read site data without importing site code.
3. **Live literals** (11 code sites):
   1. `site-djbclark/bin/hermes-ping:23` → 44130 (`HERMES_PING_TARGET` override). `site-private/bin/hermes-ping` and `~/.local/bin/hermes-ping` are symlinks to it.
   2. `site-djbclark/bin/fleet-watch:184` → 44130 (`FLEET_WATCH_TO` override). `site-private/bin/fleet-watch` is a symlink to it.
   3. `site-djbclark/bin/basic_memory_watchdog.py:38` → 44132.
   4. `roles/site_agents/files/hibernate-disk-check:31` → 44132 (`HERMES_TO` override). It is installed by `copy`, so it isn't a template today.
   5. `roles/site_agents/templates/jobber-notify.py.j2:81` → 44130.
   6. `stayturgid/control/lib/hermes_notify.py:20` → 44132. `fleet_health_monitor`, `access_monitor`, `adb_reconnect`, `usb_shizuku_heal`, `battery_watch` and others send through it.
   7. `stayturgid/control/bin/check_apk_updates.py:32` → 44130.
   8. `.github/workflows/monitor-herdr-extension-releases.yml:127,186`, `monitor-thaw-next-access-request.yml:162,231`, `nixos-lock-update.yml:208`, `track-issue-activity.yml:217-218`: seven inline `curl … sendMessage` blocks. Only `nixos-lock-update` and `track-issue-activity` run `actions/checkout` today.
   9. Tests pin literals: `stayturgid/tests/python/test_check_apk_updates.py` and `stayturgid/tests/test_firerpa_consent.py`.
4. **`~/.hermes/cron/jobs.json` has 37 jobs:**

   | `deliver` | Jobs |
   |---|---|
   | `telegram:838808636:44132` (Watch) | 21 |
   | `telegram:838808636:44134` (Digests) | 8 |
   | `telegram:838808636:44130` (Pings) | 1 |
   | `local` | 5 |
   | `origin` | 1 |
   | bare `telegram` | 1 |

   The Hermes CLI has a sanctioned writer: `hermes cron edit <id> --deliver <target>` (`hermes_cli/subcommands/cron.py:95-100`). Sync must use that and never write JSON while the gateway owns the file.
5. **`~/.hermes/config.yaml`** (read only) has `platforms.telegram.channel_overrides['44136']` and `extra.ignored_threads: [44130, 44132, 44134]`. The memory note `reference_hermes_send_transports.md` records that `hermes send --list telegram` has **no topic names**, so today nothing on the machine maps a name to an ID. The register fixes that.

## A. Where the register lives, and its schema

**DECIDED:** the canonical file is **`~/ops/site-djbclark/registry/telegram-inbox.toml`** (public). The reasons:

1. Every value is already public, so a private home buys no secrecy.
2. A private canonical file would force a generated public copy for GitHub Actions anyway, which is the same data plus a drift risk.
3. It reuses `registry/`, `registry_lint.py`, `just lint`, CI, and stayturgid's existing site discovery.

Veto point for the lead: if djbclark wants topic *purposes* kept private, move only the `purpose` strings to `site-private`. The IDs must stay readable by public CI.

**The register is a TOML file, but consumers never parse TOML.** A generated, committed **`registry/telegram-inbox.env`** sits beside it. It is POSIX `KEY=value` lines, so `sh` can source it, `$GITHUB_ENV` accepts it, Ansible reads it with `lookup('ansible.builtin.ini', KEY, type='properties', file=…)`, and Python parses it in 3 lines of stdlib on any version. That matters: launchd's `/usr/bin/python3` is 3.9 and has no `tomllib`. Only `bin/inbox-target` and the lint parse the TOML. The lint fails if the `.env` is stale.

```toml
# registry/telegram-inbox.toml — the ONE place a Telegram destination is written.
# Consumers read the generated registry/telegram-inbox.env (bin/inbox-target export).
schema_version = 1
default = "pings"                    # destination for unknown routes (non-strict resolve)

[chats.dan]
platform = "telegram"
chat_id = 838808636

# mode: "sink"  = outbound-only; MUST be in config.yaml extra.ignored_threads
#       "bound" = a live agent session; MUST be a config.yaml channel_overrides key
[destinations.pings]
chat = "dan"; thread_id = 44130; mode = "sink"; title = "Pings"
purpose = "agent task-done / needs-djbclark pings (hermes-ping)"
[destinations.watch]
chat = "dan"; thread_id = 44132; mode = "sink"; title = "Watch"
purpose = "watchdogs, monitors, health alerts"
[destinations.digests]
chat = "dan"; thread_id = 44134; mode = "sink"; title = "Digests"
purpose = "scheduled summaries"
[destinations.triage]
chat = "dan"; thread_id = 44136; mode = "bound"; title = "Triage"
bound_to = "goose-scout"             # must equal config.yaml channel_overrides['44136'] binding
purpose = "paste-in triage; the only bound topic"

# Retired IDs: any sender, cron job or config entry naming one is a lint/check failure.
[retired]
22158 = { was = "Inbox", retired = "2026-10-23", split_into = ["pings","watch","digests","triage"] }

# Routes: sender key -> destination. Senders ask for THEIR key, never a destination,
# so splitting a topic later is a route edit here, not a sender edit.
[routes]
"hermes-ping"                 = "pings"
"fleet-watch"                 = "pings"
"basic-memory-watchdog"       = "watch"
"hibernate-disk-check"        = "watch"
"jobber-notify"               = "pings"
"stayturgid.control"          = "watch"     # hermes_notify.py (all control monitors)
"stayturgid.apk-updates"      = "pings"
"gha.herdr-extension-releases" = "pings"
"gha.thaw-next-access-request" = "pings"
"gha.nixos-lock-update"       = "pings"
"gha.track-issue-activity"    = "pings"

# Cron: job id -> destination (comment = job name). Seeded from jobs.json as it is today.
[cron.routes]
"58601d6dc480" = "watch"   # Memory Size Watchdog
# … one row per telegram-delivering job (30 rows) …

[cron]
# Jobs whose deliver is not a register destination, each listed on purpose.
unmanaged = { "<id>" = "local", "<id>" = "origin" }   # 5 local + 1 origin
# The bare `telegram` job (home channel) gets a decision in step F4: give it a route or list it here.

[config_yaml]
extra_ignored_threads = []    # threads config.yaml may ignore that aren't register sinks (should stay empty)
```

The TOML above shows inline tables and `;` for brevity. The real file uses normal multi-line tables, because TOML forbids `;`.

**Generated `.env` contract** (fixed now, so slices S2–S4 can code against it in parallel):

```
# GENERATED by bin/inbox-target export from registry/telegram-inbox.toml — do not edit
INBOX_SCHEMA=1
INBOX_CHAT_ID=838808636
INBOX_DEFAULT=telegram:838808636:44130
INBOX_DEST_PINGS=telegram:838808636:44130
INBOX_DEST_PINGS_THREAD=44130
…  (one _DEST_<NAME> / _THREAD pair per destination)
INBOX_ROUTE_HERMES_PING=telegram:838808636:44130
INBOX_ROUTE_HERMES_PING_CHAT=838808636
INBOX_ROUTE_HERMES_PING_THREAD=44130
…  (one triple per [routes] key; key upper-cased, [.-] -> _)
```

Cron routes are not exported, because only `inbox-check` reads them. Lines are sorted, unquoted, and contain no spaces, so the `properties`, `sh` and `$GITHUB_ENV` parsers all agree.

## B. One read path, one helper

**`site-djbclark/bin/inbox-target`** is a `uv run --script` Python ≥3.11 stdlib program, written the same way as `registry_lint.py`. It is never on the send hot path.

| Command | Output / effect |
|---|---|
| `inbox-target <route-or-destination>` | `telegram:<chat>:<thread>`. It looks in `[routes]` first, then `[destinations]`. An unknown name prints `INBOX_DEFAULT`, warns on stderr and exits 0, because a ping must not be lost. `--strict` makes it exit 1. |
| `inbox-target --field thread\|chat <name>` | The bare number, for curl. |
| `inbox-target export [--check]` | Writes `registry/telegram-inbox.env`. `--check` exits 1 if the file is stale. |
| `inbox-target list` | A table of name, thread, mode, purpose and routes. It replaces "you must be given the numeric ID" in the memory note. |

**How each kind of consumer reads it:**

1. **Shell senders** (`hermes-ping`, `fleet-watch`, `hibernate-disk-check`) source the env file and keep their existing override variable. In `hermes-ping`, for example:
   ```sh
   . "${INBOX_ENV:-$(dirname "$(realpath "$0")")/../registry/telegram-inbox.env}"
   target="${HERMES_PING_TARGET:-$INBOX_ROUTE_HERMES_PING}"
   ```
   `hibernate-disk-check` is a deployed copy. Its plist template sets `INBOX_ENV={{ site checkout }}/registry/telegram-inbox.env`, and the script reads the file at runtime, so a reorg needs no redeploy.
2. **Site Python** (`basic_memory_watchdog.py`, `jobber-notify.py.j2`) reads the env with a 3-line parser and takes `INBOX_ROUTE_<KEY>`. Only the env file's path is templated into `jobber-notify`, not the target.
3. **stayturgid** (`control/lib/hermes_notify.py`) resolves the site directory with the existing product discovery, reads `<site>/registry/telegram-inbox.env`, and takes the route key named by its caller. It adds `notify(..., route="stayturgid.control")`, and `check_apk_updates` passes `route="stayturgid.apk-updates"` instead of keeping its own constant. The product must still work standalone, so it keeps **one** `FALLBACK_TARGET` constant, used only when site discovery or the file fails, and it logs a warning when that happens. `inbox-check` (section E) asserts that the fallback equals the register's route, so even the fallback can't drift silently.
4. **`eval "$(inbox-target export --shell)"`** exists for interactive use only. Senders source the committed file, so sending never needs `uv`.

## C. GitHub Actions

**Recommendation: option (a) without the generation hop.** The register is in the same repo, so the workflows read the committed `.env` directly.

1. Add a local composite action, **`.github/actions/inbox-send/action.yml`**:
   1. Inputs: `route`, `text`, `bot-token`.
   2. It reads `registry/telegram-inbox.env`, takes `INBOX_ROUTE_<ROUTE>_CHAT` / `_THREAD`, and runs the existing `curl --data-urlencode` plus the `jq -e '.ok'` check.
   3. A missing route key fails the step, so the problem stays visible.
   4. This collapses the 7 duplicated curl blocks into one.
2. In each workflow job that sends, add `actions/checkout` pinned to the SHA already used in `nixos-lock-update.yml`, with `sparse-checkout: |\n registry/telegram-inbox.env\n .github/actions/inbox-send`, `sparse-checkout-cone-mode: false`, `persist-credentials: false`. Then `uses: ./.github/actions/inbox-send` with `route: gha.<workflow>`. Jobs that already check out the whole repo skip the sparse step.
3. Rejected options:
   1. (b) per-thread repo secrets: invisible drift, a `gh secret set` on every reorg, and the lint can't check them.
   2. (c) dispatching to a remote action: a new moving part.
4. **Propagation:** a reorg reaches CI the moment the TOML+env commit is pushed. There is no secret rotation step.

## D. Cron (`jobs.json`)

**`site-djbclark/bin/inbox-check`** (separate executable, `uv` script, `pyyaml`) runs on the host only:

1. `inbox-check cron` does a read-only diff. For each job with a `telegram:`-prefixed or bare `telegram` deliver, it compares the job with the register:
   1. **Fail** if the job id is missing from `[cron.routes]` and `[cron] unmanaged`. That catches a new job added without registering it.
   2. **Fail** if the thread is retired or isn't a destination.
   3. **Fail** if deliver ≠ the route's target.
   4. **Fail** if a routed id no longer exists (stale row).
   5. `local` and `origin` must appear in `unmanaged`.
2. `inbox-check cron --apply`:
   1. First snapshot `{id: deliver}` to `~/.local/state/telegram-inbox/cron-deliver-<UTC>.json`. That is the rollback.
   2. Then run `hermes cron edit <id> --deliver <target>` for each mismatch only, through the CLI, never as a JSON write.
   3. Then re-read and assert zero diff.
   4. `--rollback <snapshot>` replays the snapshot the same way.
3. **Not at schedule time.** Changing the Hermes scheduler to read the register would patch the hermes-agent checkout, which is a harness fork. A sync plus a periodic check gives the same guarantee for one small file.
4. **No silent desync:** `fleet-watch`, which is already periodic, calls `inbox-check all --quiet` and pings `INBOX_ROUTE_FLEET_WATCH` on a state change only (its existing gating). Every job's validity is judged against the same `mode`/`thread` data that section E checks against `config.yaml`, so cron and config can't disagree without one check failing.

## E. Invariant with `~/.hermes/config.yaml`

The register is the source of truth. `config.yaml` topic state is derived, and the operator applies it by hand or with `hermes config set`. Agents never write it.

`inbox-check config` (read-only) holds these as **set equalities** and exits 1 on any failure:

1. `{str(d.thread_id) for d in destinations if d.mode=="bound"}` == `set(platforms.telegram.channel_overrides.keys())` (restricted to the register's chat).
2. For each bound destination, the override's agent/profile == `bound_to`. The exact YAML path is read from the live file once while building S5. Today it's the triage → goose-scout binding.
3. `{d.thread_id for d in destinations if d.mode=="sink"}` ∪ `[config_yaml].extra_ignored_threads` == `set(platforms.telegram.extra.ignored_threads)`.
4. No sink thread is also a `channel_overrides` key, and no bound thread is ignored.
5. No retired thread (22158) appears anywhere in `config.yaml`.

On divergence it prints the **desired YAML fragment** and the operator command to apply it, then exits 1. It never edits. The same subcommand also runs:

1. `inbox-check stayturgid`: the `hermes_notify.py` `FALLBACK_TARGET` equals the `stayturgid.control` route. The file is found via `STAYTURGID_ROOT`, like the justfile.
2. `inbox-check all` = config + cron + stayturgid. The `just inbox-check` recipe runs it.

**CI-safe half, in `registry_lint.py`** (runs in `just lint` and CI, with no `~/.hermes` needed):

1. The TOML schema is valid. Every route and cron route names a real destination. Thread IDs are unique. `default` exists. `bound` has `bound_to`.
2. `inbox-target export --check` passes.
3. **Literal-ID guard:** `rg` for `838808636`, `\b4413[0-9]\b` and `\b22158\b` across `bin/ roles/ .github/` excluding `registry/`. It reports in warn-only mode during migration and becomes a hard failure at step F7.

## F. Migration order, with no lost send

Each step is one commit per sender class, behavior-identical: every resolved target equals today's literal. The rollback for any step is `git revert` of that commit, plus a role redeploy where a deployed copy changed.

1. **F0. Land the register** (S1): add the TOML, generated `.env`, `bin/inbox-target`, the lint extension (warn-only literal guard), tests and `just inbox-sync` / `inbox-check` recipes. This is purely additive, and nothing reads it yet. Gate: `inbox-target <every route>` == the current literal for that sender (a table test).
2. **F1. Site senders** (S2): `hermes-ping`, `fleet-watch`, `basic_memory_watchdog.py`, `hibernate-disk-check` (and its plist `INBOX_ENV`), and the `jobber-notify.py.j2` env path. Existing tests (`test_basic_memory_watchdog.py`, `test_fleet_watch_*.py`) assert the resolved argv with a fixture env file. Smoke test: one real `hermes-ping "site-djbclark: inbox register F1 smoke"` that lands in Pings. Redeploy `site_agents`.
3. **F2. stayturgid** (S3): route-aware `hermes_notify`, `check_apk_updates` and the two pinned tests. They resolve from a fixture site directory and test the fallback separately.
4. **F3. GHA** (S4): the composite action. Convert `track-issue-activity` first (it already checks out), run it via `workflow_dispatch` (or a no-op path) to Pings, then convert the other 3.
5. **F4. Cron** (S5): seed `[cron.routes]` from the current `jobs.json`, so `inbox-check cron` shows zero diff and `--apply` is a no-op. Decide the bare `telegram` job: route it or mark it unmanaged.
6. **F5. Config invariant** (S5): `inbox-check config` passes against the current `config.yaml` (it already matches). Wire `inbox-check all --quiet` into `fleet-watch`.
7. **F6. Docs** (S6): point every doc that names a topic at `inbox-target list`, and keep the lessons (no guessed IDs, Triage is bound) as prose:
   1. `~/.hermes/skills/ops/agent-notifications/SKILL.md` and its references.
   2. `hermes-messaging/` (including `topic-migration-recipe.md`, rewritten as the reorg procedure below).
   3. `ops-scheduling/SKILL.md`.
   4. `site-private/memory/{feedback_ping_telegram_and_chat.md, reference_hermes_send_transports.md}`.
8. **F7. Flip the literal-ID guard to a hard failure.** It is a one-line change by the S1 owner.

**The reorg procedure after migration** (a one-file edit plus two commands):

1. Create the topic in Telegram.
2. Edit the TOML.
3. Run `just inbox-sync` (export, lint, commit, push), so CI picks it up.
4. A **new sink or bound topic gets its `config.yaml` change before any route points at it.** `inbox-check config` prints the change; the operator applies it.
5. Run `inbox-check cron --apply`.

Shell, Python and stayturgid senders follow on their next run, because they read the file at runtime.

## G. Who implements what

All slices work in place on `master` of `~/ops/*` (home rule 21). They don't use worktrees, they own disjoint files, and each commits with `git commit -m MSG -- <its paths>`. The contract (TOML schema, `.env` key names) is fixed in sections A and B above, so S2–S4 can start in parallel with S1 and test against S1's pushed `.env`. Before each batch, `route_agent.py plan` picks the actual pool for each kind below. The pools named are the policy default.

| Slice | Repo and files owned (exclusive) | Kind → recommended | Depends on |
|---|---|---|---|
| **S1 register core** | site-djbclark: `registry/telegram-inbox.{toml,env}`, `bin/inbox-target`, `bin/registry_lint.py` (inbox part), `tests/test_inbox_target.py`, `tests/test_registry_lint.py` (inbox cases), `justfile` (`inbox-sync`, `inbox-check` recipes) | `code` → claude **Sonnet 5.5** | none |
| **S2 site senders** | site-djbclark: `bin/hermes-ping`, `bin/fleet-watch` (target lines only), `bin/basic_memory_watchdog.py`, `roles/site_agents/files/hibernate-disk-check`, `roles/site_agents/templates/{jobber-notify.py.j2, hibernate-disk-check.plist.j2}`, the role defaults var for the env path, `tests/test_basic_memory_watchdog.py`, `tests/test_fleet_watch_*.py` | `code` → `omp` `anthropic/claude-sonnet-5-5` (credits tier) | S1's `.env` pushed, for its tests |
| **S3 stayturgid** | stayturgid: `control/lib/hermes_notify.py`, `control/bin/check_apk_updates.py`, `tests/python/test_check_apk_updates.py`, `tests/test_firerpa_consent.py` | `code` → claude Sonnet 5.5 (product repo: keep quality high) | contract only |
| **S4 GHA** | site-djbclark: `.github/actions/inbox-send/action.yml`, the 4 workflow files | `github`/`code` → a cheap code pool from `route_agent.py plan`. Copilot only if ≥60% left, since it is the reserve and this is exactly its "one small GitHub slice" | S1's `.env` pushed |
| **S5 host checks** | site-djbclark: `bin/inbox-check`, `tests/test_inbox_check.py`, the TOML's `[cron]` / `[config_yaml]` seed rows (handed to S1 as a patch, or done after S1 lands), then the `fleet-watch` `inbox-check` call | `code` → claude Sonnet 5.5 | S1 landed; S2 landed (both touch `fleet-watch`) |
| **S6 docs sweep** | the `~/.hermes/skills/{ops,hermes}/…` files and the 2 `site-private/memory` notes listed in F6 | `mechanical` → cheapest eligible pool | S2–S5 |
| **R review** | read-only: S1 and S5 (schema, invariants, cron apply/rollback). Before S4 lands, an `adversary` security review of the bot-token handling in the composite action (rule 28) | `judgment` → **Opus high**; `adversary` as the bigteam names it | after S1/S5 and S4 |
| **Operator** | `~/.hermes/config.yaml`: nothing to change today (it already matches). Future changes: apply what `inbox-check config` prints | human | none |

**Collision notes:**

1. `fleet-watch` is touched by S2 (target line) and S5 (check call). S5 runs strictly after S2.
2. The TOML is S1's. S5 sends its seed rows to S1 through `relay.py`, or edits after S1's commit lands. It never edits concurrently.
3. Tests run only through `~/ops/site-private/bin/bg`, one at a time, per the delivery contract.

## First steps, in order

1. Dispatch **S1** (`acp-dispatch claude --kind code --model sonnet-5.5 …`) with sections A, B and E-lint as its brief. At the same time dispatch **S3** (contract only).
2. When S1 pushes, dispatch **S2** and **S4** in parallel.
3. Then **S5**: seed the cron routes, confirm zero diff, wire it into `fleet-watch`.
4. Then **R** (Opus review plus adversary on S4), then **S6**, then flip the literal guard to a hard failure (F7).
5. Ping when the chain completes: `hermes-ping "site-djbclark: telegram inbox register live"`.

DECIDED:
1. The register is public, in `site-djbclark/registry/`. The IDs are already public, and it reuses the existing registry, lint and stayturgid-discovery path.
2. Consumers read a generated, committed `.env`, not the TOML. That keeps `uv` and `tomllib` off the send path and gives one format for sh, GHA and Ansible.
3. Cron is synced through `hermes cron edit` with a snapshot rollback, not by patching the Hermes scheduler.
4. stayturgid keeps a single fallback constant for running standalone, and the site check verifies it.
5. GHA uses a composite action reading the committed `.env`, not secrets.

DONE
