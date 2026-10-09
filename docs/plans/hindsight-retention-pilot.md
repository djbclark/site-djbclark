# Hindsight retention pilot: current state and operator guide

- **Issue:** [#129](https://github.com/djbclark/site-djbclark/issues/129)
- **Status (2026-10-09):** **closed out, not running.** Hindsight was retired
  2026-09-30 and removed from the ops repos 2026-10-03. The pilot this issue
  describes cannot run any more, and nothing in it needs operator action.
- **Recommendation:** close #129 as superseded. The pilot's policy questions
  now live in [memory-architecture-v2.md](memory-architecture-v2.md) §4.2
  (the candidate gate, design only).

This file replaces the pilot plan of the same name that commit `6ad56e2`
deleted. It records what happened to the pilot and how to do each of its jobs
today, so the issue's operator guide does not send anyone to commands that no
longer exist.

## 1. What happened

| Date       | Event                                                                                                                                                                                                       |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-08-08 | Pilot guide written (the #129 issue body): candidate ledger, `/m` command, auto-retention off, shared bank empty by design, zero candidates in the ledger.                                                    |
| 2026-08-10 | [#139](https://github.com/djbclark/site-djbclark/issues/139) folds the pilot into the combined architecture and renames the command `/z`.                                                                  |
| 2026-08-13 | [memory-architecture-v2](memory-architecture-v2.md) accepted; Hindsight kept "until a same-corpus comparison".                                                                                              |
| 2026-09-30 | Operator retires Hindsight (token cost, host load, frequent breakage). Basic Memory becomes the memory search service. Commit `83724da` adds `hindsight_enabled: false` and shuts the LaunchAgents down. |
| 2026-10-03 | Operator: remove Hindsight from everywhere. Commit `6ad56e2` deletes the role, playbook, recipes, inventory group, scripts, tests and this file's predecessor; `c3f5c59` rewrites the architecture plan. |

No pilot checkpoint or 30-day promotion-gate result was ever recorded in this
repo. The pilot produced no evidence for or against automatic retention.

## 2. Current state, checked 2026-10-09

| Pilot component                                              | State now                                                                                                    |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Hindsight API on `127.0.0.1:8888`                            | Gone. Nothing listens on 8888. Ports 8888 and 5432 are released in `registry/ports.yml`.                      |
| `~/.hindsight/` (ledger script, `claude-code.json`, archive) | Deleted 2026-10-03.                                                                                          |
| Candidate ledger `hindsight_memory_candidates.py`            | Deleted from `bin/` in `6ad56e2`, with its tests.                                                            |
| `/m` Hermes plugin, `/z` skill                               | Removed (`/z` on 2026-09-30).                                                                                |
| Shared-bank policy watchdog, inactivity reminder             | Removed with `~/.hermes/scripts/hindsight-*` on 2026-10-03. Neither was still registered in Hermes cron.     |
| Hermes `auto_retain`, Claude `autoRetain`                    | Moot: the Hindsight provider is removed from Hermes and the plugin from Claude Code and the other TUIs.       |
| S1 lossless evidence store                                   | **Kept; it was never Hindsight.** Renamed to `bin/s1_evidence.py` and friends, data in `~/.local/share/s1-evidence/`. |
| Memory search                                                | Basic Memory over `~/ops/site-private/memory`, shared MCP server at `http://127.0.0.1:18796/mcp`.             |

The pilot's safety posture survives in a different form. There is still no
automatic transcript-to-memory promotion, and nothing writes durable memory
without a reviewable Git commit.

## 3. Operator guide: doing the pilot's jobs today

Each numbered step of the old guide maps to one of these.

1. **Propose a durable fact** (old steps 1 and `/m add`). Write one Markdown
   file per fact under `~/ops/site-private/memory/` with the usual
   frontmatter, add a one-line pointer to `MEMORY.md`, then
   `git pull --rebase`, commit and push. Any agent can do this on request.
2. **Review candidates** (old steps 2 and 3, `/m review|approve|reject`). The
   review is the Git history: `git -C ~/ops/site-private log -p -- memory/`.
   Reject a fact by deleting or correcting its file in a new commit.
3. **Inspect before promoting** (old step 4). Read the file and its diff. There
   is no separate payload any more: the note is the durable record.
4. **Retain explicitly** (old step 5). The commit is the retain. No shared bank
   exists, so the "never write `hermes-shared` automatically" rule has nothing
   left to guard.
5. **Recall from another client** (old step 6, `/m recall`). Use the
   `basic-memory` MCP tools (`search_notes`, `read_note`) from Claude Code,
   Codex, Antigravity or Hermes, or `bm tool search-notes` from a shell.
   A semantic hit is not proof a note exists; confirm with an exact read.
6. **Check health** (old `/m status`). Run `just basic-memory-mcp-status` and
   `just basic-memory-mcp-check` here. After any Basic Memory upgrade or config
   change, `git -C ~/ops/site-private status --short` must show no modified
   files.
7. **Recover exact past conversation detail.** Use the S1 store, not memory:
   `bin/s1_search.py search ...` (`stats`, `neighbours` for context).

The pilot's admission rules still apply to anything written into memory. Good
candidates are confirmed decisions, stable conventions, explicit preferences
and verified facts with a source. Never write secrets, credentials, personal
data, raw logs or diffs, speculation or temporary plans.

## 4. Confirming nothing is left

These read-only checks should all come back empty or "No such file":

```bash
lsof -nP -iTCP:8888 -sTCP:LISTEN
launchctl list | rg -i hindsight
ls -d ~/.hindsight ~/.hermes/hindsight
ls ~/.hermes/scripts | rg -i hindsight
rg -il hindsight ~/.claude/settings.json ~/.codex/config.toml
```

`~/.pg0/installation` is intentionally kept: it is the restore toolchain for
the archived Hindsight database dump.

## 5. If Hindsight ever comes back

Do not restore the deleted role from history and turn it on. Start from
memory-architecture-v2 §4.2 and §8.1: the gate is meant to be one SQLite
workflow in front of Git canon, and any semantic-memory product enters only
through a same-corpus comparison against Basic Memory and S1. The hook
invariants that broke during the pilot are recorded in site-private memory
under "Retired Hindsight leftovers migration".
