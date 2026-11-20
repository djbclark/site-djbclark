# Plan: add m11, kob, g6c to the fleet and fix their quirks

Date: 2026-11-20. Status: **plan, with one executed step:** the m11 rotation lock was applied and reboot-tested on 2026-11-20 (section X). Everything else below, including inventory, Termux/Shizuku, debloat and the other devices, is still unchanged. (Earlier the same day the dead `cswap_quota_context.sh` SessionStart hook was also removed from `~/.claude/settings.json`; unrelated to the devices.)
Where it lives: `site-public-djbclark/docs/plans/new-devices-2026-11-20/` (raw research reports beside it: `research-*.md`).
Evidence tags: **[observed]** read from the m11 over USB today; **[doc]** fetched vendor/AOSP source; **[forum]** community report; **[inference]** reasoning, untested.

## I. Summary and the three decisions I need

1. **m11 (Lenovo TB336FU)** — it is a real Android 16 tablet and fits the existing Termux/Shizuku/Tailscale fleet model. Rotation fix is a ladder (section III.B); the strongest candidate is `wm fixed-to-user-rotation enabled`, which lives in `display_settings.xml` and needs no app running at boot. **Not yet tested on the device.**
2. **kob (Kobo Clara Colour)** — **not Android and cannot be made Android.** Secure-boot chain is signature-checked, no unlock/ROM/port exists, eMMC is soldered (brick risk). Best path: keep Kobo firmware, add KOReader + NickelMenu + SSH + Tailscale, pinned to firmware 4.x. If you truly need adb/Shizuku/Termux/Tasker on e-ink, buy a native-Android e-ink device (Boox first).
3. **g6c (Galaxy Watch 6 Classic)** — Wear OS, adb only over Wi-Fi wireless-debugging (random ports, no USB data, no adb-over-Bluetooth). Joins as a *separate, non-Termux* host class; Tailscale on the watch is unproven.

Decisions needed from djbclark (details in section VII):

1. m11: which portrait do you want — **0° (normal)** or **180° (upside-down)**? It is **currently locked at 180°** [observed], which looks accidental.
2. m11: OK to do **one controlled reboot test** (about 5 minutes, tablet unusable meanwhile) to catch what resets rotation at boot?
3. kob: keep it on Kobo firmware (recommended), or replace it with a Boox-class Android e-ink device?

## II. Device identity and proposed inventory entries

Inventory file: `site-public-djbclark/inventory/hosts.yml` ("a new device = add a host, assign taxonomy groups"). Generic per-model quirks go in the product repo `stayturgid` `ansible/inventory/group_vars/<group>.yml` (synced by `just site-sync`); site-only overrides in `site-public-djbclark/inventory/group_vars/`.

| Host | Real device | OS | Serial (USB) | Taxonomy groups to add | Joins `stayturgid` (Termux ansible, :8022) deploy group? |
| --- | --- | --- | --- | --- | --- |
| **m11** | Lenovo **Idea Tab 11** (TB336FU, a.k.a. Tab K11 Gen 2 / Xiaoxin Pad 2025 11"); market name on device: "Lenovo Idea Tab". Dimensity 6300 per sources [doc]; *the "M11/TB330/Helio G88" threads are only cousins* | Android 16, ZUI 17.5.10.321 (ST_260804), patch 2026-08-05 | `HA2PMV18` [observed] | `android_16`, new `vendor_lenovo`, new `model_idea_tab_11` | **Yes**, after Termux + sshd + Shizuku are installed (neither is installed today [observed]; Tailscale app is) |
| **kob** | Rakuten Kobo Clara Colour (N367B-class, Kaleido 3), MediaTek MT8113-family, 4.9 Linux kernel | **Linux + Nickel, not Android** | not applicable (no adb); record MAC + firmware version | new `linux_embedded`, new `vendor_kobo`, new `model_kobo_clara_colour` | **No** — different connection class (ssh root, BusyBox, no Python). Own group `kobo_fleet`; do not let `just deploy` target it |
| **g6c** | Samsung Galaxy Watch 6 Classic (SM-R950 43 mm or SM-R960 47 mm — confirm) | Wear OS (4→5→6; One UI Watch 5–8) | none — adb over Wi-Fi only | new `wear_os`, `vendor_samsung`, new `model_galaxy_watch_6_classic` | **No** (initially) — own group `wearos_fleet`; adb connect IP:port changes every toggle |

Missing facts to collect before editing inventory: Tailscale IPs, LAN IPs (DHCP reservations on 192.168.68.0/24), watch model/size, kob firmware version (Settings > About), which of the three the operator wants `firerpa_enabled` on (default: m11 yes after test; kob/g6c no).

## III. m11 (Lenovo Idea Tab 11, TB336FU)

### A. Observed state (adb, read-only, today)

- Rotation: `accelerometer_rotation=0` (locked), **`user_rotation=2` (180°)**; WM shows `mUserRotationMode=LOCKED, mUserRotation=ROTATION_180`, `mAllowAllRotations=true`, `mSetIgnoreOrientationRequest=true` (apps' own orientation requests are ignored — Android 16 large-screen behaviour), `fixed-to-user-rotation` = **default**, `camera_autorotate=1` with `mCameraRotationMode=1` (a camera-based rotation component, `OvCameraRotation`, is active).
- Rotation lock history: the only entry is **`11-19 11:56:42 mode=LOCKED rotation=ROTATION_0 caller=DisplayRotationReversionController#revertOverride`**, about 2 minutes after the last boot (uptime 22 h). The 180° value was written later by something that bypasses the lock history (a direct `Settings.System` write — a WRITE_SETTINGS holder, e.g. the installed *Rotation Control* tile app, is the only such app granted it) [observed + inference].
- Boot: bootloader **locked**, verified boot green, encrypted, `ro.debuggable=0`. Last shutdown reason in history is **`shutdown,battery`** (battery ran flat) — a cold boot after an empty battery is a realistic "startup" case.
- Third-party rotation/automation apps installed: Rotation Control (tile), Tasker + AutoInput, Key Mapper, MacroHandler, SecondScreen, Taskbar. **None has `WRITE_SECURE_SETTINGS`** [observed]. Two accessibility services are enabled (Smart Launcher lock-screen service and Quick Search).
- Load: load average ~13 on 8 cores, RAM 99% used, 1.1 GB swap in use, `systemui` 25% CPU [observed] — consistent with ZUI's memory cleaner (B1 below); no root cause confirmed.
- Developer: `adb_enabled=1`, `adb_wifi_enabled=0`, `persist.sys.usb.config=adb`; Tailscale app present; Shizuku and Termux **absent**; no device owner (`Device Owner Type: -1`).

### B. Rotation not remembered — diagnosis and fix ladder

**Honest status:** no public report of "TB336FU rotation lock resets at boot" exists [doc, 30+ searches]. The ladder below comes from AOSP source plus adjacent ZUI bugs.

What AOSP guarantees [doc]: the lock is two `Settings.System` keys (`accelerometer_rotation`, `user_rotation`) which survive reboot; but (a) an app's own orientation request beats the lock on stock Android, (b) `wm fixed-to-user-rotation enabled` is stored per display in `/data/system/display_settings.xml` instead, ignores app requests, and needs no sensor — so it should survive reboot and ignore late-starting apps. ZUI could still layer its own policy on top (untested).

Candidate causes for the symptom (ranked by my judgement; confirm with step 1):

1. **H1 — something rewrites the keys during/after boot** (Tasker/Key Mapper/Rotation Control profile, ZUI "Smart Rotate", or the camera-rotation component). Evidence: the 180° write bypassing lock history.
2. **H2 — ZUI resets rotation state at boot** (R2/R3 forum bugs: sensor service dying on ZUI 17.5, lock screen sticking landscape).
3. **H3 — the lock holds, but the *lock screen/launcher* starts in the wrong orientation until an app takes over** (R3 report; your "third-party apps kick in later" matches this).
4. **H4 — late third-party app start** (ZUI background/autostart management delays `BOOT_COMPLETED`) — explains why the apps "eventually" work.

Plan (each step reversible; steps 2+ need your yes for the reboot):

1. **Read-only capture** (done in part today). Add: `dumpsys window | rg -A9 RotationLockHistory`, `wm user-rotation`, `wm fixed-to-user-rotation`, `wm get-ignore-orientation-request`, and a full `logcat -b all` dump saved right after the next boot.
2. **Apply the system-level lock now** (no app involved): `settings put system accelerometer_rotation 0`; `wm user-rotation lock 0` (or the angle you pick); `wm fixed-to-user-rotation enabled`; `settings put secure camera_autorotate 0`. Re-read all four.
3. **Controlled reboot test** (needs your OK): reboot, **do not open any app**, read the keys + `display_settings.xml` value + lock history via adb the moment adb is up, then repeat once after force-stopping Tasker/Key Mapper/Rotation Control (or disabling their boot receivers) to separate H1/H4 from H2/H3.
4. **If a third-party app is the writer (H1/H4):** remove its rotation profile or stop using it — the system lock now makes it redundant; revoke its WRITE_SETTINGS if unused (`cmd appops set PKG WRITE_SETTINGS deny`).
5. **If ZUI resets the system state (H2/H3):** re-assert at every adb attach from the Mac (the existing hd8 pattern: `firerpa_recovery_mode: control-node-adb` — Mac adb supplies persistent shell UID). Add a healing-registry ID (e.g. `m11.rotation_locked_portrait`) in stayturgid `tests/healing_registry.json` so `just test` requires a mechanism that restores it. As a second layer, give a rotation-tolerant on-device app `WRITE_SECURE_SETTINGS` via `pm grant` (Tasker is already installed) triggered on boot.
6. **Acceptance:** three consecutive reboots (normal, power-button hold, battery-dead cold boot) each show portrait on the lock screen and launcher with **no** third-party app having run; lock history shows no rewrite.
7. **Document** the result as the `model_idea_tab_11` group_vars quirk (generic) and the chosen angle as a site override.

### C. Other m11 quirks (divergence from base Android) and fixes

Numbering for tickets: **M1…M12**.

| # | Quirk | Evidence | Fix / plan |
| --- | --- | --- | --- |
| M1 | **ZuiMemoryCleaner** force-stops background apps (Termux/Shizuku/Tailscale would die); matches today's 99% RAM and load ~13 | [forum] Lenovo P11 / TB350FU, TB373FU on ZUI 17.5 | Test `adb shell setprop persist.debug.zuimemory.enable false` (reboot, read back); reversible with `true`. Unverified on TB336FU. |
| M2 | Autostart / background manager unknown on ZUI 17.5; no doc found | [doc gap] | Inspect Settings > Battery/Apps on device; whitelist: `cmd deviceidle whitelist +com.termux +com.tailscale.ipn +moe.shizuku.privileged.api`; set standby bucket `active`. |
| M3 | Wireless-debugging port changes on every enable and reboot; Shizuku needs a restart after each boot; Android 16 has no adb Wi-Fi auto-reconnect | [doc] Shizuku guide, Android adb docs | USB-attached m11: keep Mac as persistent adb (hd8 pattern). On Wi-Fi: Developer options → "Disable adb authorization timeout", default USB config "No data transfer", Termux-side `adb tcpip` helper; re-arm Shizuku from the Mac after each boot. |
| M4 | Termux children killed by Android's phantom-process limit (signal 9) | [forum] termux-app #2366 | `settings put global settings_enable_monitor_phantom_procs false` and `device_config put activity_manager max_phantom_processes 2147483647`, or Developer options toggle. |
| M5 | **OTA**: frequent ZUI updates; Android 15→16 shipped with ZUI 17.5.10.x; broke other Lenovos (crashes, cleaner kills) | [forum] | Pin a known-good build; record fingerprint in inventory; consider `pm disable-user --user 0 com.lenovo.ota` after testing (inference, reversible). Re-run the quirk script after every OTA. |
| M6 | **Bootloader locked, no root**; unlock path on this SoC unknown (cousin TB330FU needs mtkclient + patched lk) | [forum] | Treat as unrooted. Don't attempt unlock; fleet runs on Shizuku (uid 2000). |
| M7 | Large-screen policy (Android 16, sw ≥ 600dp): apps cannot force orientation; ZUI "Smart Rotate" per-app list overrides in addition | [doc] Android 16 behaviour changes; [forum] | Rely on system lock (III.B); if apps still rotate, check Settings > Display > Smart Rotate > App Management. |
| M8 | **PC/Desktop mode** and "Ready For" tile (Motorola stack) change display policy; freezes reported | [forum] | Keep `persist.sys.zui.pcmode=0` [observed 0]; remove/avoid the Ready For QS tile. |
| M9 | Hall sensor + folio case; "double-tap to wake" cause spurious wakes | [forum] low | Keep magnets/cases away; disable double-tap wake if tablets wake in a rack. |
| M10 | USB-C is USB 2.0; default USB config matters for adb staying authorized | [doc] | Default USB config → charging/no data; use a data cable. |
| M11 | Pre-installed Lenovo/ZUI/Motorola stack (~70 packages: tbengine, appdaily, lsf, whatsnew, weather, OMADM…) | [observed] + [doc] debloat guide | Optional `pm disable-user --user 0 PKG` for a vetted list; **never** touch systemui, settings, gms/gsf, com.lenovo.ota (until tested), pen stack. One commit per batch with a restore command (`cmd package install-existing`). |
| M12 | Heavy system load and flat-battery shutdowns | [observed] | Check charging config ("Charge Optimization"); re-measure load after M1; add `battery` to the fleet health probe. |

Order of work for m11: III.B step 1→2→(approval)→3, M1, M2–M4 (needed before Termux/Shizuku are trustworthy), install Termux + Shizuku + native agent via the existing stayturgid provisioning, then inventory entry, then M5–M12.

## IV. kob (Kobo Clara Colour)

### A. What it is (and is not)

- Linux 4.9.77 + Kobo's Qt "Nickel" UI, BusyBox userland, MediaTek MT8113-family SoC, ~512 MB RAM, 16 GB soldered eMMC [doc/hands-on teardown]. **No adb, Shizuku, Termux, Doze, accessibility API, or Developer options** — "devmode" is a hidden Nickel menu, not Android's.
- Root shell is available (stock SSH toggle or KOReader's dropbear); **the bootloader/secure-boot chain is locked** (signature checks seen on UART; no public unlock/exploit).

### B. Can it be turned into "normal Android"? (answer: no)

Ranked, with evidence quality:

1. **Stay on Kobo firmware and add KOReader + NickelMenu + SSH + Tailscale.** Documented, reversible, low risk. Gives a hackable Linux box, not Android APIs. *(Recommended.)*
2. **Buy a native-Android e-ink device** (Boox first; Bigme/Meebook/Hisense alternatives) if adb/Shizuku/Termux/Tasker are hard requirements. Boox spec pages could not be fetched, so verify model + Android version + Play Services before buying.
3. Hobby: Nerves/Buildroot from a loop image under Kobo's own kernel (UART soldering; not Android; e-ink WIP).
4. **Do not attempt:** replacing boot partitions, an Android port, or an Android chroot — no unlock/ROM exists, ~500 MB RAM, no e-ink path for Android, real brick risk with no restore path.

### C. Quirks and fixes (K1…K12)

| # | Quirk | Plan |
| --- | --- | --- |
| K1 | **Firmware generation split**: 4.x (Qt5) vs 5.x/6.x (Qt6, update.tar). Kobo's 6.0.x opt-in beta (6.0.279225, Nov 2026) breaks stock NickelMenu/KFMon; 6.0.274403 had a **data-loss bug** (sideloaded books/notes) and Kobo says do **not** roll back | **Pin to 4.x**; never accept the "update to 6.0" prompt; record firmware version in inventory; back up the whole device before any change. |
| K2 | SSH toggle is awkward: rename `.kobo/ssh-disabled`→`ssh-enabled`, reboot; ForceCommand blocks `ssh host cmd`, scp, sftp; root home is `/` so keys go in `/.ssh/authorized_keys`; `ssh-copy-id` fails | Use KOReader's dropbear SSH (scp/sftp work, port 2222) as the file channel; pipe commands over stdin on stock SSH. Root password in sudo-secretspec, never in repo. |
| K3 | **Wi-Fi powered off on sleep** (no Doze whitelist); can wedge after wake; restarting KOReader while wedged can reboot | KOReader "Restore Wi-Fi connection on resume"; NickelMenu `force_wifi`; keep on charger; avoid restarting KOReader in a wedged state. |
| K4 | **Suspend while charging hangs MTK Kobos** | Leave KOReader's refusal-to-suspend alone; hold power 10–20 s to hard-reset. Don't treat as always-on kiosk without testing. |
| K5 | No CA bundle; `/var/*` is tmpfs → VPN state lost each boot | Tailscale state under `/etc` or `/opt`; install `ca-certificates.crt`; `sync` after editing rcS; start via `nohup setsid`. |
| K6 | Tailscale: no official client; KOReader plugin (runs only while KOReader runs) or hand-hooked boot daemon (untested on Clara Colour) | Try the KOReader Tailscale plugin first; boot daemon only if always-on is required. |
| K7 | OTA rewrites rootfs → KFMon/NickelMenu/rcS hooks vanish | Keep KoboRoot.tgz / Kobo.tgz + KOReader zips under fleet control; re-run installer script after every update; re-verify SSH/Tailscale. |
| K8 | 5.x/6.x boot counter: four boots without Nickel resetting it → factory-reset prompt | Only matters if booting straight into another app; run `bootcount-ctl reset`. |
| K9 | Hidden-folder indexing on fw ≥ 4.17 | Set `ExcludeSyncFolders` regex in `.kobo/Kobo/Kobo eReader.conf`. |
| K10 | Kaleido 3 colour ghosting; slow refresh | Not for dashboards; use KOReader full-refresh settings, devmode CFA presets. |
| K11 | Sideloaded books don't cloud-sync | Leave unsigned-in, or use a fleet account; push content over SSH/OPDS. |
| K12 | **Screen rotation persistence: unknown** — no source found; Nickel keeps orientation as a UI setting | Test on the unit; KOReader has its own rotation setting. |

### D. Plan

1. Operator records firmware version + model code; photo/copy of the whole device to the Mac (`.kobo`, `.adds`).
2. Install KOReader + KFMon + NickelMenu via the mobileread one-click package (4.x). If already on 5.x/6.x: nicoverbruggen NickelMenu fork `Kobo.tgz` + KOReader "kobov5" build.
3. Enable SSH (K2), set auto-restore Wi-Fi (K3), test Tailscale plugin (K6).
4. Add `kob` as a **non-Termux** host (separate group, ssh root) with only a health check (reachable? firmware version? battery). No Ansible deploy plays.
5. **Fallback path:** if the use case needs Android APIs, spec and buy a Boox-class device as a *new* host (`boox_*`), then repeat the Android fleet flow.

## V. g6c (Galaxy Watch 6 Classic)

### A. Observed constraints [doc/forum, nothing tested on the watch]

- adb **only over Wi-Fi wireless debugging**: pairing port + separate connect port, both random and changing each toggle. **No USB data** on the wireless puck; **no adb-over-Bluetooth** on Wear OS 3+.
- Samsung holds Wi-Fi in "Auto" (off while the phone is Bluetooth-connected). Developer options → "Turn off automatic Wi-Fi", Wi-Fi On, and "Stay awake when charging".
- Samsung dev-mode path: Settings > About watch > Software information > tap Software version (5–7 times).

### B. Quirks and fixes (G1…G10)

| # | Quirk | Plan |
| --- | --- | --- |
| G1 | Pair + connect with two ports; stale after reconnect | Per-visit procedure in a runbook: toggle Wireless debugging, read both ports, `adb pair` then `adb connect`; platform-tools ≥ 30. |
| G2 | Wi-Fi auto-off / debugging switches itself off | "Turn off automatic Wi-Fi", Wi-Fi On, "Stay awake when charging", keep on charger. |
| G3 | AP/client isolation breaks `adb pair` ("unable to start pairing client") | Same non-isolated VLAN; provision via phone hotspot if needed. |
| G4 | **Tailscale: no official client**; third-party "Tailware" is a private preview, VPN permission must be granted via adb (AppOp `ACTIVATE_VPN`); phone VPN can block the 1.8 GB OTA | Treat Tailscale on watch as unproven. Reach it via LAN adb only; evaluate Tailware as a separate experiment. |
| G5 | Fixed IP: no static-IP UI found | DHCP reservation on 192.168.68.0/24. |
| G6 | Shizuku works (GW7/Wear OS 6 reports); no autostart upstream; no round UI; Termux possible but unverified | Autostart fork if needed; install via `adb install -r -g`. |
| G7 | Wear OS battery/Doze: whitelist with `dumpsys deviceidle whitelist +PKG`; phone-side "Allow background activity" in Galaxy Wearable | Re-apply after reboot/OTA. |
| G8 | OTA: block with `pm disable-user --user 0 com.sec.android.soagent` and `com.wssyncmldm`; **rollback prevention since March 2026**; One UI 8 lag/battery drain reported on GW6 Classic | Block updates until a build is vetted; no downgrades possible. |
| G9 | Captive-portal Wi-Fi drops instantly | `settings put global captive_portal_mode 0` (undo: `settings delete global captive_portal_mode`). |
| G10 | Needs Galaxy Wearable on an Android phone for first setup; factory reset = re-pair everything; bootloader unlock reportedly bootloops/bricks LTE models | Keep treated as locked, unrooted; record the setup phone. |

Not found at all (test on device): rotation/orientation, accessibility services, static IP.

### C. Plan

1. Operator enables developer mode and Wireless debugging; provide model, Wi-Fi, IP.
2. First connect from the Mac (G1/G2); record Wear OS version, patch level, fingerprint.
3. Apply G2, G7, G8 (disable update agents), G9 if relevant.
4. Add `g6c` as a non-Termux host in `wearos_fleet` with an adb-based health probe only; decide on Shizuku/Tailware after a measured battery test.

## VI. Inventory and repository work (after the test results above)

All edits in a claimed workspace, small commits, `git-commit-own`:

1. `site-public-djbclark/inventory/hosts.yml`: add `m11` to `stayturgid` (after Termux/Shizuku are up) with `device_usb_serial: HA2PMV18`, `device_label: Lenovo Idea Tab 11 (TB336FU)`, Tailscale + LAN IPs, `firerpa_recovery_mode: control-node-adb` if USB-attached; add `kob` / `g6c` under new non-Termux groups; add taxonomy groups (`android_16` for m11; `vendor_lenovo`, `model_idea_tab_11`, `vendor_kobo`, `model_kobo_clara_colour`, `wear_os`, `model_galaxy_watch_6_classic`).
2. `stayturgid/ansible/inventory/group_vars/`: `vendor_lenovo.yml` / `model_idea_tab_11.yml` with the M-series settings (rotation lock, memory-cleaner property, whitelist, phantom-process flags); `model_kobo_clara_colour.yml`, `model_galaxy_watch_6_classic.yml` for generic quirks. Then `just site-sync`.
3. `registry/identity-patterns.yml` and `inventory/group_vars/all.yml` (Prometheus targets, machine_name labels): add m11 (and g6c if it gets a reachable target); keep Kobo out of Termux-based monitoring.
4. Add healing-registry IDs for the m11 rotation lock and each persistent property; `just test` must stay green (run on GitHub CI per repo rules).
5. Docs: add the quirk tables above to `stayturgid/docs/` (device notes) and trim this plan to a pointer once done.

## VII. Open questions and gates

1. **Portrait angle** for m11: 0° or 180°. (Current 180° looks accidental.)
2. **Reboot test** approval (III.B step 3).
3. **kob**: keep on Kobo firmware (recommended) or replace with a Boox-class Android device? Also its firmware version and whether it has already been offered/accepted the 6.0 beta.
4. **g6c**: model size (SM-R950/R960), Wi-Fi/SSID, and whether it is allowed to stay on a charger as a fleet member.
5. Does `m11` get `firerpa_enabled: true` after testing (default: yes, like t2e)?
6. Any destructive step — factory reset, bootloader unlock, firmware change, debloat batch, OTA disable — needs your explicit yes first; none is planned to run unasked.

## VIII. Research gaps (could not verify)

- No TB336FU-specific rotation-reset report; ZUI-specific overlays/props that pin portrait are unverified (AOSP shows no `persist.sys.*` lever).
- XDA TB330FU root thread, manualslib manual body, several Reddit pages were not fetchable (see each report's "Not fetched" list).
- Kobo: warranty text, Boox/Hisense/Meebook specs, Clara-Colour-specific SSH/Tailscale behaviour on 6.0 were not verified; most Wi-Fi/suspend evidence is from Clara BW / Libra Colour / Tolino.
- Watch: static IP, rotation, accessibility, Tailware behaviour are unverified.

## IX. Evidence files

- `research-m11.md` — m11/TB336FU quirks (30+ queries, AOSP source read).
- `research-kob.md` — Kobo Clara Colour divergence-from-Android quirks.
- `research-kob-android-conversion.md` — can it be made Android, ranked options, exact steps.
- `research-g6c.md` — Galaxy Watch 6 Classic quirks.

## X. Update 2026-11-20 (later): m11 reboot test result and decisions

**Decisions from djbclark:** reboot test approved; **0° for now**. Later requirement (not now): **180° while on power, 0° otherwise** (see below).

**Test run (adb, USB, no third-party app opened):**

1. Applied: `settings put system accelerometer_rotation 0`; `wm user-rotation lock 0`; `wm fixed-to-user-rotation enabled`; `settings put secure camera_autorotate 0`. Read back: accel 0, user_rotation 0, fixed enabled, camera rotation 0, current rotation 0.
2. `adb reboot`; adb back and `sys.boot_completed=1` after about 38 s.
3. First reading at boot completion, and again at +25 s, +60 s and +2 min: **accelerometer_rotation=0, user_rotation=0, fixed-to-user-rotation=enabled, mCurrentRotation=ROTATION_0, locked.** No rewrite appeared in the lock history after boot; the lock screen was up (keyguard showing).
4. **Result: the system-level lock survives a normal reboot.** Raw readings: `m11-rotation-test-readings.md` beside this file (the boot logcat is deliberately not kept: it holds account data).

**Caveats (not yet tested):**

- This was a software reboot (`adb reboot`), not a **battery-dead cold boot** and not a power-button reboot. The earlier boot reason was `shutdown,battery`, so the cold-boot case still needs a run (needs a person to press power).
- The third-party rotation/automation apps (Tasker, Key Mapper, Rotation Control, MacroHandler) did not run a rotation write in this window, so their possible interference is still open; Rotation Control's WRITE_SETTINGS grant is the one to watch.
- `ignoreOrientationRequest` read **true** right after boot completed and **false** about a minute later (it was true before the reboot). Unexplained; probably ZUI/Android 16 large-screen policy settling. With fixed-to-user-rotation enabled it should not matter for rotation, but re-check after the next boot.
- Acceptance still needs the three-boot matrix in section III.B step 6.

**Next for m11 (0° only):** record the four commands as the `model_idea_tab_11` desired state; add a healing-registry ID; decide whether to remove the third-party rotation apps' write access.

**Later: 180° on power, 0° otherwise.** Not designed yet. Options: (a) a Mac-side adb watcher (`dumpsys battery` AC/USB powered → `wm user-rotation lock 2`, else `lock 0`) while USB-attached; (b) on-device Tasker/Key Mapper profile on the power-connected event with `WRITE_SECURE_SETTINGS` granted by `pm grant`; (c) Android 16 docked/charging-state rotation setting if ZUI has one (unknown). Note that `fixed-to-user-rotation` keeps the angle stable, so changing the user rotation is enough; the event source is the open piece.

## XI. kob alternative: Android e-ink (research, 2026-11-20)

Goal from djbclark: an alternative to the Kobo Clara Colour that runs Android and is easy to program and control.

**Recommendation: a Boox colour ePaper device.** Onyx Boox ships full Android with the Google Play Store and sideloading (official store pages, fetched), which gives adb, Termux, Shizuku-style tooling and normal Kotlin apps. Onyx also publishes an e-ink SDK with sample code (`onyxsdk-device` `EpdController`, refresh/update modes, front-light control): https://github.com/onyx-intl/OnyxAndroidDemo.

Candidates (prices as shown on shop.boox.com on 2026-11-20; verify before buying):

| Model | Screen | Android (per store page) | Price | Note |
| --- | --- | --- | --- | --- |
| **Palma 3** | 6.13" colour, 300 PPI B&W / 150 PPI colour | Page lists several Android versions in a comparison table; **confirm 16 vs 15 before buying** | US$339.99 | Closest size to the Clara Colour; phone-shaped |
| **Note Mini C** | 8.52" Kaleido 3 colour | **Android 16** | US$579.99 | "Available soon" on the shop page |
| **Note Air6 C** | 10.3" colour, 6 GB RAM, 64 GB | **Android 16** | US$579.99 | Largest; keyboard cover via pogo pins |

**Why it is easier to program and control than the Kobo:** normal Android toolchain (adb, Gradle on CI, Termux), Play Store, and the Onyx SDK for refresh control; the fleet's existing Android flow (Termux sshd, Shizuku, Tailscale) should apply.

**Unverified / to check before buying** (could not confirm from fetched pages): whether Boox's wireless debugging and Shizuku behave normally; Boox's battery manager / app-freezing behaviour (known to exist from memory, not verified here); bootloader/root status; OTA behaviour; data-handling of the Onyx cloud services (Chinese vendor). Treat as a new m11-style host: run the same probe and quirk plan after the first boot.

**Alternatives not researched in depth:** Bigme, Meebook, Hisense (Android e-ink); I could not fetch their spec pages.

## XII. Brilliant Labs Halo (asked 2026-11-20; not a fleet device)

From Brilliant Labs' own docs (https://docs.brilliant.xyz/halo/halo-sdk, fetched): Halo is **not Android**. It is a Bluetooth LE peripheral with a small low-power chip and no app launcher or app installation; a "host" app on a phone or computer drives it, optionally with Lua scripts run on the glasses. Official SDKs: Python (Mac/Linux/Windows), Flutter (iOS/Android), Web Bluetooth; firmware is open source at https://github.com/brilliantlabsAR/halo-firmware. The chip (reported as an Alif B1 by a secondary source) and its OS/RTOS were not confirmed. For this fleet it would be a Bluetooth-paired accessory of a host (m11 or the Mac), not an ssh/adb node; closer to "non-Android" like the Kobo, but with no shell at all.
