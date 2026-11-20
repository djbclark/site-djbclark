STATUS: done

# Kobo Clara Colour: can it be made to behave like Android?

Date 2026-11-20. Prior art / docs checked: firecrawl_search x ~16 queries + firecrawl_scrape of ~25 pages (listed per claim). Evidence tags: [DOC] vendor/project documentation fetched; [HANDS-ON] primary-source teardown/log by a user on a Clara Colour; [FORUM] mobileread/reddit/HN comment (unverified); [MY-INFERENCE]; [NOT-FETCHED] seen only as a search snippet or from memory.

## Verdict (short)
- **Android on a Clara Colour: not feasible today.** No bootloader unlock, no ROM/port, no Linux distro exists; the boot chain is signature-checked. Trying to replace boot partitions is a real brick risk. Nobody has shown it (the only public "own OS on a Clara Colour" work boots from a loop image under Kobo's own kernel, see below).
- **Best practical path: stay on Kobo firmware, add KOReader + NickelMenu + SSH + Tailscale.** That gives a hackable Linux box, not Android. Shizuku/Tasker/Termux/adb are Android-only and cannot run.
- **If you truly need Android APIs/apps/adb/Shizuku/Tasker/Termux: buy a native-Android e-ink device (Boox first).**
- **Timing risk (new): Kobo firmware 6.0.279225 (Nov 2026) is rolling out to Clara Colour/Libra Colour and breaks stock NickelMenu/KFMon.** See OTA section.

## 1. Hardware/boot facts (best evidence on the web) [HANDS-ON]
Source: Elixir Forum thread "The journey to running Nerves on a Kobo Clara e-reader" (fetched): https://elixirforum.com/t/the-journey-to-running-nerves-on-a-kobo-clara-e-reader/73331 . Device: Clara Colour, model N367B, UART + root SSH, fw build dated 2025-01-03.
- SoC: boards report "MediaTek MT8110 board"; rcS detects platform `mt8113t-ntx`; U-Boot 2019.04 "MT8110 P1 EMMC"; DRAM ~506 MiB; 16 GB eMMC (soldered; XCSoar thread says eMMC is soldered, https://github.com/XCSoar/XCSoar/discussions/1433 [FORUM]).
- Kernel Linux 4.9.77 armv7l, an Android-derived MediaTek kernel (CONFIG_ANDROID=y, binder built in) but userland is Yocto/busybox Kobo (Nickel/Qt), **not Android**. Modules load fine (CONFIG_MODULE_SIG off, f2fs.ko insmod worked).
- GPT: bl2, UBOOT, nvram, boot_a (FIT kernel+dtb), tee_a, hwcfg, ntxfw, waveform, vendor, system_a (1 GiB), recovery (1 GiB), userdata (~12.7 GB, FAT = the USB-visible partition).
- **Secure boot: serial log shows "Verifying bootimg_ctl Sign / fit_verify_configed_sign ... result: 0" before U-Boot, and U-Boot built with CONFIG_FIT_SIGNATURE=y.** The author concluded an unsigned/foreign kernel image will not boot and he found no exploit. Fastboot can be entered (run `fastboot getvar all` then plug in and hold power) but exposes only getvar; no unlock command shown.
- HN (Dec 2025, https://news.ycombinator.com/item?id=46194904) [FORUM, one knowledgeable commenter]: MT8113 Kobos have a locked boot chain; BROM download mode reachable (kamakiri/mtkclient) but no public exploit or signed BL2 to boot arbitrary code; Kobo ships GPL kernel source but won't let users boot their own kernel. I could not fetch the cited mtkclient issues (#1332/#1289) [NOT-FETCHED].
- Kobo publishes GPL sources (kernel, U-Boot, wifi driver) at https://github.com/kobolabs/Kobo-Reader (fetched; repo present; per Nerves thread kernel/U-Boot tarballs are there).
- No Android port, custom ROM, or bootloader-unlock guide exists for Clara Colour or Libra Colour: none found in ~16 searches. The only Android-on-Kobo history is Gingerbread on old SD-card models (Touch/Glo/Aura HD): https://www.mobileread.com/forums/showthread.php?t=322865 [FORUM, 2019]; NiLuJe there: "Android on eInk is a... questionable choice (also, pain)". New models have soldered eMMC and no SD slot.
- Brick evidence: an XCSoar user bricked a Clara Colour trying to install foreign software (2024); it recovered after days (power-button + USB, Kobo updated itself) (XCSoar thread above) [FORUM].
- Closest "other OS" result: Nerves/Buildroot boots from a loop image on /userdata via a replaced /sbin/init under Kobo's own kernel (touch-at-boot dual-boot), Wi-Fi working, e-ink still WIP. It is hobby-grade, not Android, and needs UART soldering to develop.
- Android-userland-in-chroot (proot/Termux/Waydroid-like) [MY-INFERENCE, nothing found]: only ~500 MiB RAM, armv7 4.9 kernel, no GPU/e-ink compositor path for Android, Kobo e-ink driven by proprietary Nickel libs. Not worth attempting; Termux-style ARMv7 userspace via KOReader/SSH is the realistic substitute.

## 2. In-place options on Kobo firmware
| Option | Works on Clara Colour? | Evidence |
|---|---|---|
| KOReader (+ NickelMenu/KFMon launcher) | Yes. KOReader wiki: "full Kobo lineup supported". Kobo 4.x: one-click packages. | [DOC] https://github.com/koreader/koreader/wiki/Installation-on-Kobo-devices ; https://www.mobileread.com/forums/showthread.php?t=314220 |
| NickelMenu | 4.x: official. 5.x/6.x: unofficial Qt6 fork-v1.2 (Kobo.tgz), tested on 6.0.279225 + 4.46. | [DOC] https://pgaskin.net/NickelMenu/ ("not currently compatible with 5.x"); https://github.com/nicoverbruggen/NickelMenu/releases/tag/fork-v1.2 |
| kobopatch web UI (NickelMenu, fonts, patches; patches for 4.45.x on Libra/Clara Colour + Clara BW) | Yes | [DOC] https://github.com/nicoverbruggen/kobopatch-webui ; https://www.mobileread.com/forums/showthread.php?t=373075 |
| Plato (alt reader) | Via the one-click package | [DOC] mobileread 314220 |
| Dev mode (search "devmodeon" in Annotations) -> telnet, forced Wi-Fi etc. | Documented generically; not verified on current Clara Colour fw | [DOC] https://uwuu.ca/kobo/guide/nickel-options/ (warns telnet is unauthenticated; do not use on public Wi-Fi) |
| SSH as root | Yes on Clara Colour: .kobo/ssh-disabled file says rename to ssh-enabled and reboot; "ssh root@<ip>" | [HANDS-ON] Nerves thread. Password/key behaviour not stated; test on a trusted LAN only. Behaviour on fw 6.x unverified. |
| adb / adbd | No. No adbd on device; USB is mass-storage only (fastboot not useful). | [MY-INFERENCE] + Nerves thread (USB gadget is mass storage) |
| Tailscale | Likely. kobo-tailscale supports Libra Colour + Clara BW (same MT8113 family; no Clara Colour dir, so unverified). KOReader plugin installs ~57 MB ARMv7 binaries from KOReader menu; "Tested on Kindle PW5/PW6, Kobo, PocketBook". Needs iptables binary + userspace workarounds on old 4.9 kernels. | [DOC] https://github.com/videah/kobo-tailscale ; https://github.com/jadehawk/koreader-tailscale ; https://dstaley.com/posts/tailscale-on-kobo-sage/ |
| Shizuku / Termux / Tasker | **No** (Android only) | [MY-INFERENCE]; Shizuku docs assume Android 11+ wireless debugging https://shizuku.rikka.app/guide/setup/ |
| Tasker-like automation | Partial substitutes: NickelMenu actions/menu entries, KOReader plugins (Wallabako, Syncthing, Calibre sync, OPDS), cron-like loops via SSH scripts | [DOC]/[MY-INFERENCE] |

## 3. Risk, warranty, OTA
- **Bricking:** USB-file installs (KOReader, NickelMenu, kobopatch) are low risk; NickelMenu has an auto-uninstall failsafe [DOC]; uwuu.ca grades eReader.conf edits "minimal brick risk, fixable with factory reset" [DOC]. Flashing/replacing partitions or modding boot chain: high, no known restore path (eMMC soldered; UART needs opening the case) [HANDS-ON/FORUM].
- **Warranty:** Kobo's actual warranty text NOT fetched. A reddit user says installing KOReader/NickelMenu doesn't void it (3 years old, anecdote) https://www.reddit.com/r/kobo/comments/1cs89x4/new_to_kobo_possible_dumb_question/ [FORUM]. Opening the case/soldering UART or flashing partitions would very likely void it [MY-INFERENCE].
- **OTA behaviour (documented):**
  - KFMon is disabled by any firmware update and must be reinstalled (NiLuJe, mobileread 314220) [DOC]. NickelMenu "persists between firmware upgrades" on 4.x [DOC].
  - **Firmware 6.0.279225 (Nov 2026; mobileread https://www.mobileread.com/forums/showthread.php?p=4620834)** targets the MediaTek models (Clara BW/Colour, Libra Colour, Elipsa 2E) and moves to Qt6; r/koreader reports (https://www.reddit.com/r/koreader/comments/1xw4zp0/update_6_on_kobo_help/ and /1xxr5ej/) say NickelMenu vanished after the update and a Kobo restart auto-updated one user to 6.x [FORUM]. Fix reported: install fork-v1.2 `Kobo.tgz` (NOT KoboRoot.tgz) into `.kobo/`; KOReader "kobov5" builds (v2026.07.x, https://github.com/koreader/koreader/releases/tag/v2026.07.1 adds tolino>=5.18 support; "mostly work on 6.x") [FORUM]. Known 6.x quirks: exit-to-Nickel unreliable (use reboot), LED stuck on / battery shows 0% [FORUM]; some NickelMenu features disabled in Qt6 build [DOC].
  - Downgrade: forum says 5->4 easy, 6->4/5 risky; a mobileread comment says turning off accessibility options still allows downgrade to 4.45.x [FORUM, unverified]. Do not downgrade without reading the current threads.
- New devices already ship 5.x in Europe (mobileread t=374547, [FORUM]).

## 4. Ranked recommendation
1. **Keep Kobo firmware; add KOReader + NickelMenu + SSH (+ Tailscale).** Lowest risk, documented, reversible. Gives root shell, file sync, remote reachability; no Android APIs.
2. **If Android tooling is a hard requirement: buy a native-Android e-ink device (fallback).** Boox (Go Color 7 / Palma / Note Air6 C family; shop https://shop.boox.com/collections/all lists Palma 3 $339.99, Note Air6 C $579.99, Go 6 Gen II B/W) ships Android with Play Store; Bigme HiBreak (Android 14 per secondary source), Meebook/Hisense are alternatives. I could not fetch Boox spec pages (product URLs 404) [NOT-FETCHED], so: adb/Shizuku/Termux/Tailscale-app/Tasker compatibility is expected from standard Android (Shizuku doc [DOC]) but check the exact model + Android version before buying; Hisense (reported without Google Play, 5ch snippet) and Chinese-market Boox firmware need care. A reddit snippet also says Android may restrict on-device ADB (Shizuku) [NOT-FETCHED].
3. **Hobby only: Nerves/Buildroot-from-loop-image like the Elixir Forum author.** Needs UART, kernel-module work, no Android.
4. **Do not attempt:** bootloader/partition replacement or Android port (secure boot, no unlock, brick risk).

## 5. Exact steps for option 1
Prereq: Settings > Device information: note firmware (4.x vs 5.x/6.x). Copy the whole device (.kobo, .adds) to the Mac first. Use a good USB cable.
**A. Firmware 4.x (e.g. 4.45.x/4.46):**
1. Open https://www.mobileread.com/forums/showthread.php?t=314220 ; from post #1 download the KOReader one-click ZIP (bundles KFMon + NickelMenu); from post #2 get the install script (it also handles the FW>=4.17 hidden-folder scan quirk).
2. Plug in Kobo, accept USB connect, extract the ZIP to the device root (not a subfolder), run the script, eject safely. Device shows "processing" and reboots to install.
3. Launch KOReader from home/NickelMenu. Alternative GUI: https://github.com/nicoverbruggen/kobopatch-webui (install NickelMenu + KOReader from Chrome/Edge).
**B. Firmware 5.x/6.x (Clara Colour on 6.0.279225):**
1. Download `Kobo.tgz` from https://github.com/nicoverbruggen/NickelMenu/releases/tag/fork-v1.2 ; put it into hidden `.kobo/` (do not rename), eject; device installs and reboots. Remove with empty file `.adds/nm/uninstall` + reboot.
2. Install a KOReader "kobov5" build (https://github.com/koreader/koreader/releases , v2026.07.x or newer) into `.adds/koreader`; add a NickelMenu entry to launch it. Prefer reboot over "exit to Nickel".
**C. SSH:** in `.kobo/` rename `ssh-disabled` to `ssh-enabled`, reboot, `ssh root@<device-ip>` (DHCP lease or KOReader network info). Keep the reader off public Wi-Fi.
**D. Tailscale:** KOReader menu > Settings > Network > Tailscale VPN > Setup > Install/Update (plugin from https://github.com/jadehawk/koreader-tailscale into `.adds/koreader/plugins/`; put an auth key in `bin/auth.key`), or run `install-tailscale.sh` from the `libra-color` or `clara-bw` dir of https://github.com/videah/kobo-tailscale over SSH (Clara Colour untested).
**E. Update hygiene:** keep a copy of the matching KoboRoot.tgz/Kobo.tgz and KOReader zip; after any firmware update reinstall KFMon/NickelMenu; consider not updating until NickelMenu/KOReader confirm support for your firmware.

## Uncertainties
- Whether SSH/devmode and kobo-tailscale behave identically on firmware 6.0 for Clara Colour: unverified.
- Kobo warranty wording and Boox/Hisense/Meebook specs: not fetched.
- "No unlock exists" is absence of evidence plus the Nerves serial log; it is strong for current public knowledge but not proof of impossibility (HN says BROM download mode is reachable).

Closing search: re-ran searches for Android port/unlock/custom ROM for Kobo Clara/Libra Colour (Kobo-specific queries above) and NickelMenu on fw 6; found nothing new beyond cited items. Boox/Hisense/Meebook spec pages not verified.
DONE
