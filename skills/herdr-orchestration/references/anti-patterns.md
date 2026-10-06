# Anti-patterns (things that went wrong once, don't repeat)

- Trusting a sub-agent's "CI passes" / "verified" claim without checking —
  led to shipping-adjacent PRs with a real regression that a cosmetic-looking
  markdown-lint fix had glossed over.
- Writing "hand off to Agent N+1 the way this handoff to you was made" into a
  sub-agent's prompt — ambiguous enough to read as "use herdr yourself,"
  which the operator explicitly does not want. Say plainly: prepare your
  handoff (plan file + clipboard prompt per the existing protocol), the
  orchestrator will launch the next one.
- Re-enabling a disabled billing/credits toggle to get access to a better
  model, on the theory that "the user said make the best call" — that
  authority covers model/vendor/effort selection, not spend-control settings.
- Assuming a model name from an older plan/roster still exists — check the
  live picker.
- **Moving on while a sub-agent's PR sits unmerged "pending operator review."**
  With merge authority, the merge step is yours: review and merge the unit's
  PR before starting the next unit, or write down why not and when you'll
  revisit it (see ["Workflow per unit"](../SKILL.md#workflow-per-unit) steps 9-11). Otherwise PRs with no owner
  pile up unnoticed, foundational fixes included.
- **Trusting "local check passes" without confirming it actually ran
  everything.** A sub-agent's worktree missing supporting tools/venvs
  (`.ansible/collections`, `node_modules`, a `.venv-test`) makes its own
  check script *silently skip* the exact checks that matter (lint, format,
  test-collection) instead of failing — the sub-agent's "CI passes locally"
  report is then genuinely true of what ran, and still worthless. One
  session needed three separate fix-and-push rounds after a sub-agent's
  "done" report, because real CI kept finding things a from-scratch
  `just check` (run by the orchestrator, after actually installing the
  missing tools) would have caught in one pass. Before trusting a green
  local run, either reproduce it yourself with the full toolchain installed,
  or at minimum grep its output for "skip"/"not installed" next to anything
  load-bearing.
- **Closing your own tab/pane during a bulk cleanup loop.** Check each target
  against `$HERDR_TAB_ID`/`$HERDR_PANE_ID` before closing it. The
  `~/.herdr-wrapper/bin/herdr` wrapper and the `orc` naming convention exist
  to stop self-closure; don't remove either without replacing that protection.
- **Not reading a new script's own logic just because it has passing
  tests.** A sub-agent's new notification script called a CLI subcommand
  that doesn't exist (silently a no-op, `check=False`) instead of the one
  actually confirmed working earlier in the same session, and separately
  had a guaranteed false-positive bug (comparing its own containing repo's
  overall latest release against an unrelated pinned tag it forgot to
  exclude) — neither one was caught by its own tests, because the tests
  were written by the same pass that missed the bugs. Read new
  orchestrator-facing code (notifications, checks, anything meant to fire
  unattended later) line by line once, independent of its test suite.
- **Backticks in a double-quoted `herdr agent prompt "..."` string get
  shell-expanded by the orchestrator's own Bash tool before Herdr ever sees
  them** — double quotes do not suppress command substitution. A prompt
  containing literal code examples like `` `codexbar --version` `` or
  `` `gh issue create --repo <owner>/<repo>` `` gets those fragments
  actually *executed* in the orchestrator's own shell first, and the
  sub-agent receives whatever that command's real stdout/stderr (or a
  syntax error, for a placeholder like `<owner>/<repo>`) happened to be,
  substituted in place of the intended literal text — not the example
  itself. This corrupted a real prompt once; the sub-agent still completed
  the task correctly by inferring intent from surrounding context, but that
  was luck, not something to rely on. Fix: single-quote the outer string
  when the prompt body contains backticks (loses `$VAR` expansion, which a
  literal prompt string rarely needs anyway), or escape every backtick as
  `` \` ``.
