I’ll survey the live OSS landscape for unattended, self-hosted coding loops — focusing on projects that actually survive context exhaustion and subscription quotas, not just agent wrappers.GitHub pages confirm a few real systems; next I’ll pull live stats and check how each one actually survives context and quota failure.The thing that never dies cannot be an LLM. As of 16 Aug 2026 the field has mostly accepted that. The winning pattern is a **program** that starts a **fresh agent** on one tightly scoped unit of work, persists progress in **files / git / an issue graph**, then repeats. Compaction and “supervisor LLM above the orchestrator” are the two approaches that keep failing the way you described.

Do **not** adopt one mega-product. Adopt a **stack**. Almost nothing well-maintained does loop + quota + multi-repo + independent verification at once.

---

## The short answer

**Adopt this OSS stack, greenfield:**

1. **[Beads](https://github.com/gastownhall/beads)** as the durable work graph (this is the memory).
2. **[Ralph Orchestrator](https://github.com/mikeyobrien/ralph-orchestrator)** as the program that never dies (this is the loop).
3. **[Herdr](https://github.com/herdrdev/herdr)** as the process runtime so the loop survives lid-close / SSH drop / reboot.

If you want a more productized unattended runner and will accept a desktop app: **[Maestro](https://github.com/RunMaestro/Maestro)** instead of (or in front of) Ralph Orchestrator. It is the only maintained project I found that actually reads Claude subscription usage and auto-resumes when the window reopens.

If you actually need a multi-repo factory with merge queues: **[Gas Town](https://github.com/gastownhall/gastown)** — with the explicit warning that its “Mayor” is another LLM and will hit the same wall unless you treat the **daemon / scheduler / refinery** as the never-dies layer, not the Mayor.

---

## Dominant architecture (Aug 2026)

**In favor**

- **Ralph / harness loop.** A program picks one task, spawns a clean agent, agent writes artifacts, program verifies something outside the model’s mouth, next iteration starts empty. Geoffrey Huntley named it; Anthropic independently published the same idea as [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (initializer + incremental coding agent + artifacts). Beads won the “where does the task graph live?” fight.
- **Worktree isolation.** One task → one branch → one worktree → one PR. Parallelism without shared dirty trees.
- **Human gate at merge, not at every tool call.** Tight task definitions + tests + PR review.
- **Subscription CLIs as workers.** Claude Code / Codex / Gemini / OpenCode stay the workers. The orchestrator does not become another billed LLM if it can help it.

**Out of favor (for multi-day unattended work)**

- **One immortal chat + auto-compact.** Context rot hits before the hard window. Anthropic’s own Claude Code Ralph plugin is widely called *wrong Ralph* because it reuses the same session and compact. See [PageAI’s writeup](https://pageai.pro/blog/long-running-ai-coding-agents-ralph-loop).
- **Supervisor LLM above orchestrator LLM.** That is your infinite regress. [Agent Orchestrator](https://github.com/Untrivial-ai/agent-orchestrator) still sells this (“the orchestrator itself is an AI agent”). Gas Town’s Mayor is the same shape.
- **Pretty Kanban as the control plane.** [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) died with Bloop (shutdown 10 Apr 2026, last commit 24 Apr 2026). The survivors that look like it (Emdash, Nimbalyst, Claude Squad) are *human-supervised parallel session managers*, not AFK factories.

Anthropic’s later [March 2026 harness note](https://www.anthropic.com/engineering/harness-design-long-running-apps) said Opus 4.5 let them drop mid-build context resets and lean on compaction. That is a model-generation claim, not a reason to run one session for days on mixed vendors with rolling 5-hour / 7-day caps.

---

## Candidates (verified, not padded)

Stars, last-commit, and contributor counts below are from GitHub on **2026-08-16** unless noted.

### 1. Beads — `gastownhall/beads`

- **URL / license:** https://github.com/gastownhall/beads · MIT
- **What it does:** Git-local issue graph (`bd`) for agents. `bd ready` / `bd update --claim` / `bd close` / `bd remember`. Storage is Dolt (embedded by default), with JSONL as export, not source of truth.
- **Maturity:** 26,362 stars, last commit 15 Aug 2026, 100+ contributors, release `v1.2.2` same day. Originated with Steve Yegge; now `gastownhall`. This is a real project, not a blog repo.
- **Context exhaustion:** It does not run agents. It is the disk the next fresh agent reads. Closed work can be semantically compacted (“memory decay”).
- **Never-dies thing:** A **program** (`bd`) + a database.
- **Durable state:** `.beads/` (Dolt). Optional git remotes via `bd dolt push/pull`.
- **Quota:** None.
- **Multi-vendor:** Agent-agnostic. `bd setup` hooks exist for Claude, Codex, Cursor, Factory, etc.
- **Weaknesses:** Not a loop. Dolt adds operational weight versus the old SQLite+JSONL “classic” beads. [beads_rust](https://github.com/Dicklesworthstone/beads_rust) froze that older architecture (1,052 stars, 2 contributors) — fine if you want SQLite, not a replacement for the live project. **Bad fit** if you wanted an orchestrator.

### 2. Ralph Orchestrator — `mikeyobrien/ralph-orchestrator`

- **URL / license:** https://github.com/mikeyobrien/ralph-orchestrator · MIT
- **What it does:** Rust CLI that runs coding agents in a loop until `LOOP_COMPLETE` or an iteration cap. “Hats” are personas (implement / review / debug). **Backpressure gates reject work that fails tests / lint / typecheck.**
- **Maturity:** ~3.1k stars, commit on **16 Aug 2026**, ~38 contributors (Trendshift; author-heavy). Releases through `v2.10.1` (23 Jun 2026). Individual-led (Mikey O’Brien), not a company. Passes the 60-day rule; community is real but thinner than Beads/OpenHands.
- **Context exhaustion:** Fresh iteration is the point. State lives in `.ralph/specs/`, tasks, memories, events — not in the model.
- **Never-dies thing:** A **program** (`ralph`).
- **Durable state:** Files under `.ralph/`. Optional Beads dir is in the repo. Web dashboard is alpha.
- **Quota:** No subscription-window awareness I could verify. Iteration limits and timeouts only.
- **Multi-vendor:** Claude Code, Codex, Gemini CLI, OpenCode, Copilot CLI, Kiro, Forge, Amp.
- **Weaknesses:** Author-centric. Multi-repo is “one MCP/server per workspace,” not a fleet. Telegram “RObot” is optional HITL you said you do not want. **Bad fit** if you need company-backed ops or cross-account quota rotation.

This is the closest maintained terminal-native answer to *your actual problem*.

### 3. Maestro — `RunMaestro/Maestro`

- **URL / license:** https://github.com/RunMaestro/Maestro · AGPL-3.0
- **What it does:** Desktop “command center.” Auto Run walks markdown checklists; each task (default) is a **new agent session**. Goal-Driven mode is Ralph-without-a-checklist. Worktree dispatch + optional PR at the end. Headless `maestro-cli` for cron.
- **Maturity:** 3,254 stars, last commit 16 Aug 2026, 48 contributors, latest tagged release `v0.17.3` (4 Jul 2026). Pedram Amini / RunMaestro. Active, not vaporware. AGPL is a real constraint if you ever vendor it.
- **Context exhaustion:** Documented as first-class. “Fresh context per task” vs “per document.” Isolation is “critical for looping playbooks.”
- **Never-dies thing:** A **program** (Electron app + CLI). Group Chat has a moderator LLM — ignore that feature.
- **Durable state:** Markdown playbooks, `runs/` copies as audit logs, History panel, git branches/PRs.
- **Quota:** **Best in class among things I verified.** Settings → Auto-Resume on Limit. For Claude it “reads your actual plan usage” and waits; other providers retry on an interval (default 2h, give-up 7d). Survives app restart *for the agent conversation*. Caveat they document themselves: **the Auto Run loop controller does not survive restart** — you can lose the checklist walker even if the chat resumes.
- **Multi-vendor:** Claude Code, Codex, OpenCode, Factory Droid, Copilot CLI (beta). Gemini CLI is “maybe later.”
- **Weaknesses:** Not terminal-native (Electron). Goal-run progress is an HTML comment the **agent writes** (`<!-- maestro:progress 45 -->`) — that is self-report. **Bad fit** if you refuse desktop apps or AGPL.

### 4. Gas Town — `gastownhall/gastown`

- **URL / license:** https://github.com/gastownhall/gastown · MIT
- **What it does:** Multi-repo “town”: rigs (projects), polecats (ephemeral worker agents in worktrees), convoys (batches of beads), a **Go daemon**, Witness/Deacon watchdogs, and a Bors-style **Refinery** merge queue. Mayor is a Claude (or other) session you talk to.
- **Maturity:** 17,633 stars, 100+ contributors, Homebrew/`@gastown/gt`. `main` last commit **23 Jul 2026** (inside 60 days; cadence has slowed vs Beads). Latest release `v1.2.1` 6 Jun 2026. Yegge-origin, now `gastownhall`.
- **Context exhaustion:** Work state is Beads + git worktree “hooks,” not chat. `gt prime` / `gt seance` recover predecessor sessions from `.events.jsonl`. Polecat sessions are meant to die.
- **Never-dies thing:** **Mixed, and this matters.** Daemon, scheduler, Witness patrol, Refinery = **programs**. Mayor, Deacon, Boot = **LLMs**. If you make the Mayor the thing that “never dies,” you have rebuilt your current failure. Use `gt sling` + daemon + `scheduler.max_polecats` and treat Mayor as optional.
- **Durable state:** Beads (per-rig Dolt) + worktrees + convoy DB.
- **Quota:** `scheduler.max_polecats` batches dispatch to avoid rate-limit exhaustion. This is **concurrency capping**, not 5-hour/7-day subscription accounting, and not multi-account rotation.
- **Multi-vendor:** Presets for claude, gemini, codex, kiro, cursor, auggie, amp, opencode, copilot, pi.
- **Weaknesses:** Naming tax (mayor/polecat/witness/deacon/molecule/wasteland). Feb 2026 field report: orphaned daemons, 2–3 concurrent agents realistic on an M2, “Mayor still waits for you to tell it what to do,” people writing cron to poke it. **Bad fit** unless you want to operate a small factory, not a loop.

### 5. Herdr — `herdrdev/herdr`

- **URL / license:** https://github.com/herdrdev/herdr · Apache-2.0
- **What it does:** Agent-aware terminal multiplexer. Background server owns PTYs. Sidebar shows working / blocked / idle. Does not replace Claude/Codex/etc.
- **Maturity:** 29,696 stars, commit 16 Aug 2026, 76 contributors, `v0.8.0` 3 Aug 2026, Homebrew. Hottest “agent runtime” of 2026.
- **Context exhaustion:** None. It keeps *processes* alive, not *context*.
- **Never-dies thing:** A **program**.
- **Durable state:** Session/layout persistence, not work state.
- **Quota / multi-vendor:** Detects many CLIs; no quota brain.
- **Weaknesses:** If you install only this, you still have a human restart ritual — you just have a nicer tmux. **Adopt as infrastructure, not as the orchestrator.**

### 6. Ralph for Claude Code — `frankbria/ralph-claude-code`

- **URL / license:** https://github.com/frankbria/ralph-claude-code · MIT
- **What it does:** Host-side bash loop around `claude`. Circuit breaker, hourly call/token caps, GitHub issue → PR lifecycle, Beads import, Docker/E2B sandbox for the worker only.
- **Maturity:** 9,605 stars, last visible commits 10 Jul 2026 (`pushed` 18 Jul), v0.11.5, 784 tests. Individual-led (Frank Bria) with outside PRs. Pre-1.0.
- **Context exhaustion:** Loop is a program. **They also implement session continuity via `--resume`**, which is the *anti-Ralph* choice Huntley and PageAI warn about. `--no-continue` exists; default is continuity.
- **Never-dies thing:** A **program**.
- **Durable state:** `.ralph/PROMPT.md`, `fix_plan.md`, logs, optional `.ralph/queue.json`.
- **Quota:** Closest Claude-specific handling: 100 calls/hour (configurable), optional tokens/hour, **three-layer 5-hour-limit detection**, unattended auto-wait 60 minutes. This is hourly/5-hour, not 7-day, and not multi-account.
- **Multi-vendor:** Claude only. Multi-provider is an [open ADR](https://github.com/frankbria/ralph-claude-code/blob/main/docs/adr/0001-multi-provider-agent-abstraction.md), not shipped.
- **Weaknesses:** One vendor. Exit still leans on Claude emitting `EXIT_SIGNAL`. **Bad fit** if you rotate Grok/Codex/Gemini for quota.

### 7. OpenHands — `OpenHands/OpenHands`

- **URL / license:** https://github.com/OpenHands/OpenHands · MIT (All Hands AI)
- **What it does:** Self-hosted agent platform (Agent Canvas). Own CodeAct agent in a Docker sandbox, **or** ACP subprocesses of Claude Code / Codex / Gemini CLI using the **same subscription login** already on the machine ([ACP docs](https://docs.openhands.dev/openhands/usage/agent-canvas/acp-agents)). Automations = cron/webhook that start a **fresh sandbox**. Resolver = labeled GitHub issue → PR.
- **Maturity:** 84,206 stars, commit 15 Aug 2026, 100+ contributors, `v1.13.0` 13 Aug 2026. Company-backed, real releases. This is the grown-up “self-hosted Devin.”
- **Context exhaustion:** Automations start fresh. Long interactive sessions compact. Not a Beads-style multi-day factory.
- **Never-dies thing:** Platform **program** (scheduler + sandboxes). Each run is a new LLM.
- **Durable state:** Conversation store + git remotes/PRs. Not a local issue graph.
- **Quota:** Subscription reuse via ACP is real. No 5-hour/7-day pacer I found. Cloud path wants API keys.
- **Multi-vendor:** Own agent (BYOK) + Claude/Codex/Gemini via ACP. Not Grok/Cursor/OpenCode as first-class ACP in the docs I read.
- **Weaknesses:** Web/desktop control center, Docker tax, company product around the MIT core. **Bad fit** if you want a local TUI loop across many private repos with no extra platform.

### 8. Goose — `aaif-goose/goose` (was `block/goose`)

- **URL / license:** https://github.com/aaif-goose/goose · Apache-2.0 (Block → AAIF)
- **What it does:** Local agent + YAML **recipes** + scheduler + `goose run --continuous --budget`.
- **Maturity:** 52,869 stars, commit 14 Aug 2026, 100+ contributors, `v1.46.0` 12 Aug 2026.
- **Context:** Continuous mode is still one agent. Budget is **API dollars**, not subscription windows.
- **Never-dies:** Recipe scheduler is a **program**; the worker is an LLM.
- **Weaknesses:** One agent personality, not a multi-CLI quota rotator. `--budget` assumes metered APIs — the failure mode you named.

### 9. Agent Orchestrator (AO) — `Untrivial-ai/agent-orchestrator`

- **URL / license:** https://github.com/Untrivial-ai/agent-orchestrator · Apache-2.0  
  (was Composio; org moved)
- **What it does:** Local desktop + daemon. Workers in worktrees. Live Kanban derived from PR/CI facts. 26 CLI agents.
- **Maturity:** 9,559 stars, commit **today**, 81 contributors, `v0.12.5` 15 Aug 2026.
- **Context / never-dies:** Their own blog: **“the orchestrator itself is an AI agent.”** That is the stacked-supervisor design. Workers can be fresh; the planner is not.
- **Quota:** None material.
- **Weaknesses:** Solves parallel human-supervised fleets. Does not solve your wall. Desktop, telemetry on by default.

### 10. Parallel session managers (not AFK factories)

These are maintained and useful for a human driving many agents. They do **not** replace the handoff ritual for a days-long unattended run.

| Project | URL | License | Stars | Last commit | Notes |
|---|---|---|---|---|---|
| Claude Squad | https://github.com/smtg-ai/claude-squad | AGPL-3.0 | 8,325 | 30 Jul 2026 | tmux + worktrees; you still attach |
| Emdash | https://github.com/generalaction/emdash | Apache-2.0 | 5,414 | 16 Aug 2026 | YC W26 Electron ADE; 20+ CLIs; human merge |
| Nimbalyst (ex-Crystal) | https://github.com/nimbalyst/nimbalyst | MIT | 1,493 | 13 Aug 2026 | Visual workspace; Crystal last commit Feb 2026 |
| Jean | https://github.com/coollabsio/jean | Apache-2.0 | 1,180 | 14 Aug 2026 | Coolify team; early |

### Flagged: do not adopt as the never-dies layer

| Project | Why |
|---|---|
| [BloopAI/vibe-kanban](https://github.com/BloopAI/vibe-kanban) | Company shut down 10 Apr 2026. Banner: sunsetting. Last commit 24 Apr 2026. 27.8k stars is a tombstone. |
| [subsy/ralph-tui](https://github.com/subsy/ralph-tui) | Architecturally right (program loop, Beads/prd.json, many CLIs). **Last commit 13 May 2026, last release v0.12.0 same day.** ~95 days stale. 2,426 stars. Do not greenfield onto a paused repo. |
| Anthropic Claude Code `ralph-wiggum` plugin | Same session + auto-compact. Community consensus: not Ralph. |
| [ghuntley/how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum) | Method essay, last push Jan 2026. Read it; do not “install” it. |
| [PageAI-Pro/ralph-loop](https://github.com/PageAI-Pro/ralph-loop) | Correct principles. 288 stars, last push 28 Jun 2026. Too small. |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | Great pair programmer historically. Last commit 22 May 2026, last release Aug 2025. Pair tool, not a factory. |
| [letta-ai/letta](https://github.com/letta-ai/letta) | 24k stars, very alive. Memory OS, not a coding loop. |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | 198k stars. A **worker**, not an orchestrator. |
| `claude-rotate`, `open-grok-build` | Single-digit stars. Not a control plane. |

I did **not** find a maintained, multi-contributor, 60-day-active OSS that does **cross-vendor rolling-window quota + account rotation** as a first-class scheduler. That gap is real.

---

## What still does not exist (you will still build, or do without)

Be specific. These are the holes after throwing away your ritual:

1. **A quota brain for subscription windows.** Nobody I verified tracks Claude 5-hour *and* 7-day *and* Codex *and* Gemini *and* Grok *and* Cursor rolling caps, then parks work or switches worker. Maestro reads Claude plan usage. frankbria waits on Claude 5-hour. Gas Town caps concurrent polecats. Goose caps **API dollars**. Fresh session does not refill a capped account — you already know this, and the market has not shipped the fixer.

2. **Independent verification that ignores the agent’s story.** You have been burned by exit 0 on wrong work and `INTERRUPTED` on success. Closest OSS:
   - Ralph Orchestrator **backpressure** (tests/lint must pass).
   - Gas Town **Refinery** (merge queue + verification gates).
   - OpenHands sandbox traces + CI on the PR.
   
   Still missing: a judge that diffs the tracker (`bd show`), the git range, and the test log, and *refuses* to mark the bead done if those three disagree — without asking the same agent “did you finish?” Maestro’s goal-run progress comment is exactly the self-report you distrust.

3. **Simple multi-repo Ralph.** Beads is per-repo (federation exists, it is not simple). Gas Town is multi-repo and is a lifestyle. AllBeads (`thrashr888/AllBeads`) looked early; I did not treat it as adopt-ready.

4. **Loop persistence across machine reboot.** Herdr persists panes. Maestro documents that Auto Run’s **controller** dies on restart. frankbria queue survives process death better than Maestro’s controller. Nobody gives you “close the lid Friday, open Monday, the *same* DAG is still walking” as a boring guarantee.

5. **Grok / Cursor as first-class loop backends.** AO and Herdr will *launch* them. The serious loops (Ralph Orchestrator, Maestro, frankbria) are weaker here. I would not claim Grok is a supported Ralph backend without testing it myself — I did not.

---

## Top 3, ranked

### 1. Beads + Ralph Orchestrator (+ Herdr as the host)

**Why first:** This is the only combination that is (a) actively maintained, (b) terminal-native, (c) a **program** loop with **fresh context**, (d) multi-CLI, (e) has a verification hook that is not the model’s exit code, (f) stores work where the next amnesiac agent can find it.

- Beads is the durable brain. Ralph Orchestrator is the while-loop. Herdr is so you stop caring about SSH drops.
- Safety model matches yours: scoped beads → isolated commits → you review PRs.
- You will still write **acceptance criteria into beads** so backpressure has something to chew. That is configuration, not a new orchestrator.

**Honest cost:** Ralph Orchestrator is individual-led. If Mikey stops, you have a MIT Rust codebase and Beads still works. That is a better failure mode than a SaaS.

### 2. Maestro Auto Run (keep Beads underneath)

**Why second:** Best productized “walk away for hours.” Fresh session per checkbox is documented, not implied. Worktree + auto-PR is the integration gate you want. Auto-Resume on Limit is the only **subscription-aware** wait I could verify, and it is Claude-first.

**Why not first:** Electron + AGPL; Gemini missing; loop controller dies on restart; Goal-Driven progress is self-scored. Use Spec-Driven playbooks and put the real done-check in tests + `bd close`, not in `maestro:progress`.

### 3. Gas Town, but only the program half

**Why third:** It is the only mature OSS that is *natively* multi-repo, worktree-per-worker, merge-queued, and concurrency-limited. If “several independent git repos” is non-negotiable, this is the factory.

**Why not higher:** The marketed UX is “talk to the Mayor.” The Mayor is an LLM with a tmux session. Field reports say it sits idle until poked. Use `gt sling`, the daemon, `scheduler.max_polecats`, Witness, and Refinery. Leave the Mayor for planning you are present for.

---

## Practical adoption order (still OSS, still not a custom framework)

1. `bd init` in every repo. Stop using markdown TODO as the source of truth.
2. Install Ralph Orchestrator. One epic, `--backend` rotating among the CLIs you already have, backpressure = your test command.
3. Put the loop in Herdr so the program, not an LLM, is what you reattach to.
4. Land work as PRs. Judge success with `git diff`, CI, and `bd show` — never the agent’s last sentence.
5. Add Maestro only if you want Auto-Resume on Claude Max nights.
6. Touch Gas Town only after that stack is boring, and only for multi-repo dispatch.

If you do that and still hit quota mid-loop, that last mile — **cross-vendor rolling-window pacing and account rotation** — is the piece the open-source ecosystem has not actually shipped. I would not pretend otherwise.
