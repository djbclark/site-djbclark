# macOS 27.0.1 boot-time TCC race — apps re-ask for permissions after every reboot, and a staggered-login fix

**Date:** 2026-10-05 · **Status:** diagnosed and worked around; root cause is
Apple's (not fixed as of 27.0.1 — no point release available yet)

## TL;DR

After upgrading to macOS 27.0.1, a set of apps — Default Folder X, Warden,
CuaDriver, BetterStage, Logi Options+ — re-showed their "grant permission"
dialogs on seemingly every reboot even though the toggles in System Settings
→ Privacy & Security were still on. The cause is **not** the apps and **not**
lost grants: for roughly the **first two minutes after login**, `tccd` (the
TCC permissions daemon) intermittently fails to compute code identities for
processes, so any app that launches inside that window has its permission
requests **refused** and concludes it needs to re-prompt. The stored grants
are intact; launch the same app two minutes later and everything works.

Two remedies fall out of that:

1. **Zero-install workaround:** after a boot, dismiss the dialogs, wait ~2
   minutes, relaunch the complaining apps. They re-evaluate against the
   intact grant and stop asking.
2. **Durable fix (below):** a ~140-line login-time script
   ([`stagger-login`](#the-stagger-login-script)) that delays the noisy
   apps' launches past the race window, staggered, via one LaunchAgent.

**Do not** reach for `tccutil reset` here — resetting TCC throws away the
grants that are actually fine and guarantees a fresh round of prompts.

## The symptom

Five apps, five different permission types (Accessibility, Input Monitoring,
Apple Events, Microphone), one shared behavior: the grant dialog reappears
after reboot despite the toggle already being enabled. All five were
properly Developer ID–signed, notarized, hardened-runtime apps, updated
within the prior week — which initially pointed at the classic (and usually
correct) "update changed the code signature" theory. That theory is wrong
here, and checking it is cheap:

```sh
codesign -vv /Applications/SomeApp.app     # "satisfies its Designated Requirement"
spctl --assess --verbose=2 /Applications/SomeApp.app   # "accepted, Notarized Developer ID"
```

Both passed for all five. When signing is fine but grants appear broken,
the next suspect is the grant *evaluator*, not the grants.

## Diagnosis: watching tccd

TCC decisions land in the unified log under the `tccd` process. A 48-hour
sweep:

```sh
log show --last 48h --style compact --predicate 'process == "tccd"' > /tmp/tcc.log
```

Three findings, in order of importance:

### 1. Boot-window bursts of "Failed to get code reference"

```text
tccd ... Failed to get code reference from: TCCDProcess: identifier=com.trycua.driver,
  pid=…, binary_path=/Applications/CuaDriver.app/Contents/MacOS/cua-driver. 100024

tccd ... Refusing TCCAccessRequest for service kTCCServiceAccessibility from ...
```

`tccd` could not construct a code identity for the *on-disk binary* — the
same binary `codesign` happily validates — and therefore refused the
request outright. Related shape, same meaning:

```text
internal_TCCCreateDesignatedRequirementIdentityFromMessage: Refusing
TCCCreateDesignatedRequirementIdentityForService (kTCCServiceAppleEvents)
accessing={…}: unable to compute designated requirement for:
file:///Applications/Some.app/Contents/MacOS/Some
```

### 2. It is systemic, not app-specific

Grouping the failures by bundle ID returned **130+ identifiers** — every
third-party app that launched early (Contexts, PopClip, Raycast, 1Password,
Tailscale, …) *and* Apple's own (Dock, weather widgets, notification
center, System Settings). When the Dock fails a code-signing lookup, the
apps are innocent.

### 3. It is a race with a hard time boundary

Bucketing failures by minute showed bursts only in the first ~2 minutes
after each login (59–244/min during the window), then **zero**. On the
diagnosis day there were three reboots inside 20 minutes — three prompt
storms, three clean recoveries. Post-window, `tccd` logged normal
"Granting …" decisions again, and a live Apple Events request issued from
a shell succeeded with no refusal.

Also visible, and worth knowing apart from the race: a couple of apps
(App Tamer, the Logi background agent) spam

```text
Prompting policy for hardened runtime; service: kTCCServiceMicrophone
requires entitlement com.apple.security.device.audio-input but it is missing
```

That is a different, permanent condition — the binary requests a service
without carrying the matching entitlement in its signature. No amount of
granting can satisfy it; ignore it or file with the vendor.

One more thing the log surfaced: **Logi Options+ has (at least) three TCC
identities** — the GUI (`com.logi.optionsplus`), the background agent
(`com.logi.cp-dev-mgr`, living in `/Library/Application Support/Logitech.localized/…`),
and a driver host (`com.logi.optionsplus.driverhost`). Prompts can arrive
under any of them, which multiplies the perceived re-prompting.

## What is actually going on

During early login, `tccd`'s code-identity computation (which consults the
security/trust stack) is not yet reliably available — under boot load it
fails for processes that ask too early, tccd refuses their request, and
well-behaved apps respond to the refusal by surfacing a grant request.
The stored TCC rows are untouched, which is why the "wait and relaunch"
workaround works and why `tccutil reset` is the wrong tool.

(Note for reproducing on your own machine: on macOS 27 there is no
user-readable `~/Library/Application Support/com.apple.TCC/TCC.db`; the
authoritative store is root-only. The `log show` sweep above is the
practical evidence source from an unprivileged shell.)

## The fix: launch late, staggered

Since the window is bounded (~2 min) and load-dependent, moving the
affected apps' launches past it removes the symptom entirely. The wrinkle
is that "launch at login" is three different mechanisms, and the fix must
handle each:

| Mechanism | Example | How to delay it |
|---|---|---|
| Classic login item | Default Folder X, Warden, BetterStage | delete the login item; `open -g -a` from a script |
| User LaunchAgent (launchd-supervised, KeepAlive) | CuaDriver (`com.trycua.cua-driver`) | `launchctl disable` in the per-user DB; re-enable + start late |
| Root-owned LaunchAgent | Logi agent (`com.logi.cp-dev-mgr` in `/Library/LaunchAgents/com.logi.optionsplus.plist`) | same `launchctl disable` — works without sudo for the user session |

### The launchd dance (the part worth testing yourself)

For launchd-supervised agents you don't want to lose supervision — the
correct pattern, rehearsed live on the real service before trusting it:

1. `launchctl disable gui/$UID/<label>` — writes the per-user disabled
   flag. **The running instance keeps running**; only future loads skip it.
   So disabling now costs nothing until the next reboot.
2. At login, launchd skips the disabled agent — good, that's the point.
3. Late (after the race window): `launchctl enable gui/$UID/<label>`, then
   start it. Two gotchas learned the hard way:
   - **`kickstart` only works on a *loaded* service.** After a `bootout`
     (or if launchd skipped loading the disabled plist entirely),
     `kickstart` fails with "Could not find service". The fallback is
     `launchctl bootstrap gui/$UID <plist>` — and because the plist has
     `RunAtLoad`, bootstrap alone starts it.
   - `enable` persists in the disabled DB. If you enable-and-start, the
     agent will autostart early again at the *next* boot — so re-`disable`
     it right after the successful start. The running process is
     unaffected; you have just re-armed the skip for next boot.
4. Bootstrap of a root-owned `/Library/LaunchAgents` plist into your own
   GUI session works unprivileged (probed: it fails with rc=5
   "already loaded" when the service is up, not with a permission error).

So the per-boot cycle for a launchd-managed target is:
**skip (disabled) → enable → kickstart-or-bootstrap → verify running → disable again.**

### The stagger-login script

One LaunchAgent runs this at login; it sleeps out the base window, then
gates on the live tccd log before releasing the staggered launches.

Config (`~/.config/stagger-login/apps`, **tab**-separated; delays are
absolute seconds after login):

```text
# delay  kind     target...
150	launchd	gui/501/com.logi.cp-dev-mgr	/Library/LaunchAgents/com.logi.optionsplus.plist
170	app	/Applications/Default Folder X.app
185	app	/Applications/Warden.app
200	app	/Applications/BetterStage.app
225	launchd	gui/501/com.trycua.cua-driver	~/Library/LaunchAgents/com.trycua.cua-driver.plist
```

(the `gui/501` literal is `gui/$(id -u)`; `app` targets are skipped if
already running, so a manual early launch is never double-opened)

```sh
#!/bin/sh
# stagger-login — delay-launch TCC-noisy apps past the macOS 27.0.1 boot race.
# Config: tab-separated lines: <delay>\tapp\t<bundle-path>
#                                    <delay>\tlaunchd\t<gui/uid/label>\t<plist>
# Flags: --dry-run (log the plan, do nothing), --now (skip base wait+gate).
# Env: STAGGER_BASE (default 150) seconds before the first target.
# Log: ~/Library/Logs/stagger-login.log

set -u
PATH=/usr/bin:/bin:/usr/sbin:/sbin

CONF="${STAGGER_CONF:-$HOME/.config/stagger-login/apps}"
LOG="$HOME/Library/Logs/stagger-login.log"
BASE="${STAGGER_BASE:-150}"
UID_=$(id -u)
DRY=0; NOW=0; tries=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --now) NOW=1; BASE=0 ;;
        *) printf 'unknown flag: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '[%s] %s\n' "$(ts)" "$*" >> "$LOG"; }

# Rotate if over 64 KB.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 65536 ]; then
    tail -n 200 "$LOG" > "$LOG.1"
    : > "$LOG"
fi
touch "$LOG"
log "=== stagger-login start (pid $$, base=${BASE}s, dry=$DRY, conf=$CONF)"

if [ ! -f "$CONF" ]; then
    log "no config at $CONF — nothing to do"
    exit 0
fi

if [ "$DRY" = 0 ] && [ "$NOW" = 0 ]; then
    log "sleeping ${BASE}s (TCC race window)"
    sleep "$BASE"
    # Active gate: while tccd still fails code refs in the recent log,
    # extend the wait (up to 6 x 15s). `log show` failure = proceed anyway.
    tries=0
    while [ "$tries" -lt 6 ]; do
        n=$(/usr/bin/log show --last 20s --style compact \
             --predicate 'process == "tccd" AND eventMessage CONTAINS "Failed to get code reference"' \
             2>/dev/null | grep -c 'Failed to get code reference')
        [ "${n:-0}" -gt 0 ] 2>/dev/null || break
        log "gate: tccd still failing ($n hits in last 20s); +15s (try $((tries+1))/6)"
        sleep 15
        tries=$((tries + 1))
    done
    log "past base wait + gate (took $((BASE + tries * 15))s max)"
fi

app_running() {
    pgrep -f "$1/Contents/MacOS" > /dev/null 2>&1
}

svc_state() {
    launchctl print "$1" 2>/dev/null | awk -F' = ' '/^[[:space:]]*state =/ { print $2; exit }'
}

do_app() {
    path="$1"
    if app_running "$path"; then
        log "skip (running): $path"
        return
    fi
    log "open -g -a $path"
    if [ "$DRY" = 1 ]; then return; fi
    open -g -a "$path" && log "launched: $path" || log "FAILED: open -g -a $path"
}

do_launchd() {
    svc="$1"; plist="$2"
    if [ "$(svc_state "$svc")" = "running" ]; then
        log "skip (running): $svc"
    else
        log "start: $svc"
        if [ "$DRY" = 0 ]; then
            launchctl enable "$svc" 2>/dev/null
            if ! launchctl kickstart "$svc" 2>/dev/null; then
                # Service not loaded in the session: bootstrap it; RunAtLoad fires.
                launchctl bootstrap "gui/$UID_" "$plist" 2>&1 | head -1 >> "$LOG"
            fi
            sleep 2
            if [ "$(svc_state "$svc")" = "running" ]; then
                log "started: $svc"
            else
                log "FAILED to start: $svc (check launchctl print $svc)"
            fi
        fi
    fi
    # Re-arm the login skip whether we started it or found it running.
    if [ "$DRY" = 0 ]; then
        launchctl disable "$svc" 2>/dev/null && log "re-armed skip for next boot: $svc"
    fi
}

# Delays are absolute seconds-from-login: credit the base wait (plus any
# gate extension) already slept before the first entry, then sleep only the
# delta between consecutive targets.
prev=$((BASE + tries * 15))
grep -v '^[[:space:]]*#' "$CONF" | grep -v '^[[:space:]]*$' | sort -n | {
    while IFS="$(printf '\t')" read -r delay kind a b; do
        case "$kind" in
            app) target="app $a" ;;
            launchd) target="launchd $a $b" ;;
            *) log "skip (unknown kind '$kind'): $delay $kind $a $b"; continue ;;
        esac
        delta=$(( ${delay:-0} - prev ))
        if [ "$delta" -gt 0 ] && [ "$DRY" = 0 ]; then
            sleep "$delta"
        fi
        prev=${delay:-0}
        log "t+${prev}s $target"
        [ "$kind" = "app" ] && do_app "$a" || do_launchd "$a" "$b"
    done
    log "=== stagger-login done"
}
```

LaunchAgent (`~/Library/LaunchAgents/com.<you>.stagger-login.plist`; adjust
the Program path):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.stagger-login</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/stagger-login</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>STAGGER_BASE</key>
        <string>150</string>
    </dict>
    <key>StandardErrorPath</key>
    <string>/Users/you/Library/Logs/stagger-login.launchd.log</string>
    <key>StandardOutPath</key>
    <string>/Users/you/Library/Logs/stagger-login.launchd.log</string>
</dict>
</plist>
```

Load it without rebooting:

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.stagger-login.plist
```

### De-commissioning each app's own autostart

The stagger only helps if the app isn't *also* starting itself early:

1. **Classic login items** — remove from System Settings → General →
   Login Items, or
   `osascript -e 'tell application "System Events" to delete login item "Warden"`.
   Some apps re-add the item on next launch; check for an in-app
   "launch at login" preference and turn it off there too
   (e.g. `defaults write app.betterstage.macos launchAtLogin -bool false`).
2. **LaunchAgents** — `launchctl disable gui/$(id -u)/<label>`; leave the
   vendor plist untouched on disk.

To revert an app to normal autostart: `launchctl enable gui/$(id -u)/<label>`
for agents, re-create the login item
(`osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Some.app", hidden:false}'`),
and delete its line from the config.

## Verification notes

1. Rehearse the launchd dance on a live service before depending on it:
   `disable` (confirm still running) → `bootout` (confirm stopped — this
   is what a disabled-at-login agent looks like) → `enable` + `kickstart`
   → observe the kickstart failure → `bootstrap` → confirm running →
   `disable` → confirm still running and listed in
   `launchctl print-disabled gui/$(id -u)`.
2. A dry-run mode (`--dry-run`) is worth the five lines it costs: it
   exercised the whole config parse and running-checks against the live
   system before anything moved.
3. Timing bug to avoid (shipped in v1 here, caught by a targeted test):
   if the loop sleeps each entry's *absolute* delay after the base wait,
   everything fires at `base + delay`. Credit the elapsed base/gate time
   (`prev = BASE + gate_extension`) and sleep only consecutive deltas.
4. Expect the gate's `log show` probe to cost a few seconds; that only
   ever shifts launches later, never earlier — the safe direction.

## Caveats and watch items

1. The Logi updater may re-enable its agent on update; re-run the
   `launchctl disable`. Logi mouse/keyboard remaps are also simply absent
   for the first `delay` seconds after login.
2. Default Folder X's open/save enhancements and BetterStage's window
   management are likewise inactive until their delay elapses — that is
   the trade you are making.
3. Apps with no "launch at login" pref key (Warden, DFX here) may re-add
   their login item when the stagger launches them; the script's
   running-check prevents double processes, but that app would return to
   launching early. Re-delete the item if a boot-time storm returns for
   just one app.
4. System-extension-based tools (Karabiner-Elements class) cannot be
   delayed this way and were not attempted.
5. When Apple ships the fix (watch point releases; 27.0.1 was current and
   affected at diagnosis time), delete the config lines and let everything
   boot normally again — the script with an empty config is a no-op.

## Related

- The live investigation notes and machine-local revert commands live in
  the operator's private notes; this document is the self-contained
  public write-up.
- TCC internals background: Apple's Threaded/privacy docs are thin;
  Howard Oakley's explainers on TCC.db and `tccutil` are the best
  practitioner references.
