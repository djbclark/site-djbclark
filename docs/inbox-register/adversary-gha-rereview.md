STATUS: complete
# AD2 re-review: fix commit 3acf24b (site-djbclark HEAD) for AD findings F1-F5

## Per finding

F1: CLOSED - no `run:` body in the four callers, gradle-cache-repin or action.yml contains `${{ }}` any more (I parsed every workflow's YAML and scanned each step's `run`; the only hit repo-wide is `sync-tracked-issues.yml` `dry_run="${{ github.event.inputs.dry_run }}"`, a dispatch input that only write-access users can set, so no exploit path). The title, note and state now arrive via `env:` (track-issue-activity.yml:205-212). `esc()` passes the value as argv to a constant `python3 -c` program (:214). A hostile title (`Bug"; touch …; : "`, `$(touch …)`, `<a href=…>`, a literal `EOF`/`EOF_00` line) run through the real step body under `bash -e`: rc 0, no file created, everything escaped. Remaining expressions in `if:`/`with:` are not evaluated as code (`with: message:` reaches the action as `INBOX_MESSAGE` env, action.yml:57).

F2: CLOSED - all 8 writers (thaw :79, :165, :236; herdr :126, :187; nixos-lock-update :201; gradle-cache-repin :254; track-issue-activity :240) use `d="EOF_$(openssl rand -hex 16)"`: 128 random bits per write, generated in the same shell after the body is fixed, so a body cannot contain it. Under the default `bash -e {0}` or an explicit `set -euo pipefail`, an `openssl` failure aborts the step rather than falling back to the guessable `EOF_` (the assignment takes the substitution's exit status). Each body ends with a newline (`echo`, `jq -r`), so the closing delimiter is always on its own line.

F3: PARTIAL - the escaping is complete (every interpolated value goes through `esc()`, quote=True; `ISSUE_URL` is not escaped, but it is built only from hard-coded matrix values, so nothing to exploit), and `strict:` is gone from every caller (only action.yml:33 defines it, default "true"). The cache move is correct as written: Save at :257-268 has an implicit `success()`, so a failed send leaves the cache unsaved and the next run retries, and a skipped Notify on a cold start still saves because `had_cache == 'false'` is in Save's `if`. **But the dedupe it protects does not work: see N1. The workflow never notifies, so "saved only after a successful send" is never reached** (track-issue-activity.yml:100-101 vs :268).

F4: CLOSED - empty token -> `::error::` + exit 1 (action.yml:79-82). Every caller still triggers only on `schedule`/`workflow_dispatch` (rechecked, no PR trigger), so no fork run will fail for missing secrets. In nixos-lock-update and gradle-cache-repin, Notify runs after Promote and Report, so a token failure cannot block a deploy. In thaw and herdr, a send failure now also skips the tracking-issue update, so the event is retried, which is the intended effect.

F5: PARTIAL - the jq injection is fixed (`jq --arg t`, herdr :97-103; gh `--json title` always emits a JSON array). **But the step has no `set -o pipefail`: there is no `shell:` and no `defaults.run.shell`, so it runs under `bash -e {0}`.** A failing `gh` now gives `count=""`, `[ "" -eq 0 ]` errors inside `if`, and the step takes the else-branch `new_update=false` / "Release was already reported", rc 0. Before the fix, `count=$(gh … --jq …)` failing aborted the step red. See N2 (monitor-herdr-extension-releases.yml:97-109).

## New findings

N1. MEDIUM (functional; no attacker; predates 3acf24b, but the fix moved this block and left it): **track-issue-activity never restores its state, so it never notifies.** Restore uses `gh-tracker-v3-<slug>-` (:100-101); Save writes `gh-tracker-v2-<slug>-<run_id>` (:268).
- Introduced in 67a7fe2 (#118), which bumped restore to v3 but not save.
- Live evidence:
  - `gh cache list` shows only `gh-tracker-v2-*` entries, 17 new ones each hour. Every entry's `lastAccessedAt == createdAt`: none has ever been restored.
  - Run 40109985759's log: `Cache not found for input keys: gh-tracker-v3-cfengine-core-6295-…`.
- Effect:
  - Each run has `had_cache=false`, so `old_count=-1` and `old_state=""`, so `changed=false`. A scheduled run never sends; only a manual dispatch with `notify_even_if_unchanged` does.
  - Save runs every hour for every slug, piling up cache entries.
  - This is the "lost baseline forever" case the brief asked about. Its cause is the key mismatch, not the reordering.
- Fix: change :268 to `gh-tracker-v3-${{ matrix.issue.slug }}-${{ github.run_id }}`.
- After the fix, expect one burst of notifications: the first run seeds the cache, and later runs compare against it.

N2. LOW (regression introduced by the F5 fix): **a gh failure in herdr dedupe silently suppresses the release alert, and the run is green.**
- Reproduced with a fake `gh` that exits 1, run under `bash -e`: output `[: : integer expected`, then `new_update=false` / `Release was already reported`, rc=0.
- Exploit path (same attacker as F5: a plugin author; the length limit is [INFERENCE] from GitHub's documented 256-character search-query limit, not run):
  - Publish a `herdr-plugin.toml` `version` longer than about 256 characters.
  - `--search "${title} in:title"` is rejected, `gh` exits non-zero, and the daily run (`17 7 * * *`) reports green with no Telegram message and no tracking issue.
  - This continues for as long as that version stays up, so the attacker's update ships without the alert that exists to flag it.
  - Transient API errors cause the same silent skip for one day.
- Fix: put `set -euo pipefail` at the top of that `run:` (or `defaults: run: shell: bash` at workflow level, which gives `-eo pipefail`). Optionally also fail on a non-numeric `count`.

## Regression hunt, no findings
1. Dedupe after moving Save: the key includes slug and run_id, so matrix jobs never share a key, and caches are immutable per run.
   - A rerun of a failed attempt reuses the run_id, but that key was never saved, because Save is the last step and is gated on success.
   - If the send succeeds and the cache save then fails, the next run sends again (at-least-once delivery). This is an acceptable trade and has no attacker.
2. python3/openssl dependencies:
   - `python3` was already used throughout the check step (:130-173), so it is not a new dependency.
   - `openssl` is present on ubuntu-latest. The nix jobs run the writer on the same image.
   - The runner image floats (`ubuntu-latest`); per the 1e409b4 ruling, no pin is relitigated.
3. `set -e` aborts: if `esc()` or `openssl` fails, the step aborts and the job goes red without saving (fail-closed, retried next hour).
   - A title that is not valid UTF-8 cannot reach `esc()`, because the earlier `print` only emits valid UTF-8.
4. Possible newline in an issue title at `echo "title=$new_title"` (:168): I did not verify that GitHub allows a newline in a title. All consumers now get the value via env and escape it, so there is no exploit path today; dropped.

DECIDED: N1 predates the fix, but I made it the reason F3 is PARTIAL and the merge blocker. The fix commit claims cache-after-send semantics for a cache that is never read, and the change it needs is a single key string.

VERDICT: changes-required (N1: save key v2 -> v3; N2: add pipefail to the herdr dedupe step)

DONE
