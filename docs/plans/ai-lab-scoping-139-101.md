# Combined AI track (#139) and reuse-first engineering (#101): scoping

- **Issues:** [#139](https://github.com/djbclark/site-djbclark/issues/139),
  [#101](https://github.com/djbclark/site-djbclark/issues/101)
- **Date:** 2026-10-09
- **Status:** scoping only. Nothing was installed, configured or built.
- **What this is:** an inventory of each piece the two issues name, as it
  exists today, the overlaps between them and with later work, and a proposed
  order of work.

## 1. What changed since the issues were written

#139 was written 2026-08-10 and #101 2026-08-06. Since then:

1. **Hindsight is gone.** Retired 2026-09-30, removed 2026-10-03. The `/z`
   skill was removed 2026-09-30. #139's Phase 5 (`/z` to Hindsight promotion)
   has no target any more. See
   [hindsight-retention-pilot.md](hindsight-retention-pilot.md).
2. **Basic Memory is adopted** as memory search over `site-private/memory`,
   served by one shared MCP server (`roles/basic_memory_mcp`).
3. **Memory architecture v2 is accepted** ([memory-architecture-v2.md](memory-architecture-v2.md)).
   It owns the memory half of #139: S1 evidence, Git canon, Basic Memory as a
   projection, and a candidate gate that is design only (§4.2).
4. **A bounded multi-vendor worker harness exists.** `acp-run` and
   `acp-dispatch` in `~/src/djbclark-ade` send one task to any of about ten
   agent CLIs with scoped write permissions, a timeout and a report file.
5. **A verifier design exists.** The
   [unattended AI coding stack plan](unattended-ai-coding-stack-plan-v1.md)
   showed that ralph-orchestrator's marketed gates are self-report and that
   its lifecycle hooks can run a real command that blocks completion. Its
   "~100-line judge" is not built.
6. **Skills are consolidated in Git.** Hand-maintained skills live in
   `skills/` here and in `~/src/djbclark-ade`, reached by every TUI through one
   symlink chain (`skills/README.md`). That is most of #99's "Git-backed
   canonical library", without its validation, provenance or release parts.
7. **Prime Agent 0.7.1 is installed** (`/opt/homebrew/bin/prime-agent`). It has
   `--mode json|rpc|acp|daemon`. It is not one of the agents `acp-run` knows.

## 2. Inventory

| Piece (issue)                                  | What exists today                                                                                                                       | State                    |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| Git/OKF canon and checkpoints (#139 P0)        | `AGENTS.md` files, `site-private/memory` notes, v2 §4.3. Worktrees and cow pastures for isolation.                                     | **Exists**               |
| Benchmark task suite and run schema (#139 P0)  | Nothing.                                                                                                                                | **Missing**              |
| Deterministic verifier (#139 P1)               | `bin/verify_facts.py` checks mined facts, not code. The judge in the unattended-stack plan is designed, not built.                      | **Design only**          |
| Independent fresh-context review (#139 P1)     | `adversary` teammate (required before a PR in agent teams), code-review skills, CodeRabbit, `acp-run` to other vendors, `bigteam`.     | **Tooling exists, unmeasured** |
| RLM-style external context (#139 P2)           | Nothing named RLM. Pieces that query a corpus outside the prompt: `bin/s1_search.py`, `book-kb`, graft, Basic Memory.                   | **Pieces exist**         |
| Prime Agent bounded worker (#139 P3)           | Binary installed, ACP and RPC modes available, no config or wrapper here. A site-private note marks it optional.                       | **Installed, unused**    |
| Basic Memory as working context (#139 P4)      | Adopted 2026-09-30; v2 §8.4.                                                                                                            | **Exists**               |
| `/z` ledger and Hindsight promotion (#139 P5)  | Removed. v2 §4.2 gate is the replacement design.                                                                                        | **Superseded**           |
| Self-refinement / autoresearch (#139 P6)       | Nothing.                                                                                                                                | **Not started, by design** |
| Reuse-first skill (#101)                       | Hermes skill at `~/.hermes/skills/software-development/reuse-first-agent-engineering/` with seven reference files. No Agent Skills copy for Claude Code or the other TUIs. | **Hermes only**          |
| Reuse-first plans (#101)                       | [ai-agent-reuse-first-implementation-plan-v1.md](ai-agent-reuse-first-implementation-plan-v1.md), [agent-skill-library-strategy-v1.md](agent-skill-library-strategy-v1.md). Unchanged since 2026-08-06. | **Stale**                |
| Reuse baseline metrics (#101)                  | Nothing.                                                                                                                                | **Missing**              |
| Canonical skill library (#99, via #101)        | Consolidated in Git, see section 1 item 6.                                                                                              | **Mostly done, informally** |
| Reuse-first behaviour in agent rules           | `~/AGENTS.md` already requires graft/symbol tools before grep, and web search before local trial and error.                            | **Partly enforced by rules** |

## 3. Overlaps

1. **One verifier, three documents.** #139 Phase 1, the unattended-stack
   plan's judge, and `docs/fact-verification.md` all want a command that
   checks real evidence instead of a self-report. Build one judge and use it
   from a ralph hook, from `acp-dispatch`, and from the benchmark.
2. **The bounded worker is already built.** #139 Phase 3 asks for a fixed
   budget, a disposable worktree, no deploy authority and structured output.
   `acp-dispatch` with `--perm scoped:` and `--timeout` in a cow pasture is
   that. Prime Agent needs adding as one more ACP agent, not a new harness.
3. **#139's memory phases duplicate v2.** Phases 4 and 5 should point at
   memory-architecture-v2 and drop `/z` and Hindsight.
4. **#101's library step is #99, and #99 is mostly done.** What remains is
   validation, provenance and release tooling over the existing Git skills.
5. **#101's reuse assessment belongs in the benchmark report.** #139 already
   says so. One run record should carry tests, verifier result, review
   findings and the reuse decision.
6. **Independent review is spread over four tools.** The benchmark should pick
   one review path so results are comparable.
7. **#37 stays deferred.** Nothing here shows a coordination bottleneck (see
   [agent-fleet-migration-assessment.md](../reference/agent-fleet-migration-assessment.md)).

## 4. Proposed sequence

Each step has an exit gate. A step that fails its gate stops the track there.

| Step | Work                                                                                                                                                               | Exit gate                                                                                  | Rough effort |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ | ------------ |
| S0   | Issue housekeeping: correct #139's Hindsight, `/z` and #92 text; close #92 as superseded; mark #99 for what remains.                                                | Issues match the repo.                                                                     | 1 hour       |
| S1   | Benchmark fixture: 8 to 12 real tasks from #139 Phase 0 in a throwaway repo, and a JSONL run schema that extends the `acp-dispatch` report.                        | One baseline run that a second run reproduces.                                             | 1 to 2 days  |
| S2   | Build the judge once: real tests plus hidden tests, exit code is the verdict. Wire it into `acp-dispatch check` and a ralph `pre.loop.complete` hook.               | It blocks a planted false "done" in both places.                                           | 1 day        |
| S3   | Reuse assessment: port the Hermes skill to an Agent Skills `SKILL.md` for every TUI, and make its decision record a required field of the run schema.               | A measured duplicate-implementation baseline over the S1 tasks.                            | 1 day        |
| S4   | Prime Agent as an `acp-run` agent (`prime-agent --mode acp`), run over the benchmark against the S1 baseline.                                                      | A measured improvement, or Prime is dropped.                                               | 0.5 to 1 day |
| S5   | RLM-style context packets from S1 search and Basic Memory, compared with plain prompting on the long-context tasks. Only if S1 to S4 show a context bottleneck.    | Better hidden-test results or lower context cost at the same quality.                      | 2 to 3 days  |
| S6   | The v2 §4.2 candidate gate. Only after S1 to S5.                                                                                                                    | v2's own gate criteria.                                                                    | per v2       |
| S7   | Self-refinement experiments, last and gated as #139 Phase 6 says.                                                                                                   | #139 Phase 6 rules.                                                                        | open         |

The continue, defer and stop thresholds in #139 (about 10 points better to
continue, under 5 points with more than 25 to 30 percent added cost to defer)
apply from S4 on.

## 5. Decisions this needs from the operator

1. Whether #139's body should be edited to reflect section 1, or a correction
   comment is enough.
2. Whether to close #92 now.
3. Where the Agent Skills copy of the reuse-first skill lives: `skills/` here
   (public) or `~/src/djbclark-ade`. Hermes's copy has seven reference files
   that must be checked for private content before either.
4. Whether Prime Agent is worth S4 at all, given the note that marks it
   optional.
