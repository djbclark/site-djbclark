STATUS: done

# Galaxy Watch 6 Classic (SM-R950 43mm / SM-R960 47mm; Wear OS 4->5->6, One UI Watch 5/6/7/8) - ops-fleet quirks vs stock Android

Research date 2026-11-20. Tools: shared firecrawl (firecrawl_search, firecrawl_scrape, firecrawl_developer_search). Read-only. Confidence tags: high = official doc or reproduced by several sources; med = consistent forum reports; low = single forum post, search snippet only, or my inference (flagged "INFERENCE"). Reddit comment claims are community claims, not verified by me on hardware.

## 0. Bottom line for a fleet

1. Only transport: Wi-Fi wireless debugging (Android-11-style pair + connect, both ports random). No USB data on the Classic's wireless puck, no adb-over-Bluetooth bridge on current Wear OS. Plan on: watch on charger + Wi-Fi forced on + "Stay awake when charging".
2. Wi-Fi radio is power-managed by Samsung (Auto mode; off while phone BT-connected, on again when phone leaves). Fixed Wi-Fi/adb reachability is the main operational fight.
3. Tailscale: no official watch client found. Only third-party "Tailware" (private, debug-signed preview, validated on Watch5 Pro, never a live-VPN test) and a Hermes "wearos" plugin that embeds a tailnet node. VPN permission must be granted over adb (AppOp ACTIVATE_VPN), not by dialog.
4. Shizuku works on Galaxy Watch (reported GW7 / Wear OS 6, Pixel Watch 4); Termux-on-watch is possible but I could not fetch the how-to pages (see fetch failures).
5. OTA: Samsung pushes One UI Watch updates; they can be blocked with adb (pm disable-user of two packages). Rollback prevention since March 2026; One UI 8 reported to cause lag/battery drain on GW6 Classic (factory reset fixed it for one user).
6. Bootloader: One UI 8 Watch reportedly has an OEM-unlock/bootloader unlock, but custom binaries bootloop and LTE models can hard-brick. Treat as not rooted/unlockable for fleet purposes.

## 1. adb / debugging

### 1.1 Pairing is mandatory; two different ports
- Symptom: `adb connect IP` or `IP:5555` gives "debugging isn't allowed"/"offline"/"failed to connect"; "adb: usage: unknown command pair" on old adb; recipes written for Watch 4 / Wear OS 3 ("Debug over Wi-Fi", port 5555) fail on GW6.
- Cause: GW6 (Wear OS 4+/One UI Watch 5+) uses Android-11 wireless debugging: one pairing socket (random port + 6-digit code, shown under "Pair new device") and a separate connect socket (shown on the main Wireless debugging screen). Ports change on each toggle/screen open. Pairing only authorizes the computer key.
- Fix: Developer options > ADB debugging ON > Wireless debugging ON (dialog: "Always allow on this network" > Allow) > Wireless debugging > Pair new device. Then `adb pair WATCH_IP:PAIR_PORT` (enter code; Samsung's doc uses `adb pair IP:PORT CODE`), back out, `adb connect WATCH_IP:CONNECT_PORT`, `adb devices` must say "device" not "offline". Use platform-tools >= 30 (Google); use `adb -s IP:PORT` when several devices. Re-run connect (new port) after every Wireless-debugging restart or Wi-Fi change.
- Sources: https://developer.android.com/training/wearables/get-started/debug-wifi ; https://developer.samsung.com/health/sensor/guide/connect-watch.html ; https://www.juggluco.nl/JugglucoWearOS/install/WearOS4.0 ; https://www.reddit.com/r/WearOS/comments/z31ny0/psa_adb_to_wear_os_3_requires_extra_steps/ ; https://www.reddit.com/r/GalaxyWatch/comments/15pf2iy/anyone_sideload_an_app_on_galaxy_watch_6_classic/
- Confidence: high.

### 1.2 Enabling Developer options (Samsung path differs from stock Wear OS)
- Samsung: Settings > About watch > Software information > tap "Software version" repeatedly (Samsung dev doc says 5 taps, third-party guides say 7; toast "Developer mode enabled"); may ask for PIN. Stock Wear OS/Pixel: Settings > System > About > Versions > Build number x7. Tapping the version again can toggle it back off (Juggluco).
- Master toggle OFF in Developer options kills ADB + wireless debugging at once and hides the menu (third-party claim).
- Sources: https://developer.samsung.com/health/sensor/guide/connect-watch.html ; https://anexplorer.io/devmode/android/watch ; https://www.juggluco.nl/JugglucoWearOS/install/adb.html
- Confidence: high (path), med (tap count / hide behaviour).

### 1.3 Wireless debugging keeps switching itself off / needs a Wi-Fi network
- Symptom: Wireless debugging toggle demands a Wi-Fi network then "automatically disconnects"; session dies; Wi-Fi flips off when the phone's Bluetooth is connected and flips ON again when the phone disconnects/leaves range (battery drain).
- Cause: Samsung/Wear OS Wi-Fi is "Auto" by default (radio held off while BT-linked to the phone); Wear OS also receives Wi-Fi credentials from the phone and may join other known SSIDs.
- Fix: Developer options > "Turn off automatic Wi-Fi" (Samsung's own guide step); Settings > Connections > Wi-Fi: set to On/"Always on" not Auto (on later watches it is only on/off); put watch on charger with Developer options > "Stay awake when charging" ON (a user reports this stopped the self-disabling); consider the "Automatic Wi-Fi when charging" developer toggle. One user said Wi-Fi came back on after a couple of days even with the toggle -> verify per fleet device. Turn phone BT off while pairing if it flaps.
- Sources: https://developer.samsung.com/health/sensor/guide/connect-watch.html ; https://www.reddit.com/r/GalaxyWatch/comments/1sdkj71/cant_turn_on_debug_over_wifi/ ; https://www.reddit.com/r/GalaxyWatch/comments/1se0jag/how_to_disable_galaxy_watch_turning_on_wifi_when/ ; https://anexplorer.io/devmode/android/watch
- Confidence: med.

### 1.4 "Failed: unable to start pairing client" / pair fails on the LAN
- Cause (user-confirmed, one case): the Wi-Fi network (client/AP isolation or blocked peer traffic); worked via a phone mobile hotspot. Google's doc: network must allow peer-to-peer traffic.
- Fix: same non-isolated VLAN/SSID, or phone hotspot for provisioning; `adb kill-server; adb start-server`; toggle Wireless debugging off/on; current platform-tools. Also see 1.3 (Wi-Fi going away).
- Sources: https://www.reddit.com/r/GalaxyWatch/comments/1ofuuz0/how_do_i_connect_my_watch_with_adb_im_desperate/ ; https://developer.android.com/training/wearables/get-started/debug-wifi
- Confidence: med.

### 1.5 No adb-over-Bluetooth/phone bridge, no USB
- Old Wear OS 2 method: enable "Debug over Bluetooth" in the Wear app, `adb forward tcp:4444 localabstract:/adb-hub`, `adb connect 127.0.0.1:4444` (phone USB-attached). On Wear OS 3+ the Wear/Galaxy Wearable/Pixel Watch apps no longer provide it (community answer in Google forum: "WearOS 3x debugging doesn't work through the old Wear app or the new Watch app"); Google's current docs list only Wi-Fi (and USB "on supported watches that have a USB connection, such as a charging cradle that supports data transfer"). Galaxy Watch chargers are wireless pucks with no data lines (third-party statement for Watch 4-7).
- Workaround for "no PC": a phone-side adb client on the same Wi-Fi (Bugjaeger, GeminiMan "Wear OS Manager", Shizuku/Termux adb) using the same pair+connect flow; GeminiMan needs both ports (pair, then connect) entered separately and watch approval.
- INFERENCE: BT debugging is not available on GW6; I did not test it. Samsung Odin/"Netodin" flashing exists as a recovery path (mentioned in a Watch5 thread) but is not an ops channel.
- Sources: https://miltschek.de/article_2020-04-20_Debugging+on+WearOS.html (old method) ; https://support.google.com/googlepixelwatch/thread/186187472/enabling-bluetooth-debugging-in-pixel-watch-app?hl=en ; https://developer.android.com/training/wearables/get-started/debugging ; https://anexplorer.io/devmode/android/watch ; https://www.reddit.com/r/GalaxyWatch/comments/15pf2iy/anyone_sideload_an_app_on_galaxy_watch_6_classic/
- Confidence: med-high.

### 1.6 Persistence of adb/dev settings
- Google doc: reconnect needed each time wireless debugging is restarted or Wi-Fi network changes (port changes). Master Developer-options-off disables both. There is no documented way on the watch to keep a fixed port; stock-Android `adb tcpip 5555` over an existing session is an untested idea on Samsung Wear OS (INFERENCE, low). Shizuku forks with "autostart"/"TCP mode" exist and one user runs a fork on a watch to auto-start ADB Wi-Fi at boot (for Tasker/AutoWear) - so re-arming after reboot is solvable with an on-watch Shizuku fork.
- Sources: https://developer.android.com/training/wearables/get-started/debug-wifi ; https://github.com/thedjchi/Shizuku/issues/219 ; https://github.com/timschneeb/awesome-shizuku/blob/5964688eece43ccf74d688a4b6f3e820116c7dd5/README.md
- Confidence: med (reconnect behaviour high; reboot persistence not directly sourced for GW6).

## 2. Network: fixed LAN IP, Tailscale

### 2.1 Fixed IP
- I found no source for a static-IP UI on Galaxy Watch Wi-Fi. INFERENCE: Wear OS Wi-Fi detail screen shows IP but (as far as I know) no static IP field; use DHCP reservation. Because the adb connect port is random per toggle anyway, discovery (arp/mDNS or reading the screen) is still needed. Juggluco says IP is viewable under Settings > Connections > Wi-Fi > (tap network). Confidence: low.
- Source for IP location: https://www.juggluco.nl/JugglucoWearOS/install/adb.html

### 2.2 Captive-portal Wi-Fi drops immediately
- Symptom: watch connects to captive-portal Wi-Fi then immediately "Can't connect to wifi network".
- Cause: Wear OS probes http://clients3.google.com/generate_204 and disconnects when not 204.
- Fix: over adb shell: `settings put global captive_portal_mode 0` (reset: `settings delete global captive_portal_mode`); then open http://example.com in the watch browser to sign in.
- Source: https://www.reddit.com/r/WearOS/comments/1epm2hn/guide_accessing_captive_portal_wifi_using_modern/
- Confidence: med-high.

### 2.3 Tailscale on the watch
- No official Tailscale client for Wear OS found (a Reddit/HA thread says WireGuard is not available on Pixel Watch; a Wear OS VPN app, V2rayTun, crashed on launch on a watch). Third-party: "Tailware" (fork of tailscale-android, Wear OS 3+, API 30+, standalone tailnet node, supports auth key/Headscale). Status: private, debug-signed, sideload-only preview; initial target Watch5 Pro SM-R925F; smoke test "VPN was not connected"; no battery/OEM audit; log upload to Tailscale defaults on. A Hermes marketplace plugin ("wearos") has the watch enroll its own tailnet node with single-use keys.
- Quirk: Wear OS shows no usable interactive VPN confirmation; Tailware ships a helper that grants only the AppOp ACTIVATE_VPN over adb (explicitly "pm grant is the wrong mechanism"). Exact command not seen (helper script not fetched); INFERENCE: `adb shell appops set PKG ACTIVATE_VPN allow`. It auto-recovers after reboot only if the user's last state was ON ("Explicit-ON reboot/update recovery"). Always-on VPN/lockdown kept off deliberately, so a signed-out VPN can't cut all watch networking.
- Implication: a watch cannot be reached over tailnet until the above is installed/authorized via adb first; while on tailnet you still pay Wi-Fi/LTE battery cost.
- Also: a VPN on the same Wi-Fi blocked the large Samsung OTA download in one report (see 5.2).
- Sources: https://github.com/vladbezm/Tailware ; https://hermes-agent.nousresearch.com/marketplace/wearos ; https://www.reddit.com/r/homeassistant/comments/1h12tv7/pixel_watch_vpn/ (search snippet only; page unfetchable) ; https://www.reddit.com/r/WearOS/comments/1rmbz0s/is_vpn_on_wear_os_real/
- Confidence: med (Tailware README is primary but preview-grade); low for "no official client" (absence of evidence).

## 3. Shizuku / Termux

### 3.1 Shizuku
- Works on Galaxy Watch: user reports GW7 on Wear OS 6, "Shizuku (rootless)" installed with `adb install`, started via wireless debugging on the watch itself, then App Ops (Shizuku-enabled) used to grant MANAGE_EXTERNAL_STORAGE to file managers (Material Files, MiXplorer). Also Pixel Watch 4 working with a fork; rish-mcp project runs the same APK on Wear OS 3+ with Shizuku (uid 2000 shell).
- Quirks: Shizuku via wireless debugging needs the watch's Wi-Fi up and Wireless debugging enabled at start, and does not survive reboot unless a fork with autostart/TCP mode is used (thedjchi fork, ShizukuPlus etc.). No round-screen UI in upstream/forks yet (request open, planned, low priority). Official RikkaApps Shizuku has not been updated in over a year and is reported broken on Android 17 (Wear OS 6 is Android 16, sdk 36, so OK for now). Wear OS may apply "more aggressive battery management than a phone", so a Shizuku-driven foreground service needs real-device testing (rish-mcp doc).
- Fix: install via adb; prefer an autostart fork; whitelist app from battery optimization (see 4).
- Sources: https://www.reddit.com/r/GalaxyWatch/comments/1mfqxao/successfully_got_shizuku_semiroot_running_on_my/ ; https://github.com/thedjchi/Shizuku/issues/219 ; https://github.com/turin-dev/rish-mcp/blob/5ee7134f6076338eb14cd64e3cafec2d3d104626/before/docs/WEAR_OS.md ; https://github.com/timschneeb/awesome-shizuku/blob/5964688eece43ccf74d688a4b6f3e820116c7dd5/README.md
- Confidence: med (works) / high (needs wireless debugging).

### 3.2 Termux
- Feasible: sideloaded Termux on watch is reported (search snippets): XDA "[Guide] Linux on Wear OS!" (Termux; "if the enter button doesn't work..." i.e., soft-keyboard/Enter issues on a watch) and GitHub yanghoeg/usix-watch-termux ("Install and set up Termux on a Galaxy Watch (Wear OS) from your phone's Termux - wireless adb install, watch-friendly extra keys, SSH"). I could NOT fetch either page body, so no commands verified. Expect: on-watch keyboard poor, so drive via SSH; Termux is not Wear-optimized (no round UI); no Play Store listing, sideload APK; background kill risk (see 4).
- Sources (unfetched; snippets from search): https://xdaforums.com/t/guide-linux-on-wear-os.4515771/ ; https://github.com/yanghoeg/usix-watch-termux
- Confidence: low.

## 4. Battery / Doze / background killing / screen

### 4.1 Background restrictions
- Stock Doze/App Standby applies on Wear OS. Per-app setting on the watch: Settings > Apps > (app) App info > Battery/Usage > Unrestricted (community) ; Pixel Watch path "Permissions > Pause app activity if unused > Off" is a different feature (hibernation), not battery optimization. Samsung adds a phone-side control: Galaxy Wearable app > Watch settings > Apps > (app) > "Allow background activity" (community said this was the correct answer for a Galaxy Watch 4 Classic). adb: `adb shell dumpsys deviceidle whitelist +PACKAGE` (use `-PACKAGE` to remove) - from a Wear OS thread; Google doc for Doze testing: `dumpsys deviceidle force-idle|unforce`, `am set-inactive PKG true|false`, `dumpsys battery reset`.
- INFERENCE: persistence of the deviceidle whitelist across reboot/OTA on One UI Watch not verified; re-apply from a boot hook/fleet script.
- Sources: https://www.reddit.com/r/WearOS/comments/17efnpt/how_to_disable_battery_optimizations/ ; https://developer.android.com/training/monitoring-device-state/doze-standby ; https://www.reddit.com/r/GalaxyWatch/comments/q6z3hl/battery_life_improved_when_disabling_background/ (search snippet: Samsung Health > Battery > Allow background activity)
- Confidence: med.

### 4.2 Always-on display (AOD) / screen timeout
- Wear OS 5 and lower: system shows a blurred screenshot of the paused app with time overlaid ("AOD Lite"). Wear OS 6+: apps targeting SDK 36 are treated as always-on, dimmed but running (updates as slow as once per minute). Return-to-watch-face timeout is user-configurable; apps can hold the screen via Ongoing Activity API (Wear OS 5+) / Live Updates (Wear OS 7+). AOD is not shown in Theater mode.
- adb: `adb shell input keyevent KEYCODE_SLEEP` (enter ambient if AOD enabled) / `KEYCODE_WAKEUP`.
- Samsung developer option "Stay awake when charging" keeps the screen on while on the puck (useful for adb).
- Samsung rates GW6 about 40 h battery AOD off vs 30 h AOD on (grokipedia summary; low).
- Sources: https://developer.android.com/training/wearables/apps/always-on ; https://anexplorer.io/devmode/android/watch ; https://grokipedia.com/page/Samsung_Galaxy_Watch_6
- Confidence: high (Android doc), low (battery numbers).

### 4.3 Rotation/orientation, sleep/lock
- Not found: I located no source on rotation/orientation persistence for the watch (no auto-rotate on round Wear OS display; watch has a wrist/orientation setting - from memory, unverified). Lock/PIN: Samsung may prompt a PIN when enabling developer mode (Reddit, one comment). Not researched further.
- Confidence: n/a.

### 4.4 Post-update lag/battery drain
- Symptom: after One UI 8 (Wear OS 6) on GW6 Classic: ~4 h battery, heavy lag; restart/cache wipe only temporarily helped; full factory reset fixed it (OP update). Another user said One UI 8 improved battery after a week.
- Source: https://www.reddit.com/r/GalaxyWatch/comments/1plvl32/one_ui_8_basically_bricked_my_6_classic/
- Confidence: med-low (anecdotal).

## 5. OTA updates, recovery, root

### 5.1 Blocking updates
- Update agents: `adb shell pm disable-user --user 0 com.sec.android.soagent` and `adb shell pm disable-user --user 0 com.wssyncmldm`; re-enable with `pm enable ...`. A downloaded update that was "ready to install" stayed uninstalled after disabling (watch 4 Classic user). One user reported the raw commands errored but the GeminiMan manager's disable list worked (try `--user 0`, check shell uid).
- Source: https://www.reddit.com/r/GalaxyWatch/comments/1qcmmqt/remove_oneui_80_before_it_installs/
- Confidence: med.

### 5.2 Update delivery quirks
- Updates come via Galaxy Wearable on the phone or watch Settings > Software update (watch alone over Wi-Fi). Fleet gotchas reported: ~1.8 GB package re-downloads repeatedly then fails at install (red "!" screen, boots back to old build); fixes listed: clear Galaxy Wearable cache on phone, wipe cache partition from Recovery (hold Home+Back, tap Home to reach Recovery menu), update standalone over Wi-Fi with phone BT off; one user's download only succeeded after turning the phone VPN off.
- Source: https://www.reddit.com/r/GalaxyWatch/comments/1ub6p39/watch_5_wear_os_6_update_not_updating/ (comments by users; one reads LLM-style; treat steps as unverified)
- Confidence: low-med.

### 5.3 Rollback prevention
- All Wear OS Galaxy Watches (Watch4 or newer) got a rollback-prevention update in March 2026: cannot downgrade; "if you want to downgrade, do not update". (Watch 6 Classic users asking to roll back One UI 8 had no answer other than factory reset.)
- Source: https://github.com/zenfyrdev/bootloader-unlock-wall-of-shame/blob/main/brands/samsung/README.md ; https://www.reddit.com/r/GalaxyWatch/comments/1plvl32/one_ui_8_basically_bricked_my_6_classic/
- Confidence: med (community-curated repo, dated Nov 13 2026).

### 5.4 Root / bootloader
- Same repo: "Unlike other Samsung devices, One UI 8 Watch brought a proper OEM Unlock and bootloader unlock. However, the device does not seem to work correctly (bootloop) after flashing custom binaries. LTE models have the risk of HARD BRICKING; no EDL/EUB mode." A r/androidroot thread "How to root Galaxy Watch 6 (44mm)" exists (title only; page unfetched). Phones: One UI 8 removes OEM-unlock entirely (not a watch fact). For fleet: no root, treat as locked; Shizuku (uid 2000) is the practical elevation.
- Sources: https://github.com/zenfyrdev/bootloader-unlock-wall-of-shame/blob/main/brands/samsung/README.md
- Confidence: low-med (single curated repo; no GW6-specific verification).

## 6. Phone pairing / Samsung apps dependence

- First-time setup requires the Galaxy Wearable app on a compatible Android phone (GW6 not compatible with iOS). After setup an LTE model can live independently; BT/Wi-Fi-only models keep local health tracking but lose calls/SMS/sync away from the phone. Factory reset (the common fix for update problems, 4.4/5.2) means re-pairing with a phone and re-enabling developer options + re-pairing adb from scratch.
- Samsung Health is built in and does the sensor acquisition: you cannot use the health features without it; you may use other apps as the data hub. Some features (BP/ECG-style monitors, Samsung Health Monitor) are Samsung-phone-only; BP is region-limited.
- Phone and watch Wi-Fi credentials: the phone shares saved Wi-Fi passwords with the watch when it changes SSID (see 1.3), which can put a fleet watch on an unexpected network.
- CN-region SKUs (e.g. SM-R8950) block phones that use Google Play Services (older Watch4 example); only relevant if the fleet buys CN-model watches. Low.
- Sources: https://www.reddit.com/r/GalaxyWatch/comments/1ub6p39/watch_5_wear_os_6_update_not_updating/ ; https://www.reddit.com/r/GalaxyWatch/comments/1qptkt4/using_a_galaxy_watch_without_having_to_use_the/ ; https://grokipedia.com/page/Samsung_Galaxy_Watch_6 ; https://github.com/huataihuang/cloud-atlas/blob/1a72fa5fa132a50cd6f872e45cf1fc68b8af23ae/source/android/hack/cn_samsung_galaxy_watch_4_wich_android.rst
- Confidence: med.

## 7. Vendor apps / bloat / sideloading

- Sideload: `adb -s IP:CONNECT_PORT install -r app.apk` (add `-g` to grant runtime permissions; used by rish-mcp). Play Store on watch only lists Wear apps; non-Wear APKs usually install but have phone UIs (Shizuku, Termux) - round-screen issues.
- Debloat: `adb shell pm disable-user --user 0 PKG` (non-destructive; reverse with `pm enable`). Warning from a Fossil/Wear thread: removing packages can drop features like "Time only" low-battery mode; Samsung Wear packages unverified here.
- Source: https://www.reddit.com/r/WearOS/comments/z31ny0/psa_adb_to_wear_os_3_requires_extra_steps/ ; https://github.com/turin-dev/rish-mcp/blob/5ee7134f6076338eb14cd64e3cafec2d3d104626/before/docs/WEAR_OS.md
- Confidence: med.

## 8. Accessibility services
- Not researched successfully: I found no watch-specific source. Generic Android applies (`settings put secure enabled_accessibility_services ...` needs WRITE_SECURE_SETTINGS, grantable via adb/Shizuku; a YouTube result mentioned granting android.permission.WRITE_SECURE_SETTINGS on a Wear OS Galaxy Watch 4, unfetched). Test on a device. Confidence: n/a.

## 9. Version map (for ticket language)
- GW6 launched Wear OS 4 / One UI Watch 5 (Aug 2023); Wear OS 5 / One UI 6 Watch from late 2024; One UI 8 (Wear OS 6, Android 16 = sdk 36) reaching GW6 Classic by Dec 2025; One UI 9 Watch beta for GW6 (a "fifth beta" headline was seen in a search snippet, not opened) and "gone global" threads for GW8 in Nov 2026. Source: https://grokipedia.com/page/Samsung_Galaxy_Watch_6 ; https://www.reddit.com/r/GalaxyWatch/comments/1plvl32/one_ui_8_basically_bricked_my_6_classic/ . Confidence: med.

## Fetch status (pages cited were fetched unless listed here)
Failed to fetch (all engines failed; also retried with stealth proxy where noted): https://devpost.com/software/tailware-vpn-for-wear-os-smartwatches (snippet only), https://xdaforums.com/t/galaxy-watch-7-x-one-ui-8-watch.4737695/page-3 (snippet only), https://xdaforums.com/t/guide-installing-apps-and-granting-permissions-using-shizuku-and-appops.4755067/, https://xdaforums.com/t/guide-linux-on-wear-os.4515771/, https://xdaforums.com/t/galaxy-watch-6-adb-debloat-connecting.4613093/, https://www.reddit.com/r/homeassistant/comments/1h12tv7/pixel_watch_vpn/, https://stackoverflow.com/questions/79673651/adb-fails-to-connect-to-android-watch (empty), https://developer.android.com/training/wearables/get-started/debugging-wifi (404; correct URL is debug-wifi, fetched). https://github.com/yanghoeg/usix-watch-termux returned an empty GitHub error page (repo may be private/renamed). https://www.reddit.com/r/GalaxyWatch/comments/q6z3hl/... and the One UI 9 Watch beta Facebook post were seen only as search snippets. https://android-developers.googleblog.com/2026/09/wireless-debugging-adb-wifi-2.html fetched but returned only page chrome (no article text). Several search results from the shared firecrawl search were irrelevant (engine weak on long queries); firecrawl_developer_search hit HTTP 429 on some queries.

Prior art / docs checked: shared firecrawl search + scrape of Android Developers Wear OS debugging/Wi-Fi/always-on/Doze docs, Samsung Developer connect-watch guide, Tailware README, Hermes wearos plugin page, rish-mcp Wear OS doc, Shizuku fork issue, bootloader-unlock-wall-of-shame (Samsung), and Reddit threads (r/GalaxyWatch, r/WearOS). Context7 not used (no library API question).

Closing search: re-ran searches for Tailscale-on-Wear-OS, GW6 root/Termux, and OTA behaviour at the end; nothing contradicted the above. New item surfaced: Samsung rollback-prevention (March 2026) and the One UI 8 Watch bootloader-unlock note (both from one community repo, so verify before relying on them).

DONE
