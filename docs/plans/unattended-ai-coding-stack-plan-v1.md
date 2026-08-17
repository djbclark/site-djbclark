# Unattended continuous AI coding — final OSS stack plan (v1)

| | |
|---|---|
| **Status** | Research complete — adoption plan, not yet executed |
| **Evidence date** | 2026-08-16 — GitHub figures via `gh api`; hands-on tests run that day |
| **Source package** | [`research/autonomy/`](../../research/autonomy/) (research handoff: requirements, verified findings, open questions, three external AI panel answers) |
| **Produced by** | Claude Fable 5 session, from a Claude Opus 5 research handoff |


Written 2026-08-16 by a Claude Fable 5 session that processed this package,
did the hands-on testing nobody had done (Q1), re-swept the field (Q8), and
decided Q2–Q7. Everything below is split into **[TESTED]** (I ran it on this
machine today) and **[DOCS]** (taken from documentation/source reading/API
data, not executed). Test commands are included so every claim can be re-run.

---

## TL;DR

**Adopt the stack: beads + ralph-orchestrator (as a dumb while-loop only) +
a ~100-line judge you write (wired into ralph's hook system, which I
verified can genuinely block completion) + a cswap quota gate + Herdr as
host.** Trial **zeroshot** in parallel as the per-task engine — it is the
one project that ships your verification doctrine as a product, and the
prior sweep under-weighted it.

The single most important hands-on result: **ralph-orchestrator's marketed
"backpressure gates" are self-report.** I reproduced your exact failure mode
— a clean `COMPLETED` on work whose test suite fails — in three different
configurations. The redemption is that its *hooks* system (un-marketed) runs
real commands and genuinely refuses completion. The loop is adoptable; its
verification story, as marketed, is not. Configuration decides which one you
get.

---

## 1. What I verified hands-on (Q1) — ralph-orchestrator v2.10.1

Test rig: throwaway git repo, a stub "agent" (shell script) as
`backend: custom`, a real test suite that always fails, a marker file to
detect whether ralph ever executes configured gate commands. Zero LLM quota
burned. Binary: release `v2.10.1` aarch64 (what an adopter installs).

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Fresh process + fresh context per iteration | **[TESTED] TRUE** | 3 iterations → 3 distinct PIDs (25047/25054/25061); prompt re-delivered via new temp file each time; no resume/continue/session flags anywhere in `crates/ralph-adapters/src/cli_backend.rs` |
| 2 | "Backpressure gates reject work failing tests" | **[TESTED] FALSE as marketed** | Gate = substring match on the agent's own output (`event_parser.rs:326`: `payload.contains("tests: pass")`). Stub agent that did nothing, in a repo with failing tests, emitted `tests: pass` → loop completed cleanly; the real test command was **never executed** (marker file empty) |
| 3 | `backpressure.gates` config with real commands | **[TESTED] DEAD YAML** | The repo's own reference `ralph.yml` declares command gates (`cargo test --all`); **no code parses that section** — no `Backpressure` config struct exists; the binary silently swallows it and never ran my `./test.sh` |
| 4 | Completion authority | **[TESTED] the agent's magic string** | Agent emitting honest `tests: fail` evidence **plus** `LOOP_COMPLETE` → loop terminated "All tasks completed successfully". The promise outranks even honestly-failing evidence. This is your `COMPLETED`-on-wrong-work burn, reproduced on demand |
| 5 | Honest-fail without promise | **[TESTED] loop keeps working** | `tests: fail` with no promise → build.done blocked from subscribers, loop iterates to max_iterations. The string-gate does function as *work-continues* pressure when the agent is honest |
| 6 | Lifecycle hooks as a REAL gate | **[TESTED] TRUE — the important one** | `hooks: events: pre.loop.complete: [{command: ["./test.sh"], on_error: block}]` → ralph **executed the real command** (marker file written) and refused the lying agent's completion: `Error: Lifecycle hook 'real-gate' blocked orchestration at 'pre.loop.complete': hook exited with code 1`. Caveat: block = hard error stop, not "send the agent back to work" |
| 7 | Kill mid-run / resume | **[TESTED] WORKS** | `kill` during iteration 2, then `ralph run --continue --loop-id <id>` resumed at iteration 2 and ran to the cap. Requires `.ralph/agent/scratchpad.md` to exist (real agents are instructed to write it; my stub wasn't — I created it manually and resume then worked) |
| 8 | Backend rotation across your CLIs | **[TESTED] PARTIAL** | Valid backends: claude, kiro, kiro-acp, gemini, codex, forge, amp, copilot, opencode, pi, custom. **No Grok, no Cursor** (both external AIs were right to refuse the claim). The `custom` escape hatch works — my stub ran through it — so wrapping `cursor-agent`/`grok` is possible but is your glue, not their feature |
| 9 | Beads integration | **[DOCS→SOURCE] NOT REAL** | `crates/ralph-core/src/task.rs`: "Lightweight task tracking system **inspired by** Steve Yegge's Beads" — an internal beads-lite; nothing invokes `bd` |
| 10 | Quota awareness | **[SOURCE] NONE** | No subscription-window, usage-limit, or rate-limit handling in any crate (one unused API error enum constant) |
| 11 | Release hygiene | **[DOCS] STALLED** | Last release v2.10.1 = Jun 23; daily commits since (HEAD Aug 16). Docs at HEAD have drifted from the released binary (HEAD docs say `custom_command:`; the binary requires `cli.command:`). Unknown config sections are silently accepted — a typo'd gate config fails silent, not loud |

**Q1 bottom line:** the *loop* is real and solid (fresh context, resume,
custom backends, real blocking hooks). The *verification marketing* is
exactly the kind of thing you neuter-test for, and it fails the neuter test:
the gate that "rejects work failing tests" never runs the tests. Adopt the
loop; supply the verification yourself via hooks (design in §4).

## 2. Q2 — solo-maintainer risk: acceptable, with the role demoted

The hands-on results reframe this question. The risk of one-maintainer
software isn't only abandonment — it's that marketed features (backpressure
"gates", "beads integration") turn out to be aspirational, and there's no
community mass generating the bug reports that would have surfaced that. You
found this out in an afternoon of testing; 3.1k stars hadn't.

**Decision: acceptable ONLY with ralph demoted to "the while-loop".** In the
recommended configuration it holds no verification authority (hooks you
write do), no task state (beads does), no process persistence (Herdr does),
and no quota logic (your gate does). Under those conditions the abandonment
failure mode is benign: MIT Rust binary that keeps working, and every asset
that matters — beads data, judge script, task specs, quota gate — moves
unchanged to any other loop. After testing I'd put replacing ralph with a
30-line supervised shell loop at under a day of work. That is the fallback,
and it's a better one than "swap in OpenHands/paperclip", which are
wrong-shaped for terminal-native subscription CLIs (web platform / dollar
budgets respectively — unchanged from the prior sweep).

## 3. Q3 — Maestro vs ralph-orchestrator: ralph, decided by evidence

What decided it:

- **I bolted real verification onto ralph in ~10 lines of YAML plus a shell
  script, and watched it refuse a lying agent** [TESTED]. The prior
  session's rationale — "you can bolt a quota sleep onto a loop more easily
  than you can bolt real verification onto one" — is now half-proven: the
  verification bolt-on is demonstrated. Nobody has demonstrated the
  equivalent for Maestro's self-scored `<!-- maestro:progress -->` [DOCS].
- Maestro's one enviable feature, subscription-aware auto-resume, is
  Claude-first and its Auto Run controller dies on app restart per its own
  docs [DOCS]. Your cswap gate (§5) covers the same need vendor-neutrally
  and is ~50 lines.
- Maestro is Electron + AGPL-3.0 against your terminal-native requirement;
  no Gemini backend.
- One point honestly in Maestro's favor from today's API check [DOCS]: its
  contributor spread (4348/649/465/145/123) is much healthier than ralph's
  (457/16/10/6). If you weighted maintenance above shape, Maestro would win
  Q2 while losing Q3. I weight shape higher because the loop is demoted to
  replaceable plumbing (§2).

## 4. Q4 — the verification judge: build it as a ralph hook + CI check

**Placement decision: inside the loop as a blocking completion gate, and
again as CI on the PR.** Not post-hoc — a false `COMPLETED` must never be
minted in the first place (tested: `pre.loop.complete` + `on_error: block`
does exactly this). CI on the PR is the second, independent instance of the
same check, so a judge bug can't silently pass both.

Concrete design (an afternoon):

```bash
#!/usr/bin/env bash
# judge.sh — refuses completion unless tracker, git, and tests agree.
# Wired as: hooks.events.pre.loop.complete -> on_error: block
# Inputs: TASK_ID (bd id), TEST_CMD, EXPECT_DIFF=(yes|no)
set -euo pipefail
fail() { echo "JUDGE REFUSE: $1" >&2; exit 1; }

# (a) tracker: closed, with a real close reason
state=$(bd show "$TASK_ID" --json)
jq -e '.status == "closed"' <<<"$state" >/dev/null || fail "bd $TASK_ID not closed"
reason=$(jq -r '.close_reason // ""' <<<"$state")
[ "${#reason}" -ge 20 ] || fail "close reason empty/placeholder"

# (b) git: diff presence matches task type, and the work is committed
if [ "$EXPECT_DIFF" = yes ]; then
  [ -n "$(git log --oneline @{u}..HEAD 2>/dev/null || git log --oneline -1)" ] \
    || fail "no commits for a code task"
else
  [ -z "$(git status --short)" ] || fail "dirty tree on a research-only task"
fi

# (c) tests: run them YOURSELF; never parse the agent's transcript
$TEST_CMD || fail "test command failed"

echo "JUDGE PASS: tracker+git+tests agree"
```

Notes from testing and source reading:

- The hook's failure hard-stops the run rather than re-prompting the agent
  [TESTED]. That's correct behavior for you: a refused completion is a
  human-attention event (or an outer-loop requeue), not something to let the
  same agent argue its way past.
- Keep the agent-facing convention of emitting `tests: pass` evidence anyway
  — [TESTED] honest `fail` evidence keeps the loop working instead of
  completing, so the string layer adds useful *pressure* even though it must
  never be the *authority*.
- Nothing OSS ships the three-way reconciliation. The closest shipped thing
  is **zeroshot** (§6): true executor/verifier separation with isolated
  validator context, program-side command proofs, and a fail-closed
  git-pusher [SOURCE — read, not executed]. Its validators are still LLM
  judges, though — your deterministic judge stays yours either way, and it
  is deliberately boring: three subprocess calls and string checks, no LLM.

## 5. Q5 — the quota glue: a pre-flight gate, park-don't-switch

**Decision: a small gate script consulted at iteration boundaries, plus an
outer wrapper for multi-hour parking. No vendor failover mid-task.**

- **Where:** both places, same script. (1) `hooks.events.pre.iteration.start`
  with `on_error: block` so a capped window stops the loop between agent
  spawns — hook blocking is [TESTED] at pre.loop.complete and [DOCS] at
  pre.iteration.start (same mechanism; verify once when wiring). (2) The
  Herdr-hosted wrapper (`until ralph run …; do cswap-wait; done`) owns long
  parking, because a blocked hook exits the run rather than sleeping.
- **Reads `cswap list` only.** Percent = USED. Never `aiuse --json`
  (pace projection). Auto-rotation stays off — `cswap auto` is blind to
  Fable entitlement and only `djbclark@gmail.com` has Fable. The gate may
  *suggest* an account switch in its refuse message; it must never perform
  one.
- **Thresholds:** refuse new iterations at ≥80% of the 5h window (a single
  Fable-driven iteration measurably moves the 5h meter tens of points —
  your 56→87% observation), park until the reset time cswap prints.
- **No cross-vendor failover mid-task.** A model swap mid-task is a prose
  fallback chain, which your own doctrine rejects (the A-failed-skip-to-C
  lesson). Vendor diversity belongs at *task assignment* (this repo's loop
  runs codex backend today, that one claude), not inside a task.
- **claudexor: read, don't adopt** [DOCS: 1373 commits vs next human 7 —
  confirmed today]. Its `oauth/usage` polling and continuation-packet ideas
  are worth stealing into the gate if you later want proactive polling;
  cswap already gives you the reading locally.
- Flag from today's sweep [DOCS, blog-grade, verify on your own account]:
  Anthropic reportedly meters headless Claude Code separately from
  interactive since Jun 15, 2026. If your plan shows separate pools,
  loops may be cheaper against your interactive window than assumed —
  check `cswap list` during a headless run before tuning thresholds.

## 6. The zeroshot finding (Q8's headline) — trial it as the per-task engine

`the-open-engine/zeroshot` was surfaced-but-never-examined by the prior
session. Examined today:

- **Maturity** [API-verified]: MIT, 1.7k stars, commits Aug 14, **two
  ~equal real maintainers** (224/208 commits) + company (The Open Engine) +
  real CI and fast releases (v6.40.0 Aug 14). Small but *not* solo — unlike
  ralph, claudexor, NEEDLE, paseo.
- **Architecture** [SOURCE-read]: per-task executor–verifier clusters.
  Validators run with isolated context and must reproduce reported
  failures; a `cmdproof` mechanism executes/verifies exact commands
  program-side; `--pr`/`--ship` flows have a git-pusher that "fails closed"
  on quality-gate evidence. Worktree isolation default; crash-safe SQLite
  ledger; `zeroshot resume`. Providers: Claude, Codex, Gemini, OpenCode,
  Pi, Copilot, Kiro (no Grok/Cursor). Issue sources: GitHub/GitLab/Jira/
  Linear (no beads — glue needed).
- **Hands-on caveat** [TESTED]: `npm install -g` **failed on this machine**
  (node 26.7; better-sqlite3 has no prebuild and source build failed). It
  needs a pinned node 22/24 LTS. I could not run it end-to-end today, so
  its behavioral claims are **source-read, not behavior-verified** — apply
  the same skepticism I applied to ralph until you've mutation-tested it.
- **Shape caveat:** it is a per-task engine (`zeroshot run <issue>`), not a
  continuous loop, and its multi-validator workflows spend more of your
  quota per task (STANDARD = planner + worker + 2 validators).

Why it matters: it is the only actively-maintained project whose core
design principle is literally yours ("The agent that wrote the code
shouldn't be the one that says it works"), and the prior package's
"nobody shipped independent verification" is now **partially false**.

## 7. Q6 / Q7 — multi-repo and where work lands

- **Multi-repo: N independent loops, one per repo.** One beads db + one
  loop + one worktree lane per repo, all hosted in Herdr panes. No beads
  federation initially; revisit only when a real cross-repo dependency
  hurts. gastown stays un-adopted (decelerating [API: Jul 23 last main
  commit], Mayor-shaped). AllBeads is dormant [API-verified today: 8 stars,
  one contributor, last commit Mar 20] — drop it from consideration.
- **Work lands as PRs from worktrees**, judge as blocking hook + the same
  judge re-run as a required CI check. Merging stays yours. `autoCommit`
  stays off.
- **gh-aw: not now** [DOCS]. Its safe-outputs design is the right shape,
  but it executes on Actions runners billed against Copilot/API — against
  requirement #2 — and it had a run of retired releases over billing bugs.
  Copy the *pattern* locally (read-only agent + separate scoped writer);
  revisit if a public/low-stakes repo ever justifies Actions billing.
- **Kiro Crew** (new since the panel, launched Aug 4) [API-verified]:
  AWS-backed, Apache-2.0, genuinely distributed team, 143 commits/wk —
  and hard-wired to `kiro-cli` + Kiro sign-in, one month public. Wrong
  vendor for you today; the strongest *watch* item on the list. If it
  grows real multi-vendor ACP support, it becomes a serious contender.
- Also checked today: paseo = one human (4388 vs 26) + non-OSI license →
  out on two counts. NEEDLE = right shape, 16 stars, one human → read for
  design only. beads' Dolt storage: fully landed, embedded by default,
  documented migration path → accept it; don't detour to the frozen
  beads_rust fork.

## 8. The adoption sequence

Phase 0 — prep (an hour):
```bash
brew install node@24                    # only if/when trialing zeroshot
bd --version                            # already installed; keep current
# vendored ~/src/vendor/ralph-tui: delete or mark deprecated — stalest
# thing in its category [API: last commit 2026-05-13]
```

Phase 1 — one repo, supervised (a day):
```bash
# in the repo:
bd init                                  # beads = the only task truth
curl -LO https://github.com/mikeyobrien/ralph-orchestrator/releases/download/v2.10.1/ralph-cli-aarch64-apple-darwin.tar.xz
tar xf ralph-cli-aarch64-apple-darwin.tar.xz   # or: build HEAD from source — releases are stalled (§1.11)
# write ralph.yml: backend claude|codex|gemini; max_iterations ~10;
#   hooks: pre.loop.complete -> ./judge.sh (on_error: block)     # §4
#          pre.iteration.start -> ./cswap-gate.sh (on_error: block)  # §5
# write judge.sh + cswap-gate.sh (~150 lines total)
# MUTATION-TEST YOUR OWN WIRING before first real run:
#   stub agent + failing tests must be REFUSED (repeat my §1 rig —
#   a judge that has never refused anything is not known to work)
```

Phase 2 — unattended, still one repo (a week of evenings):
```bash
herdr                                    # loop lives in a Herdr pane:
until ralph run -c ralph.yml; do ./cswap-wait.sh || break; done
# land 5–10 real beads tasks as PRs; verify each with YOUR protocol
# (bd show / git log / gh pr view), never the loop's status line
```

Phase 3 — scale out + trial the alternative (in parallel):
```bash
# repos 2..N: repeat Phase 1 config (it's three files)
# zeroshot trial on node 24: one well-scoped bead ->
#   zeroshot run "<bead title + acceptance criteria>" --pr
#   then mutation-test ITS gates the same way before trusting them
```

Decision point after Phase 3: if zeroshot's verification survives your
mutation testing and the per-task quota cost is tolerable, promote it to
the per-task engine (outer loop: `bd ready` → `zeroshot run --pr`) and
retire ralph to the repos where cheap single-agent iteration wins.

## 9. Honest risks, by component

| Component | Risk | Mitigation / fallback |
|---|---|---|
| ralph-orchestrator | Solo author; releases stalled since Jun 23; marketed features ≠ real features (proven); silent config swallowing | Demoted to dumb loop; all authority in your hooks; mutation-test wiring on install and after every upgrade; fallback = 30-line supervised shell loop, <1 day |
| beads | Dolt operational surface; Yegge-project churn | Data is exportable (JSONL export, `bd dolt push`); the graph model is the asset; worst case the frozen beads_rust reads your data shape |
| judge.sh / cswap-gate.sh | It's bespoke code in a plan that says "no bespoke tooling" | ~150 lines total, zero dependencies, and it encodes the ONE thing (§ "the one thing to keep") both external AIs confirmed nobody ships. This is the irreducible custom remainder |
| zeroshot | Young company; 2 maintainers; validators are LLMs; install friction on node 26; version numbers are a build counter | Trial-gated adoption (Phase 3); pin node LTS + package version; your judge remains the outer authority regardless |
| Herdr | None new — already your infrastructure | It hosts processes; it never becomes the orchestrator |
| Quota | No OSS owns rolling windows (re-confirmed today); your gate is load-bearing | Park-don't-switch keeps it simple; thresholds tunable from cswap history |

## 10. What I did NOT verify (so you don't have to discover it)

- Maestro: everything about it remains [DOCS]. I did not install it.
- zeroshot: behavior unverified end-to-end (install failed on node 26);
  all architecture claims are from source reading of today's HEAD.
- ralph at HEAD: I tested the v2.10.1 release binary. HEAD has ~8 weeks of
  unreleased changes; re-run the §1 rig if you build from source.
- `pre.iteration.start` blocking: mechanism verified at a different hook
  point; verify at this one when wiring the quota gate.
- Hook `suspend_mode: wait_for_resume` (config hints a hook can suspend
  rather than kill): untested; if it works it could replace the outer
  wrapper's parking role — worth 20 minutes with the §1 rig.
- The separate-headless-metering claim (§5): blog-sourced; check your own
  cswap during a headless run.
- Herdr repo stats: still relayed-from-Grok, never API-verified; irrelevant
  to adopt/not-adopt since you already run it.

## Sources (today's fresh-research additions)

- [Kiro Crew launch coverage](https://dev.to/aws-builders/introducing-kiro-crew-awss-open-source-ai-agent-orchestrator-1e63) · [kirodotdev/KiroCrew](https://github.com/kirodotdev/KiroCrew) (API-verified)
- [the-open-engine/zeroshot](https://github.com/the-open-engine/zeroshot) (API + source verified; install attempted)
- Headless-vs-interactive metering claims: [TrueFoundry](https://www.truefoundry.com/blog/claude-code-limits-explained) · [CloudZero](https://www.cloudzero.com/blog/claude-code-agents/) · [claudefa.st](https://claudefa.st/blog/guide/development/higher-usage-limits) (blog-grade, unverified)
- All GitHub maturity numbers in this file: `gh api` on 2026-08-16 using the
  02-verified-findings method (default-branch commit + contributor
  distribution; never `pushed_at`).
