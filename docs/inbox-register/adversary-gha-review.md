# Adversary review: `.github/actions/inbox-send` + callers (site-djbclark @ 1e409b4)

Scope: `.github/actions/inbox-send/action.yml`; callers `nixos-lock-update.yml`, `monitor-thaw-next-access-request.yml`, `monitor-herdr-extension-releases.yml`, `track-issue-activity.yml` (I also skimmed `gradle-cache-repin.yml`, a fifth caller: every `${{ }}` there goes through `env:`, so no findings); `registry/telegram-inbox.env`, `registry/telegram-inbox.toml`.

Facts checked live: the repo is **public**, so run logs are public. `default_workflow_permissions=read`. `allowed_actions=all`, `sha_pinning_required=false`. **No workflow in `.github/workflows/` has a `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment` or `issues` trigger.** Every caller runs only on `schedule` or `workflow_dispatch`.

## Direct answers

1. **Can TELEGRAM_BOT_TOKEN leak?** It cannot leak through the action's own output. It **can be stolen through F1** (code execution in the `track-issue-activity` job, which then gets the token handed to it).
   - The action's own output is clean. There is no `set -x`. `--fail-with-body` writes the body to the `mktemp` file and not to the log. I ran curl's error lines against the real Bot API with a fake token: they do not contain the URL (`curl: (22) The requested URL returned error: 401`, `curl: (6) Could not resolve host: …`). Telegram's `description` (`Unauthorized`, `Not Found`) does not echo the token. The runner also masks the secret value.
2. **Can a fork PR run code with the token?** **No.** No caller has a PR, comment or `workflow_run` trigger. `. registry/telegram-inbox.env` sources the file at `github.sha` of a schedule or dispatch run: the default branch, or a branch picked by someone with write access, who could edit the workflow anyway. Sourcing the committed file does not widen trust today.
   - It becomes a BLOCKER the day any caller gains a `pull_request_target` or `workflow_run` trigger with a PR-head checkout.

## Findings

### F1. HIGH: `${{ }}` expression injection gives code execution in `track-issue-activity`, and from there the Telegram token
VERDICT: HIGH (the line predates this change, from 90d0dea on 2026-07-29, but this change keeps passing `secrets.TELEGRAM_BOT_TOKEN` into that job)

- **Where:** `.github/workflows/track-issue-activity.yml:221` `TITLE="${{ steps.check.outputs.title }}"`. Lines 222-224 have the same pattern. `title` is the raw `title` of a third-party issue or discussion (`:142`, `:162`).
- **Who controls the title:** anyone with triage or higher access on any of the 12 tracked third-party repos (AltanS/collie, KrishnaGupta653/telegcli, thedjchi/Shizuku, …, charmbracelet/crush). Also anyone who re-registers a deleted or renamed owner or repo name (repojacking), since the API URL is built from the name.
- **Exploit:** set the title to `Bug"; <payload>; : "`. Actions pastes it textually into the `run:` script.
  - **Reproduced locally:** I rendered lines 219-248 the same way and ran them under `bash -e -o pipefail`. The payload ran (`PWNED_AS=djbclark`), the step exited 0, and the Telegram text looked normal (`<b>Bug</b>`), so the attack is silent.
  - Workflow-level `GH_TOKEN=${{ github.token }}` is in scope (read-only by repo default).
- **How the payload gets the Telegram token** (the next step, `Notify via Telegram` at `:250`, has the same `if` and an implicit `success()`, so it runs):
  - (a) Write `BASH_ENV=/tmp/x.sh` to `$GITHUB_ENV`. The composite's `shell: bash` step is non-interactive bash, which sources `BASH_ENV` with `TELEGRAM_BOT_TOKEN` in its env. **Reproduced:** `BASH_ENV=evil bash --noprofile --norc -eo pipefail step.sh` printed `STOLEN=123:SECRET`.
  - (b) Rewrite `.github/actions/inbox-send/action.yml` on disk. The runner reads a local action's `action.yml` when that step starts. [INFERENCE from runner behaviour; not run on GitHub.] The inner `actions/checkout` resets `registry/telegram-inbox.env`, but only after `action.yml` is already loaded.
  - (c) Leave a background process that reads `/proc/*/cmdline`: line 98 puts the token in curl's argv.
- **Impact:** the attacker holds the bot token. They can send as the bot into any topic, including Triage 44136, the `bound` thread wired to a live agent (`goose-scout`). If the bot polls with `getUpdates`, they can also race the real consumer for updates and read djbclark's messages. [INFERENCE: whether this secret is the Hermes bot and whether it uses polling was not checked.]
- **Minimal fix:** move every `steps.*`/`matrix.*` value at `:219-224` into `env:` and reference `"$TITLE"` etc. Do not leave any `${{ }}` inside a `run:` body in this file; `:28`, `:94`, `:100`, `:209` and `:217` are not shell, so they are fine.

### F2. MEDIUM: any GitHub user can inject step outputs in `monitor-thaw-next-access-request` (spoofed link, suppressed alert)
VERDICT: MEDIUM

- **Where:** `.github/workflows/monitor-thaw-next-access-request.yml:76-80`. The last comment body on public issue thaw-app/Thaw#1166 is written between a **fixed** delimiter, `excerpt<<__EXCERPT__`.
- **Exploit:** any GitHub account comments on #1166 with these lines:
  `__EXCERPT__`, `url=https://evil.example/…`, `last_author=<maintainer>`, `comment_count=<seen>`, `last_id=<seen>`, `pad<<__EXCERPT__`.
  The last line absorbs the real closing delimiter, so the step does not fail.
  - **Reproduced** with a fake `gh` and a parser that follows the runner's file-command format: `url`, `last_author`, `comment_count` and `last_id` all came out as the attacker's values, and the step exited 0. That later duplicate keys override earlier ones is [INFERENCE] about the runner.
- **Impact:**
  - **Spoofing:** a phishing URL credited to a maintainer goes to the Pings thread.
  - **Suppression:** `seen_*` is readable in the public tracking issue in this repo. If the attacker forges `comment_count`/`last_id` equal to `seen_*`, `changed=false`. A real maintainer reply posted before the attacker's comment is then never notified, and the tracking issue is not updated.
  - The Telegram token is not reachable: every value reaches the shell through `env:`.
- **Minimal fix:** use a random delimiter per write, e.g. `d="EOF_$(openssl rand -hex 16)"; { echo "excerpt<<$d"; jq …; echo "$d"; } >>"$GITHUB_OUTPUT"`. Apply the same change to every `text<<__TEXT__` writer: `track-issue-activity.yml:245`, `monitor-thaw…:162,232`, `monitor-herdr…:127,186`, `nixos-lock-update.yml:202`. Today only thaw `:162` (attacker excerpt) is exploitable; the rest are cheap uniformity.

### F3. MEDIUM: `track-issue-activity` loses notifications silently and permanently (HTML not escaped, `strict: "false"`, cache saved before sending)
VERDICT: MEDIUM

- **Where:**
  - `track-issue-activity.yml:229`: `<b>$TITLE</b>` goes out with `parse_mode: HTML` (`:256`) and is never escaped.
  - `:258`: `strict: "false"`.
  - `action.yml:113`: a non-strict API error is a plain `echo`, not a `::warning::`.
  - `track-issue-activity.yml:202-211`: the state cache is saved **before** the send (`:250`).
- **Exploit or failure:** a title containing `<`, `>` or `&` makes Telegram reject the message with "can't parse entities". That can be benign (e.g. `Option<T>`) or deliberate by a title editor (same actor as F1).
  - With `strict: "false"` the action prints a plain line and exits 0. The run is green and has no annotation.
  - The new comment count is already cached, so the event is never re-sent.
  - An attacker can instead inject `<a href="https://evil">Open on GitHub</a>` to put a phishing link into a trusted thread.
- **Minimal fix:** HTML-escape the interpolated values (`python3 -c 'import html,sys;print(html.escape(sys.argv[1]))' "$TITLE"`) and drop `strict: "false"`; the `if` already gates the call. Optionally move the cache save after a successful send. In `action.yml:113`, emit `::warning::` so a non-strict failure is at least annotated.

### F4. LOW: empty token reports success while nothing is sent, and callers then mark the event as seen
VERDICT: LOW (failure mode, no attacker)

- **Where:** `action.yml:79-82`. An empty `TELEGRAM_BOT_TOKEN` gives a `::warning::` and `exit 0`.
- **Failure:** if the secret is renamed or deleted, every run stays green. Each caller then records the event as handled:
  - thaw updates the tracking issue (`:175`);
  - herdr creates the dedupe issue (`:140`);
  - track-issue already saved its cache.
  - nixos-lock-update survives because its GitHub issue is a second channel.
- **Minimal fix:** `exit 1` when the token is empty. No caller can run from a fork, so the "secrets absent on fork PRs" reason for exiting 0 does not apply. If a soft mode is wanted, tie it to `strict`.
- **Unknown or missing routes are already handled:** they exit 1 regardless of `strict` (`:74-77`). There is no default-thread fallback in the action, and no current route keys collide after `tr` (checked against `[routes]`). I found **no path that sends to a wrong thread**.

### F5. LOW: jq injection in herdr dedupe; an upstream plugin author can leak the job's GITHUB_TOKEN to the public log
VERDICT: LOW

- **Where:** `monitor-herdr-extension-releases.yml:96,103`. `LATEST_VERSION` comes from the upstream `herdr-plugin.toml` (iuhoay/herdr-break-pane, AVGVSTVS96/herdr-drovr). It is spliced into the `--jq` program as `select(.title == \"$title\")`.
- **Exploit:** a version like `x") | error(env.GH_TOKEN|@base64) | ("` makes gh's gojq print the base64 token to stderr. Base64 gets past masking, and the log is public. The token has `issues: write` and `contents: read` and is valid until the job ends. [INFERENCE: gh's `--jq` exposes `env`; not run.]
- **Not exposed:** the Telegram token is not in this step, and jq cannot run code. The attacker set is plugin authors, who already run code on the workstation, hence LOW.
- **Minimal fix:** `--jq '[.[] | select(.title == $t)] | length'` does not work, because `gh --jq` takes no `--arg`. Instead fetch `--json title` and compare in shell or Python: `gh issue list … --json title | jq --arg t "$title" '[.[]|select(.title==$t)]|length'`.

### Informational (accepted risk, does not affect the verdict)

- **Floating action tags:** `actions/checkout@v7` (inside the composite, so it runs in every send job), `actions/cache@v6`, `cachix/install-nix-action@v31`.
  - This was djbclark's ruling in 1e409b4 (2026-10-24, "no SHA pins"), and the repo does not require pins.
  - The one with real reach is the third-party `cachix/install-nix-action@v31` in `nixos-lock-update`. That job has `contents: write`, receives `github.token` (`:66`), and runs before the push to `deploy-vps-primary`, which vps-primary deploys from. A moved tag there means a NixOS config on the host chosen by whoever moved it.
  - Recorded only; not relitigated.

## Dropped (no exploit path today)

- **`route` and indirect expansion** (`action.yml:65-73`): `${!chat_var}` would evaluate an array subscript such as `X[$(…)]`. Every caller hard-codes `route`, so there is no path today. Only add an allowlist (`[[ $key =~ ^[A-Z0-9_]+$ ]]`) if `route` ever comes from data.
- **`--data-urlencode "text=…"`:** the constant `text=` prefix means curl encodes the content literally. An `@` or `&` in the message cannot read a file or add a parameter. `parse_mode` is a caller constant.
- **Sourcing `registry/telegram-inbox.env`:** see answer 2. The inner checkout's `clean: true` also resets a tampered copy of the file in the workspace before it is sourced.

DECIDED: I judged F1 a blocker for merge even though the vulnerable line predates this change, because this change keeps handing the token to that job, and the fix is three lines.

VERDICT: changes-required (F1 must be fixed; F2-F3 strongly recommended in the same change)

DONE
