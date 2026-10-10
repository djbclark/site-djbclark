# Migrating herdr-orchestration to @chankov/agent-fleet: assessment

- **Issue:** [#37](https://github.com/djbclark/site-djbclark/issues/37)
- **Date:** 2026-10-09 (package and repo facts checked live that day)
- **Scope:** assessment only. No skill, config or install changes were made.
- **Recommendation:** **do not migrate.** Keep `herdr-orchestration` as the
  orchestration layer, keep #37 deferred as
  [#139](https://github.com/djbclark/site-djbclark/issues/139) already decided,
  and borrow two ideas into the existing tools (section 5). If the operator
  still wants first-hand evidence, run the time-boxed spike in section 6.

## 1. Re-run of the maturity check (issue task 9)

| Signal              | When #37 was filed (2026-07-28) | Now (2026-10-09)                                                   |
| ------------------- | ------------------------------- | ------------------------------------------------------------------ |
| Latest version      | 0.0.8                           | **2.0.19** (2026-10-07)                                            |
| Releases            | 8 in 11 days                    | **36 in 12 weeks**                                                 |
| Major versions      | pre-1.0                         | 1.0.0 on 2026-08-07, 2.0.0 on 2026-08-31                            |
| npm maintainers     | 1 (`chankov`)                   | 1 (`chankov`)                                                      |
| GitHub stars, forks | 4, 0                            | 19, 3                                                              |
| Runtime deps        |                                 | `yaml`, `pi-ask-user`, `@modelcontextprotocol/sdk`; Node 18+; MIT   |

It is now post-1.0 under semver, but it is still a single-maintainer project
shipping roughly three releases a week, with two major versions in its first
seven weeks and at least one feature (`codex-remote`) already retired. The
issue's own condition for proceeding ("if the package is still pre-1.0 and
single-maintainer... re-confirm") is half met: the version number moved, the
bus factor did not.

For comparison, the alternatives from the 2026-07-29 comment have grown too:

| Project                                                         | Stars | Forks | Last push  | Licence                    |
| --------------------------------------------------------------- | ----- | ----- | ---------- | -------------------------- |
| [herdr-remote](https://github.com/dcolinmorgan/herdr-remote)    | 411   | 77    | 2026-10-08 | not detected by GitHub     |
| [CCGram](https://github.com/alexei-led/ccgram)                  | 277   | 85    | 2026-10-08 | MIT                        |
| [TelClaude](https://github.com/avivsinai/telclaude)             | 5     | 0     | 2026-10-08 | MIT                        |

herdr-remote's licence must be read by hand before any use: GitHub reports
it as unrecognised.

## 2. What agent-fleet is today

From its README at 2.0.19:

1. **One coding agent: pi.** Everything installs for the pi agent and nothing
   else. Claude Code appears only as a *coms peer*: a Claude pane bridged in to
   answer questions and do cross-model review. It is not an install target.
2. **agent-hub** is the dispatcher, a pi runtime with an *operator* mode and an
   *orchestrator* mode. Orchestrator mode removes `bash`/`edit`/`write` and
   drives specialist sub-agents under a **Verification Contract**: a ledger of
   acceptance assertions kept on disk.
3. **Research stays out of the dispatcher's context.** Specialists emit
   `NEEDS_RESEARCH:` lines, read-only helpers write findings to disk, and the
   hub sees file paths.
4. **Herdr** is the workspace control plane (tiled peer panes, snapshot and
   resume). **coms** is a peer messaging plane between pi and Claude panes.
5. **Hermes** gets two pieces: a Desktop panel plugin (sessions, who is blocked,
   live activity; needs Hermes 0.19+ and a gateway restart) and a Telegram
   relay for pi's `ask_user` questions. The relay runs as a Herdr pane, needs
   Agent Fleet's `hub-liaison` skill in the Hermes profile, and needs Hermes's
   `terminal` and `file` toolsets enabled for the Telegram platform.
6. **Install is per repository.** `npx @chankov/agent-fleet setup` writes
   `.pi/`, `.ai/agent-fleet.json` and a managed justfile region into the target
   repo. Re-running setup "reconciles toward the package": an edited shipped
   artifact is overwritten without a prompt.
7. It ships 29 to 30 lifecycle skills and 15 personas, part of them vendored
   from an upstream skills project.

## 3. Mapping: what we run today against what agent-fleet offers

| Our component                                                                      | agent-fleet equivalent                                              | Fit                                                                                                                                                                                      |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude Code main session as orchestrator (`orc` tab)                               | agent-hub on pi                                                     | **Does not map.** Migrating means replacing the orchestrator runtime with pi, which is not installed here. Claude Code would be demoted to a reviewer peer.                               |
| "Only the orchestrator orchestrates"                                               | Orchestrator mode drops edit tools; specialists run without extensions | Maps in spirit. The rule would still hold, restated for the hub.                                                                                                                         |
| Herdr panes driven by the `herdr` CLI                                              | `just fleet --herdr`, `herdr_spawn_peer`                            | Maps, but only for pi and Claude peers.                                                                                                                                                  |
| `acp-run` / `acp-dispatch` to Codex, Antigravity, zcode, opencode, Cursor, Copilot, Hermes | pi model providers (Codex, Copilot, Ollama) plus Claude peers        | **Partial.** Loses most of our vendors, the ACP permission scoping, and the report-file and `BLOCKED:` delivery contract.                                                                 |
| Report files and `BLOCKED:` first line                                             | Verification Contract ledger, research findings on disk             | Same idea, different format. Worth borrowing (section 5).                                                                                                                                |
| `helm`, `hermes-ping`, `fleet-watch` (who is waiting on the operator)              | Desktop panel `needs_answer` toast, Telegram relay of `ask_user`    | **Partial.** Covers only agent-fleet sessions: its registry is the filter, so our Claude, Codex and Hermes sessions outside a fleet stay invisible. Ours already spans every TUI.           |
| Requirement 1: silent Hermes, notify only when blocked                             | Relay forwards `ask_user` only                                      | Matches the shape, but only for pi. `helm` plus `hermes-ping` already do this across all agents.                                                                                         |
| Requirement 2: Hermes reads status from disk without pinging the hub               | Desktop plugin reads the coms registry and transcripts read-only    | Good design, fleet sessions only. Our report files and Tier 1 pointers already let any agent answer status from disk.                                                                    |
| Requirement 3: Codex Remote Control conductor from Android                         | **Retired.** `codex-remote` is gone; an experimental ChatGPT client replaced it with no conductor | **Does not map.** As the 2026-07-29 comment found, this is a native Codex feature independent of any hub.                                                                                |
| Requirement 4: Herdr server survives disconnects                                   | Nothing extra                                                       | **Already met.** `dev.herdr.server` is a KeepAlive LaunchAgent ([herdr-brew-service.md](herdr-brew-service.md)).                                                                        |
| Requirement 5: reference clone in `~/src`                                          | n/a                                                                 | Not done; cheap if a spike happens.                                                                                                                                                      |
| Tier 1 / Tier 2 handoffs, `orc-meta` watchdog, self-close guard wrapper            | Workspace snapshot/resume, `/af-compound` lessons                   | No equivalent for ours. Keep.                                                                                                                                                            |
| Quota pacing (`aiuse`, model-routing)                                              | Per-persona model ladders, `/af-models`                             | Different problem. Theirs picks a tier; ours checks real remaining quota across pools. Keep ours.                                                                                        |
| Verify-then-merge PR discipline, orphaned-PR sweeps                                | `/af-review`, `/af-ship` skills                                     | Overlaps with skills we already have. No reason to switch.                                                                                                                               |

## 4. Why not migrate

1. **It replaces the runtime, not just the skill.** The hub is pi. Today's
   orchestrator is Claude Code, and the toolkit around it (`acp-dispatch`,
   `helm`, `session-finder`, `bigteam`, handoffs) assumes that.
2. **It narrows the fleet.** Our routing spans about ten agent CLIs over ACP.
   agent-fleet reaches pi's providers plus Claude panes.
3. **The requirements that motivated #37 are met or moot.** Requirement 4 is
   met by the LaunchAgent. Requirement 3 was never agent-fleet's and it has
   since dropped it. Requirements 1 and 2 are covered across all TUIs by
   `helm`, `hermes-ping`, `fleet-watch` and report files.
4. **Churn and ownership.** Three releases a week from one maintainer, and a
   setup step that overwrites local edits, is a poor base for the layer that
   keeps every other agent running.
5. **It widens Hermes's attack surface.** The Telegram relay needs `terminal`
   and `file` toolsets on the Telegram platform, and the Desktop plugin needs
   a gateway restart.
6. **#139 already sequenced it.** "Defer a hub migration until the bounded
   Prime/Hermes worker experiment demonstrates a real coordination
   bottleneck." No such bottleneck has been recorded.

## 5. Ideas worth borrowing (small, inside existing tools)

1. **An acceptance ledger per dispatched slice.** Let the brief state checkable
   assertions up front and have the report mark each one met, unmet or open.
   This fits the existing `acp-dispatch` report and the `check` subcommand.
2. **A blocked-for-N-seconds signal.** agent-fleet raises `needs_answer` after
   20 s. `helm`'s collector could surface age-since-blocked the same way.

Each is a change to `~/src/djbclark-ade`, not to this repo.

## 6. If a spike is still wanted

A half-day to one-day spike, reversible by deleting a throwaway directory:

1. Make a throwaway repo in a cow pasture. Clone `chankov/agent-fleet` at tag
   `v2.0.19` beside it for reference.
2. Install pi and run
   `npx @chankov/agent-fleet@2.0.19 setup --preset default --features none --yes`,
   then `just fleet deps` and `just fleet doctor`. Pin the exact version.
3. Do **not** install the Hermes plugin or enable Telegram toolsets.
4. Run one real, small unit through `just fleet --agents frontend` and the
   same unit through today's `acp-dispatch` path. Compare result quality,
   operator interventions, tokens and wall time.
5. Undo with `npx @chankov/agent-fleet uninstall --all --yes` and delete the
   pasture.

Evaluate herdr-remote in the same spike only for the phone surface, and only
after reading its licence.

## 7. Effort, if the operator overrides this and migrates

| Piece                                                                      | Rough effort      |
| -------------------------------------------------------------------------- | ----------------- |
| Spike (section 6)                                                          | 0.5 to 1 day      |
| pi install, provider logins, routing parity with `model-routing`           | 1 to 2 days       |
| Rewrite `herdr-orchestration` around agent-hub, keep handoffs and `orc-meta` | 2 to 3 days       |
| Hermes plugin and relay, with a security review of the Telegram toolsets   | 1 day             |
| Keeping up with upstream releases                                          | ongoing, weekly   |

Rollback for any of it is the current skill, which stays in git at
`~/src/djbclark-ade/skills/herdr-orchestration` throughout.
