/baton

You were woken by `fleet-watch` (`upstream-pr` check) because someone other than the
operator acted on one of the operator's open upstream pull requests. **Prepare a
response and stop.** The event is at the end of this brief ("Event"). Operator
decisions (2026-10-16): autonomy is "prepare and stop"; nothing goes to upstream
without the operator's explicit go.

## Standing rules

1. **One upstream PR is open at a time** (`one-upstream-pr-open-at-a-time`). Never
   open a PR, never offer the next one.
2. **Nothing outward-facing without the operator's explicit go.** Never post a
   comment, review, reaction or PR edit on `cfengine/*` or `NorthernTechHQ/*`.
   The only push you may make is to the **fork** (`origin` = `djbclark/core`), and only
   under item 8 of "Steps".
3. Read `~/src/cfengine-all/AGENTS.md` (the upstream review gate, the code quality
   bar, "verify by running") and `~/src/cfengine-core/AGENTS.md`, then the Tier 1
   pointer that `/baton` finds. Upstream readers are expert C programmers: no
   ELI5 text in anything meant for upstream (`upstream-texts-audience-no-eli5`).
4. House rules: `rg` always with a path, `gsed` never `sed`, GNU `g*` tools where BSD
   differs, long commands with `run_in_background`, builds and tests only through
   `~/ops/site-private/bin/bg` (full path), never `pkill -f`.

## Steps

1. `/baton` is the first line above: follow the Tier 1 reader protocol, state a
   resume plan in one short paragraph, then continue. This is an unattended run:
   never end on a question (the delivery contract below says how to report a block).
2. Read what the reviewer wrote, all of it, not only the event's first 400 characters:
   `gh api repos/<repo>/pulls/<n>/reviews`, `gh api repos/<repo>/pulls/<n>/comments`
   and `gh api repos/<repo>/issues/<n>/comments` (read-only calls; use `--paginate`).
   An issue event has no `pulls` endpoints: read its issue comments only, and if it
   asks for no code change, skip to item 9.
3. Check the checkout: `git -C ~/src/cfengine-core status --short`. Proceed only if it is
   empty apart from `tests/asan-check/Makefile`. Otherwise another session is
   working there: make no change, `~/.local/bin/hermes-ping "cfengine-core: <repo>#<n>
   not prepared, checkout is dirty: <paths>"`, and finish with a `BLOCKED:` report.
4. Note the branch you start on (`git branch --show-current`) and **return to it at the
   end**, other sessions share this checkout. Check out the PR's head branch (the
   Event section names it; it lives on `origin`, the fork):
   `git fetch origin <branch> && git switch <branch>`. If the head branch is not on
   `origin`, stop with a `BLOCKED:` report.
5. Apply the change the reviewer asked for. If the suggestion looks mistaken (wrong
   API, changes behaviour, fails to build, contradicts upstream conventions), **do not
   change the branch and do not push**: write the analysis into the reply draft
   instead, with the evidence (the command you ran and its output).
6. Rebuild as the repo's `CLAUDE.md` says ("Building here"), through
   `~/ops/site-private/bin/bg`. Keep the two macOS gotchas in mind: `cf-agent` needs the
   `make install` tree, and Apple make 3.81 has one-second timestamps.
7. Run the affected unit test **with and without the fix**. A regression test must fail
   without the fix. This macOS tree is built `-DNDEBUG`, so an assert-based test cannot
   abort locally: say so in the draft, and use a build without `-DNDEBUG` or an
   explicit check to show the failure when it matters.
8. Push to the **fork branch only**, and only if the change is exactly what the reviewer
   asked for or a faithful port of it: `git push --force-with-lease origin <branch>`.
   The fork branch is the head of the upstream PR, so this push updates the upstream
   PR too. Anything beyond the reviewer's request, or a doubt about it: do not push,
   say so in the draft.
9. Draft the reply text, in the operator's voice and ready to paste, into the path
   named in the Event section ("Reply draft"). It states what changed (commit sha),
   what was verified and how, and anything the reviewer should know. Never post it.
10. Update the Tier 1 session log with the `session-handoff` skill's writer protocol
    (a fresh owner for this run: record the event, the head sha you pushed or why you
    did not, the draft path, and "waiting for the operator's go").
11. Return to the branch from item 4, then
    `~/.local/bin/hermes-ping "cfengine-core: <repo>#<n> prepared: <one line>"`
    (one line, what is waiting for the operator), then write the report file the
    delivery contract below names and finish.

## Event
