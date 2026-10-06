# Apple Feedback Assistant draft — tccd boot-time code-identity race on macOS 27.0.1

Paste-ready. File under **System Settings / Privacy & Security (TCC)** with a
sysdiagnose captured within ~3 minutes after a fresh login (see bottom).
Anyone hitting the same bug is welcome to file a duplicate using this text.

---

**Title:** tccd fails code-identity lookups for ~2 minutes after login — apps
re-prompt for permissions despite intact grants (macOS 27.0.1)

**Area:** Privacy & Security / TCC (tccd)

**Description:**

On macOS 27.0.1, during the first ~2 minutes after login, tccd intermittently
fails to compute code identities for requesting processes and refuses their
TCC requests. Apps that launch in that window receive refusals for services
they are already granted (Accessibility, Input Monitoring / ListenEvent,
AppleEvents, Microphone), conclude permission is missing, and re-show grant
dialogs. The stored grants are intact: launching the same app ~2 minutes
after login works with no prompt and no re-grant. Every reboot reproduces;
worse under high boot load.

**Steps to reproduce:**

1. On macOS 27.0.1, have any third-party app with Accessibility / Input
   Monitoring / Apple Events permission configured to launch at login
   (reproduced with five different Developer ID–signed, notarized apps, e.g.
   Default Folder X, Logi Options+ agent, plus ~130 other bundle IDs
   including Apple's own Dock and widgets).
2. Reboot and log in.
3. Observe the app's permission dialog re-appear during the first ~2 minutes,
   despite System Settings still showing the grant enabled.
4. Dismiss the dialog, wait 2 minutes, relaunch the app — no prompt; the
   existing grant is honored.

**Expected:** TCC evaluates the stored grant correctly regardless of when the
app launches after login.

**Actual:** Requests inside the ~2-minute window are refused with
code-identity failures; apps re-prompt.

**Evidence (from `log show --last 48h --predicate 'process == "tccd"'`):**

```text
tccd ... [com.apple.TCC:access] Failed to get code reference from:
  TCCDProcess: identifier=com.trycua.driver, pid=…, auid=501, euid=501,
  binary_path=/Applications/CuaDriver.app/Contents/MacOS/cua-driver. 100024

tccd ... [com.apple.TCC:access] Refusing TCCAccessRequest for service
  kTCCServiceAccessibility from extension Sub:{…}

tccd ... internal_TCCCreateDesignatedRequirementIdentityFromMessage: Refusing
  TCCCreateDesignatedRequirementIdentityForService (kTCCServiceAppleEvents)
  accessing={…}: unable to compute designated requirement for:
  file:///Applications/Default%20Folder%20X.app/Contents/MacOS/Default%20Folder%20X
```

Timeline from three reboots inside 20 minutes on 2026-10-05 (login times
13:42, ~13:51, 14:01): failure bursts of 59–244 per minute during each
window, **zero** occurrences after minute ~2, and normal `Granting …`
decisions resume afterward. Affected identifiers included `com.apple.dock`,
`com.apple.notificationcenterui`, weather/news widgets, and 100+ third-party
apps. On-disk code signatures are healthy at the same time the failures
occur: `codesign -vv` ("satisfies its Designated Requirement") and
`spctl --assess` ("accepted; Notarized Developer ID") pass for every affected
app, so this is not signature invalidation from an update.

**Notes / workaround:**

- `tccutil reset` does not help (grants are intact) and causes extra prompts.
- Workaround in use: delay the affected apps' launches past the window via a
  login-time stagger script (log-gated on "Failed to get code reference").
- Machine: Apple silicon (arm64), macOS 27.0.1 (Build 26A434). No user-level
  TCC.db exists to inspect; all observations via the unified log.

**Sysdiagnose to attach:** capture immediately after a fresh login while the
failure burst is still occurring (within ~2 minutes of the desktop appearing):
`sudo sysdiagnose tcc_boot_race`, and attach the resulting archive plus a
`tccd`-filtered log capture from the same window:
`log show --last 5m --style compact --predicate 'process == "tccd"' > tccd_boot.log`
