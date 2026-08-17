I verified these projects on GitHub on 2026-08-16 (API metadata, READMEs, and source docs). Web search was blocked in this session, so I did not pull blogs or Discord chatter. If a claim is not in the repo, I say so.

---

## The short version

The wall is real, and stacking supervisor LLMs is the wrong fix. As of August 2026 the projects that still get commits treat **the thing that never dies as a program**, and treat **each agent session as disposable**. Durable state lives in files, git, and an issue graph — not in a context window.

There is **no** well-maintained OSS I could verify that understands **rolling 5-hour / 7-day subscription windows** or **multi-account rotation**. Cost caps in dollars/tokens are common. Quota-as-a-resource is not. That piece you would still own.

---

## Dominant architectural pattern (Aug 2026)

**Ralph-style outer loop + structured tracker + worktree isolation + PR as the human gate.**

Geoffrey Huntley’s original definition, still quoted by the maintained implementations: *“Ralph is a Bash loop.”* Each iteration is a **fresh LLM process**. The loop itself is a program. Disk/git/tracker are the memory. Quality is enforced by **gates** (tests, lint, CI on a PR), not by a smarter supervisor.

What has gone out of favor, based on what repos actually do versus what they used to promise:

- **Supervisor-on-supervisor LLMs.** Gas Town’s own docs now treat session cycling as *normal*, not failure. OpenHands still condenses, but its unattended story moved to a control plane that starts *jobs*, not one immortal conversation.
- **Same-session infinite loops.** Anthropic’s official Ralph plugin does this (Stop hook, same context). That is the pattern that already failed you.
- **Kanban web UIs as the control plane.** [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) published a sunsetting banner on 2026-04-24 and stopped shipping.
- **Per-action approval as safety.** The 2026 consensus in these repos is: yolo inside a sandbox/worktree, review the PR.
- **Aider as the long-running harness.** Last commit 2026-05-22. Still famous, no longer a greenfield adopt.

Inner-loop agents (Claude Code, Codex, OpenCode, Goose, Pi, Gemini CLI) are **workers**. They are not the thing that should live for days.

---

## Candidates worth taking seriously

### 1. Ralph Orchestrator

- **GitHub:** https://github.com/mikeyobrien/ralph-orchestrator
- **License:** MIT
- **What it does:** A Rust program that runs coding CLIs in a loop until `LOOP_COMPLETE` or a hard limit. Each iteration is a fresh agent process; specs, memories, tasks, and git are the handoff. It has a TUI, a still-alpha web dashboard, and “backpressure” gates (tests/lint/typecheck) instead of a supervisor LLM.

**Maturity (verified 2026-08-16):** ~3,098 stars, last commit **today**, latest release **v2.10.1 on 2026-06-23**, ~33 contributors. Bus factor is real: `mikeyobrien` has 457 commits; the next person has 16. Individual-maintained, not a company. Discord exists. Docs at https://mikeyobrien.github.io/ralph-orchestrator/.

**Context exhaustion:** **Fresh context per iteration.** Stated as tenet #1. Disk is state (`.ralph/agent/memories.md`, `tasks.jsonl`, specs). It also writes `.ralph/agent/handoff.md` when a loop ends. Worktree-local loop state is first-class in `crates/ralph-core/src/loop_context.rs`.

**What never dies:** **A program** (`ralph` CLI / event loop). Hats (builder, reviewer, etc.) are LLM personas *inside* iterations, not an immortal supervisor.

**Durable state:** `.ralph/` files + git. Not Beads by default. Optional memories injected with a token budget.

**Quota:** Dollar/token `--max-cost` / `--max-tokens`. Docs still talk like metered API billing (`docs/guide/cost-management.md`). **No rolling 5h/7d window, no multi-account rotation.** I checked backends: Claude, Kiro, Gemini CLI, Codex, Forge, Amp, Copilot CLI, OpenCode, Pi. **Cursor CLI and Grok are not listed.** A PTY executor exists, so wrapping another binary may work; I did not verify Cursor/Grok as first-class.

**Weaknesses:** Bus factor; release cadence slower than commits; hat system can become a second brain if you overuse it; cost docs look partly leftover from an older Python CLI; verification is “gates + reviewer hat,” and I did **not** prove the program itself re-runs tests versus trusting the agent’s evidence string. Independent CI on the PR is still the real check.

**Bad fit for:** Anyone who needs a company-backed SLA, or who needs Cursor/Grok/quota rotation to be native.

---

### 2. Gas Town + Beads

- **Gas Town:** https://github.com/gastownhall/gastown — MIT — ~17,633 stars
- **Beads:** https://github.com/gastownhall/beads — MIT — ~26,362 stars (repo redirected from `steveyegge/beads`)

**What they do:** Gas Town is a **tmux workspace manager** for many coding agents across many git repos (“rigs”), with worktrees (“hooks”), mailboxes, and a merge queue. Beads is the git-backed issue graph those agents actually remember. Together they are the most complete OSS “town of agents” I found.

**Maturity:** Org `gastownhall` (Steve Yegge’s stack). Beads: last commit 2026-08-15, release **v1.2.2 the same day**, hundreds of contributors. Gas Town: last commit on `main` **2026-07-23** (inside 60 days), last *release* **v1.2.1 on 2026-06-06** (outside 60 days). Lots of integration branches; this is a living but heavy system, not a quiet one.

**Context exhaustion:** **Session cycling is the design.** Polecat identity persists; the live Claude/Codex session is killed on purpose (`docs/concepts/polecat-lifecycle.md`): handoff between molecule steps, context compaction, crash → Witness respawn. Quote from that doc: *“Session cycling is normal operation, not failure.”* Beads compaction (“memory decay”) shrinks old closed work so `bd prime` stays small.

**What never dies:** **Mixed, and this matters.**

| Piece | Kind |
|---|---|
| Deacon / stuck-agent dogs / Go daemons | **Program** (heartbeats, poke, recycle) |
| Witness | Hybrid: Go manager + an agent role (`templates/witness-CLAUDE.md`) |
| Mayor | **LLM coordinator** — “tell the Mayor what to build” |
| Polecats | Ephemeral LLM sessions |

This is **not** infinite regress if you treat Mayor as a *worker you can restart*, and Deacon as the watchdog. It **is** infinite regress if you expect the Mayor session to live for days. That is the same trap you already hit.

**Durable state:** Beads (Dolt + JSONL), git worktrees/hooks, heartbeat JSON files.

**Quota:** I found pacing/backoff for *await-event* and heartbeat thresholds, not vendor subscription windows. **No multi-account rotation in the docs I read.**

**Multi-vendor:** First-class. Claude, Gemini, Codex, Cursor, Amp, OpenCode, Copilot, plus a JSON preset system so any terminal CLI can be wired (`docs/agent-provider-integration.md`). Tier 0 is literally “tmux send-keys.”

**Weaknesses:** Operational complexity (town, rigs, mayor, deacon, witness, polecats, molecules, convoys). Mayor is still an LLM. Heartbeat false positives are a documented class of bug. Beads + Dolt is a real dependency. Overkill for one repo, one agent.

**Bad fit for:** Someone who wants a single `ralph run` binary and a PRD file. Good fit if multi-repo + many parallel worktrees is the actual job.

---

### 3. Herdr

- **GitHub:** https://github.com/herdrdev/herdr
- **License:** Apache-2.0
- **What it does:** An always-on terminal runtime (Rust, one binary). Agents keep running if you close the lid. Panes are marked working / blocked / idle. It does **not** wrap or replace Claude/Codex/Cursor/OpenCode/Grok; it owns their terminals.

**Maturity:** ~29,697 stars, commits through **2026-08-16**, latest stable **v0.8.0 on 2026-08-03**, ~78 contributors, company/org `herdrdev`, Homebrew formula, plugin ecosystem.

**Context exhaustion:** **Does not solve it.** A Herdr pane can host a session that still fills up. Herdr keeps the *process* alive, not the *context* fresh.

**What never dies:** **A program** (background server + sessions).

**Durable state:** Session state on disk; your git repos; not a task graph.

**Quota / multi-vendor:** Multi-vendor yes (whatever you already run). Quota: none that I verified.

**Weaknesses:** Wrong layer for the research question. It is the floor (unattended *process*), not the ceiling (unattended *progress*). `blocked` means it saw an approval UI — the opposite of “no per-action prompts” unless you run agents in yolo.

**Bad fit for:** Using it *as* the orchestrator. Good fit as the place the orchestrator’s workers live.

---

### 4. OpenHands (Agent Canvas)

- **GitHub:** https://github.com/OpenHands/OpenHands
- **License:** MIT
- **What it does:** Self-hosted **web** control center that starts coding-agent jobs (own agent, or Claude Code / Codex / Gemini via ACP) on local/Docker/VM/cloud backends, with scheduled automations and GitHub/Slack/Linear hooks.

**Maturity:** ~84,206 stars, ~516 contributors, company (All Hands AI / OpenHands org). Releases **v1.13.0 on 2026-08-13**, roughly weekly. This is the most institutional OSS coding-agent project.

**Context exhaustion:** **Compaction**, not fresh-process Ralph. The SDK condenser (`OpenHands/software-agent-sdk`) summarizes the first half of the event log when the window fills, with a hard reset if that fails. Jobs are restartable; the conversation is not designed to be immortal.

**What never dies:** **A program** (Agent Canvas + agent-server). Each task is an LLM job.

**Durable state:** Conversation event log + git in a sandbox + whatever tracker you wire (GitHub/Linear).

**Quota:** BYO model. Metered-API shaped. ACP can use vendor subscriptions, but I did not find rolling-window pacing.

**Multi-vendor:** Yes, via ACP.

**Weaknesses:** The dedicated terminal CLI (**https://github.com/OpenHands/OpenHands-CLI**) is **explicitly unmaintained**; they point you at Agent Canvas. That fights “terminal-native.” Compaction is the strategy you already distrust. Cloud/sandbox bias. Local no-sandbox mode gives the agent your whole filesystem.

**Bad fit for:** Someone who wants a TUI loop over existing CLIs and git worktrees on a Mac, with no web control plane.

---

### 5. oh-my-claudecode (OMC)

- **GitHub:** https://github.com/Yeachan-Heo/oh-my-claudecode
- **License:** MIT
- **What it does:** A large Claude Code plugin/CLI that adds teams, autopilot, PRD-driven Ralph, and reviewer verification on top of Claude Code.

**Maturity:** ~38,596 stars, commits through 2026-08-16, release **v4.15.10 on 2026-08-10**, ~140 contributors. Individual-led (`Yeachan-Heo`) with a real collaborator set. Codex sibling: https://github.com/Yeachan-Heo/oh-my-codex.

**Context exhaustion:** Has a Ralph skill, but it is **PRD + session persistence + retry**, in the Claude Code plugin style — closer to Anthropic’s same-session loop than to Huntley’s fresh process. Autopilot is another inner orchestrator. This can still fill a window.

**What never dies:** **Claude Code**, plus plugin hooks. Not a vendor-neutral program loop.

**Durable state:** `.omc/` PRD/session files, `progress.txt`.

**Quota / multi-vendor:** Claude-first (Codex in a separate repo). No subscription-window manager.

**Weaknesses:** Standardizing on Claude Code fights quota rotation. Inner orchestration is exactly the regress you described if you then put another LLM over it.

**Bad fit for:** Multi-vendor rotation. Possible fit if you pick **one** subscription and want a thick Claude-native workflow.

---

### 6. Goose (AAIF / Linux Foundation)

- **GitHub:** https://github.com/aaif-goose/goose (formerly `block/goose`)
- **License:** Apache-2.0
- **What it does:** A local-first coding/general agent (desktop + CLI) with many model providers, including **subscription login via ACP**.

**Maturity:** ~52,869 stars, ~600 contributors, weekly-ish releases (**v1.46.0 on 2026-08-12**). This is the “replace Claude Code” option, not the “drive the CLIs you already have” option.

**Context / never-dies:** Goose is a **worker**. Recipes can automate, but I did not treat it as a multi-day outer loop. Compaction/session behavior not fully verified here (code search rate-limited).

**Quota:** ACP subscription support is the closest official “use my Claude/ChatGPT/Gemini plan” story. Still not 5h/7d pacing.

**Bad fit for:** Keeping Claude Code + Codex + Cursor + Grok as the workers. Good fit only if you are willing to make Goose the worker and throw the others away.

---

### 7. Beads (as a layer, not the loop)

Covered under Gas Town, but it is independently the right **durable memory** even if you never install `gt`. `bd ready` / `bd claim` / `bd close` / `bd prime` / `bd remember`. Compaction of old closed issues. Agent setup for Claude, Codex, Cursor, Factory, etc.

There is a Rust port, https://github.com/Dicklesworthstone/beads_rust (~1,052 stars, pushed 2026-08-15). Smaller community; only relevant if you already standardized on `br`.

---

## Explicit non-answers (verified)

| Project | Why it is a non-answer |
|---|---|
| **https://github.com/subsy/ralph-tui** | Last commit **2026-05-13** (~95 days). 2,426 stars, MIT, 30 contributors, last release v0.12.0 that same day. Architecturally the right *shape* (fresh agent per task, Beads tracker, Claude/OpenCode/Cursor/Gemini/Codex). **Fails the 60-day rule.** Do not greenfield-adopt a stalled orchestrator. |
| **https://github.com/snarktank/ralph** | The popular script (21,503 stars, MIT). Last push **2026-02-02**. Technique, not a maintained product. Fresh context + `progress.txt` + `prd.json` is the idea everyone else implemented. |
| **Anthropic `ralph-wiggum` plugin** in https://github.com/anthropics/claude-code | Official. **Loops inside the current session via a Stop hook.** Same context window. This is the failure mode, packaged. |
| **https://github.com/BloopAI/vibe-kanban** | **Sunset**, last commit 2026-04-24. Apache-2.0, 27k stars, dead. |
| **https://github.com/RooCodeInc/Roo-Code** | **Archived.** |
| **https://github.com/Aider-AI/aider** | Last commit 2026-05-22. Pair-programmer, not an unattended multi-day loop. |
| **https://github.com/smtg-ai/claude-squad** | Last push 2026-07-30, AGPL-3.0, ~19 contributors. tmux multiplexer for parallel agents. Does not solve context exhaustion. Herdr is the maintained version of this *layer*. |
| **https://github.com/langchain-ai/open-swe** | Active (commit today, 10.5k stars, MIT). Cloud sandboxes + Slack/Linear + LangGraph. **Not local-first terminal-native.** API-model shaped. |
| **https://github.com/OpenHands/OpenHands-CLI** | README: **no longer actively maintained.** |
| **https://github.com/coleam00/Linear-Coding-Agent-Harness** | Last commit 2026-01-28. |
| **https://github.com/jedarden/NEEDLE** | Right architecture (program + bead queue + any CLI), last push today, MIT — **16 stars.** Fails the community bar. Mentioned only so you know the shape exists in miniature. |
| **https://github.com/wiggumdev/ralph** | 18 stars, last push 2026-04-17. |

I did not pad with Continue, Crush, Kilo, Cline, Pi, or OpenCode as *orchestrators*. They are editors/workers. Pi (https://github.com/earendil-works/pi, ~91k stars, MIT, pushed today) is a strong **worker** and is a Ralph Orchestrator backend.

---

## What genuinely does not exist yet

These are the holes I could **not** find a maintained OSS project filling. You would still build or keep thin glue:

1. **Subscription-window awareness.** No project I verified models rolling 5-hour / 7-day caps, backs off until a window resets, or fails a *loop* as “account capped” rather than “retry the API key.” A fresh session does not fix this, and they all assume it might.
2. **Multi-account rotation as a first-class scheduler.** You can point different loops at different binaries. Nobody owns “Claude account 2 is in the 5h hole, fail over to Codex, then Grok, without double-spending prepaid.”
3. **Independent verification that does not trust the agent.** Ralph’s backpressure *philosophy* is right; Gas Town’s merge/refinery is closer. I did not find a small program that, after every iteration, runs *your* tests, diffs, and tracker queries and is willing to mark the orchestrator’s “COMPLETED” as a lie. Your existing distrust of clean exits / `INTERRUPTED` is still justified. The practical OSS answer is: **land a PR and let CI + `git diff` + `bd show` be the truth**, not the TUI status line.
4. **A maintained Ralph TUI with Cursor + Grok plugins and Beads.** That used to be `subsy/ralph-tui`. It went quiet in May. Ralph Orchestrator is the maintained loop but weaker on those two vendors and on Beads.
5. **Quota-aware + fresh-context + multi-repo + Beads** as one product. Gas Town has the last three. Ralph Orchestrator has fresh-context. Nobody has quota.

---

## Top 3, ranked

### 1. Adopt **Ralph Orchestrator** as the never-dying program

https://github.com/mikeyobrien/ralph-orchestrator

This is the only actively maintained, multi-vendor, terminal-native project whose *stated architecture* is exactly your failure analysis: **fresh context every iteration, disk is state, sit on the loop not in it.** It already thinks about worktrees, handoff files, and “don’t prescribe, reject bad work.” Run it headless on macOS, `auto-yes` the CLIs, and make the human gate a PR.

Caveat: treat it as a **young individual-maintained** tool with a June release and an August commit log, not as OpenHands-grade institutional coverage. Keep tasks small enough that one iteration cannot do unbounded damage.

### 2. Adopt **Beads** as durable state (even if you never install Gas Town)

https://github.com/gastownhall/beads

This is the piece supervisor-LLMs were trying to be. A dependency graph the next fresh session can `bd prime` / `bd ready` without inheriting a poisoned transcript. Compaction is applied to *closed work in the tracker*, not to a 200k-token chat. Pair it with Ralph Orchestrator (tracker = Beads or PRD files) rather than inventing another handoff markdown ritual.

### 3. Adopt **Gas Town** only if the job is really many agents × many repos for days

https://github.com/gastownhall/gastown

This is the grown-up version of “unattended town.” Worktrees, identities, merge queue, Witness recycle, multi-vendor including Cursor. Use it if Ralph’s single-loop model is too small. **Do not** make the Mayor session the thing that never dies. Let Deacon/Go daemons be immortal; let Mayor and polecats be cheap to kill.

If that complexity is too much, **do not** take OpenHands as the #3 substitute unless you accept a web control plane and compaction. If you just need the process to survive sleep/SSH, put Ralph workers **inside Herdr** (https://github.com/herdrdev/herdr) — complementary, not competing.

---

## How this maps onto the hard requirements

| Requirement | Best OSS answer |
|---|---|
| Context exhaustion | Ralph Orchestrator (fresh process). Gas Town (session cycle + Beads). Not Anthropic’s plugin. Not a supervisor LLM. |
| Unattended, human-gated integration | Yolo in a worktree; land a PR; CI + diff + `bd show`. |
| Multi-repo / worktrees | Gas Town first; Ralph Orchestrator has worktree loops; Herdr hosts them. |
| Multi-vendor CLIs you already have | Gas Town presets > Ralph Orchestrator backends > Herdr (any binary). Cursor/Grok: Gas Town yes, Ralph Orchestrator unverified. |
| Subscription quota | **Missing.** None of the above. |
| Verifiability | Programmatic tests/CI, not TUI status. Ralph backpressure is the right idea; still verify yourself. |
| Maintained OSS | OpenHands / Goose / Beads / Herdr / OMC / Ralph Orchestrator pass the 60-day bar. Ralph TUI, Vibe Kanban, Aider, Roo do not. |

**Throw away:** same-session supervisor stacks, hand-maintained handoff rituals as the *architecture*, and `subsy/ralph-tui` as a greenfield bet (it is the right idea, frozen in May).

**Keep or re-buy:** a program loop (Ralph Orchestrator), a structured tracker (Beads), an always-on runtime (Herdr) if you want lid-close survival, and whatever thin quota rotator you already trust — because that last part is still yours.
