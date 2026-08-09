# Gemini / OpenCLI browser bridge (site-djbclark#105)

Local, localhost-only bridge that lets Hermes send a prompt to Dan's
already-authenticated Gemini web session, read the response, and leave the
same visible Chrome tab open for Dan to inspect or continue manually. This is
an operator-side integration for the Hermes/Herdr workstation, **not** a
production service and **not** a replacement for the official Gemini API.

```text
Hermes -> bin/gemini_opencli_bridge.py -> opencli CLI -> localhost:19825 daemon
        -> OpenCLI Chrome extension -> dedicated visible Gemini tab -> gemini.google.com
```

## Verified dependency

- **OpenCLI**: [`jackwener/opencli`](https://github.com/jackwener/opencli),
  npm package `@jackwener/opencli`, **verified 1.8.6**, Apache-2.0,
  Node >=20. Pin this version when installing; re-verify before bumping.
- **Browser Bridge daemon**: local micro-daemon opencli starts on demand,
  `127.0.0.1:19825` (opencli's own default; claimed in
  [`registry/ports.yml`](../../registry/ports.yml)).
- **Chrome extension**: OpenCLI Browser Bridge, release asset
  `opencli-extension-v1.0.22.zip` from the
  [opencli releases page](https://github.com/jackwener/opencli/releases).

Confirmed by running `npx @jackwener/opencli@1.8.6 --help` / `doctor` /
`daemon status` in this environment (2026-08-07): the CLI auto-starts its own
daemon on port 19825 on first use, and `doctor` cleanly reports a
disconnected-extension state rather than hanging or crashing.

## One-time manual setup (Dan only)

This wrapper never automates login, MFA, or extension installation — all of
the following are manual, human steps:

1. Verify prerequisites: `node --version` (>=20), `npm --version`.
2. Install the pinned CLI, e.g. as a project/user tool:
   `npm install -g @jackwener/opencli@1.8.6` (or run via
   `npx --yes @jackwener/opencli@1.8.6 ...` if you'd rather not install
   globally — set `GEMINI_BRIDGE_OPENCLI_BIN` accordingly, see below).
3. Install the Chrome extension: download
   `opencli-extension-v1.0.22.zip` from
   <https://github.com/jackwener/opencli/releases>, open
   `chrome://extensions/`, enable Developer Mode, "Load unpacked", select the
   unzipped extension folder.
4. Open <https://gemini.google.com/app> in Chrome and sign in if needed (Dan
   only — never scripted).
5. Open or create a dedicated Gemini conversation tab for Hermes sharing.
6. Bind that tab to a named opencli profile, e.g.:
   `opencli --profile hermes-gemini browser hermes-gemini bind`
   (the wrapper defaults to profile `hermes-gemini`; override with
   `GEMINI_BRIDGE_PROFILE` or `--profile` if you use a different name).
7. Sanity check: `opencli doctor` should report the daemon running and the
   extension connected.
8. Read-only smoke test: `bin/gemini_opencli_bridge.py status`.
9. Prompt smoke test: `bin/gemini_opencli_bridge.py ask "reply with the word PONG"`.

Do not install a second overlapping browser-automation stack unless OpenCLI
fails a documented requirement.

## Hermes-facing surface (smallest useful phase)

Exactly three commands, all read/ask only — no arbitrary JS evaluation, no
tab/browser control beyond the bound Gemini session:

```bash
bin/gemini_opencli_bridge.py status                # login/availability check
bin/gemini_opencli_bridge.py read                   # read the visible conversation
bin/gemini_opencli_bridge.py ask "<prompt>"          # send a prompt, get only the new reply
```

Each prints one JSON object to stdout:

```json
{"ok": true, "command": "ask", "data": {"response": "...", "turn_count": 4},
 "error_type": null, "error_message": null, "latency_ms": 1234}
```

On failure, `ok` is `false` and `error_type` is one of:

| `error_type`         | Exit code | Meaning                                                              |
| --------------------- | --------- | ---------------------------------------------------------------------- |
| `login_required`      | 10        | Gemini session is signed out; a human must sign in manually            |
| `quota_or_challenge`  | 11        | Rate limit, CAPTCHA, or other challenge surfaced                       |
| `daemon_unavailable`  | 12        | `opencli` not on `PATH`, its daemon/extension unreachable, or offline  |
| `stale_response`      | 13        | No new assistant turn appeared after `ask`; response ownership failed  |
| `timeout`             | 14        | `opencli` did not respond within the configured timeout                |
| `ui_mismatch`         | 15        | Unexpected/malformed opencli output (Gemini UI likely changed)         |
| `lock_busy`           | 16        | Another call is already using this session (bounded wait, then fail)   |

Typed-error classification for `login_required` / `quota_or_challenge` /
`daemon_unavailable` is heuristic text matching over opencli's own output
(see `classify_failure` in the script) — it was exercised against real
`daemon status`/`doctor` output but **not** against a live signed-in Gemini
session (no Chrome extension binding was available in this environment).
Re-check the pattern lists against real output the first time each failure
mode is hit live, and tighten them if needed.

## Bind / session model

- **Explicit targeting**: every call passes `--profile <name>` (default
  `hermes-gemini`) plus `--site-session persistent`, so it always operates on
  the one bound Gemini tab/session rather than whichever tab happens to be
  active.
- **No stolen focus**: every call passes `--window background`.
- **Physical-profile lease**: before touching opencli, the wrapper takes a
  shared exclusive lease keyed by the explicit OpenCLI Browser Bridge profile
  under `${XDG_STATE_HOME:-~/.local/state}/site-djbclark/opencli-profile-leases`.
  This is the outer lock and protects against different Hermes topics using the
  same physical Chrome/Brave profile. Contention fails closed with `lock_busy`
  and bounded owner metadata; the kernel releases the flock after a crash.
- **Per-session lock**: inside that lease, `bin/gemini_opencli_bridge.py` takes an exclusive
  `fcntl.flock` on `~/.local/state/site-djbclark/gemini-bridge/<profile>.lock`
  before touching opencli, with a bounded wait (`--lock-timeout`, default
  10s) — the same pattern as `bin/brew_flock.py` / `bin/ops_release_lock.py`.
  Concurrent calls for the same visible conversation serialize instead of
  racing. Brave and Chrome profiles can proceed independently.
- **Shared broker for other callers**: future Hermes/OpenCLI integrations must
  use `bin/opencli_profile_lease.py run --profile ... --owner ... --purpose ...
  -- <command>` rather than invoking raw `opencli` directly. The broker holds
  the same physical-profile lease for the child process.
- **Response ownership**: `ask` reads the conversation before and after
  sending the prompt and only accepts the reply if a genuinely new,
  assistant-authored turn appears; otherwise it raises `stale_response`. A
  failure on the *baseline* (before-prompt) read is only tolerated when it
  is narrowly identified as opencli's own "no active conversation" wording
  (a brand-new/never-opened session) — every other baseline-read failure
  (`login_required`, `quota_or_challenge`, `daemon_unavailable`, `timeout`,
  or any other `ui_mismatch`) is propagated as a real error rather than
  being treated as an empty conversation.

## Start / stop / check

There is no persistent service to start or stop — `opencli` starts its own
daemon on first use and it stays up in the background. Operator commands:

```bash
opencli daemon status              # is the daemon up, is the extension connected
opencli doctor                     # full connectivity diagnosis
bin/gemini_opencli_bridge.py status   # is the bound Gemini session logged in
bin/opencli_profile_lease.py status --profile <profile> # who owns a profile lease?
opencli daemon stop                 # stop the daemon (Dan-only, e.g. before revoking)
```

To revoke/uninstall: `opencli daemon stop`, remove the Chrome extension from
`chrome://extensions/`, and `npm uninstall -g @jackwener/opencli` (or delete
the local install). No credentials, cookies, or profile data are stored by
this wrapper to clean up.

## Security boundary

- Localhost-only; nothing here binds to a non-loopback address or is exposed
  publicly.
- No passwords, MFA codes, API keys, cookies, or Chrome profile data are
  *ever* read, stored, copied, or transmitted by the wrapper — there is no
  configuration path that captures those. It only shells out to the
  installed `opencli` binary with an argument list (never a shell string),
  and reads its stdout/stderr.
- **Prompt text is never persisted, under any configuration.**
- **Response text is not persisted by default.** Audit entries written to
  `~/.local/state/site-djbclark/gemini-bridge/audit.jsonl` (mode 0600)
  normally contain only timestamp, profile, command, ok/error_type, latency,
  and a response size/SHA-256 hash (enough to correlate an entry with a
  response without storing it).
- **Opt-in, bounded response capture for local debugging.** Set
  `GEMINI_BRIDGE_CAPTURE_CONTENT=1` to additionally store a response
  preview in that same audit log. The preview length defaults to 200 chars
  and is configurable down via `GEMINI_BRIDGE_CAPTURE_CONTENT_MAX_CHARS`,
  but is always clamped to a **code-level hard cap of 4096 chars (4 KiB)**
  that no configuration can raise — see `HARD_MAX_CAPTURE_CHARS` in
  `bin/gemini_opencli_bridge.py`. An invalid or over-the-cap value is
  rejected: the call still succeeds and the metadata-only entry is still
  written, but no preview is captured for that entry (a warning is printed
  to stderr).
  **A captured response preview may itself contain sensitive user data**
  (whatever was discussed with Gemini) — this wrapper does not scan
  captured content for secrets. Once capture has ever been enabled, treat
  `audit.jsonl` as operator-protected, the same as any other local
  secret-adjacent file.
- Only `status`, `read`, and `ask` are exposed — no arbitrary JS evaluation,
  no generic browser/tab control, no image generation or file upload.

## Environment variables

| Variable                                | Default                              | Purpose                                  |
| ----------------------------------------- | ------------------------------------- | ----------------------------------------- |
| `GEMINI_BRIDGE_PROFILE`                   | `hermes-gemini`                       | opencli `--profile` / bound session name  |
| `GEMINI_BRIDGE_OWNER`                     | `hermes`                              | topic/process label in physical-profile lease diagnostics |
| `GEMINI_BRIDGE_OPENCLI_BIN`               | (PATH, then `/opt/homebrew/bin/opencli`, then `/usr/local/bin/opencli`) | explicit binary override or automatic macOS Homebrew discovery |
| `GEMINI_BRIDGE_STATE_DIR`                 | `${XDG_STATE_HOME:-~/.local/state}/site-djbclark/gemini-bridge` | lock file + audit log dir |
| `OPENCLI_PROFILE_LEASE_STATE_DIR`         | `${XDG_STATE_HOME:-~/.local/state}/site-djbclark/opencli-profile-leases` | shared physical-profile lease dir |
| `GEMINI_BRIDGE_CAPTURE_CONTENT`           | unset (off)                           | `1` to opt into a bounded response preview in the audit log |
| `GEMINI_BRIDGE_CAPTURE_CONTENT_MAX_CHARS` | `200` (only used when capture is on)  | preview length in chars; must be a positive integer `<= 4096` (`HARD_MAX_CAPTURE_CHARS`) or the value is rejected and no preview is captured for that call |

## Tests

```bash
python3 -m unittest tests.test_gemini_opencli_bridge -v
python3 -m unittest tests.test_opencli_profile_lease -v
```

Covers: physical-profile lease contention and owner metadata, distinct-profile
concurrency, response-ownership/stale-response rejection, session-lock contention
and serialization (no interleaving), every typed failure state (login
required, quota/challenge, daemon unavailable, timeout, UI mismatch/malformed
JSON, lock busy), prompt-argument safety (shell metacharacters passed as a
single argv element, `shell=True` never used), and audit-log content
redaction by default.

## Known gaps / next steps

- OpenCLI 1.8.6 returns the `ask` response but does not append that turn to the visible `read` snapshot. The bridge first waits briefly for propagation; if the snapshot remains unchanged, it accepts only a nonempty response that differs from the current last assistant response and marks ownership as `ask_response_delta`. Exact stale echoes still fail closed.
- No `gemini_bind`/`gemini_unbind` lifecycle commands yet (binding is a
  manual `opencli browser <profile> bind` step per the setup above) — the
  issue lists these as optional for a later phase.
