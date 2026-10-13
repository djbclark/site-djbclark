# Apple Intelligence daemons on macOS 27 with SIP on: web research

Date: 2026-10-13. Scope: web only, no commands run on the machine.
Daemons: `com.apple.generativeexperiencesd`, `com.apple.intelligencecontextd`, `com.apple.intelligenceflowd` (gui-domain LaunchAgents), and `com.apple.modelmanagerd`, `com.apple.modelcatalogd` (system LaunchDaemons).

## 0. Headline findings

1. **On macOS 27 Apple Intelligence cannot be switched off, so "presumably not enabled" is almost certainly wrong.** Apple removed the master toggle in 27, and the models download automatically. The daemons serve a feature set that is on by default (sources in 2.1).
2. **With SIP on, `launchctl disable` on these Apple jobs does not do what it looks like.** launchd discards the override at every boot (logged as "Ignoring enabled state due to rootless restrictions"), and some jobs relaunch while their override is still in place. `bootout` fails with error 150. This has been the case since 10.12.4 and is reproduced on 26.5 and 27 (sources in 2.3).
3. **No supported key, profile or Settings toggle keeps these five daemons from being activated.** The strongest SIP-on tool (RemoveMacAI, configuration profile plus model removal) says plainly that the system services "stay loaded" and "start again whenever an app asks for them" (sources in 2.2 and 3).
4. So the 60-second TERM/KILL watchdog cannot win. It can only add respawn churn, and one report ties disabling modelmanagerd to sustained coreaudiod/launchd CPU (3.2). Cutting *demand* (features off, models removed) and then measuring whether the daemons cost anything when left alone is the better path (section 4).

## 1. What the daemons do, and what starts them

### 1.1 Apple's own descriptions (shipped man pages)

1. intelligenceflowd: "`intelligenceflowd` manages sessions, communication, and state between clients and backend intelligence services." https://manp.gs/mac/8/intelligenceflowd
2. intelligencecontextd: "`intelligencecontextd` retrieves contexual information from various sources to provide useful information about the user and their device state." https://manp.gs/mac/8/intelligencecontextd
3. generativeexperiencesd: "`generativeexperiencesd` powers generative experience such as summarization and text composition on this device." https://manp.gs/mac/8/generativeexperiencesd
4. modelmanagerd: "`modelmanagerd` is a daemon that manages ML models and requests for execution of those models. There are no options for `modelmanagerd`, and users should not run `modelmanagerd` manually." https://manp.gs/mac/8/modelmanagerd
5. modelcatalogd: "`modelcatalogd` provides a catalog of models, adapters, and tokenizers for use by the system" (NAME line: "A daemon that stores base models and adapters."). https://manp.gs/mac/8/modelcatalogd. A sibling `ModelCatalogAgent(8)` also exists: "ModelCatalogAgent(8) | A daemon that stores base models and adapters" https://manp.gs/mac/8/
6. Plist locations, per b0gdanw's Tahoe list: "/System/Library/LaunchAgents/com.apple.intelligenceflowd.plist", "/System/Library/LaunchAgents/com.apple.intelligencecontextd.plist", "/System/Library/LaunchAgents/com.apple.generativeexperiencesd.plist", "/System/Library/LaunchDaemons/com.apple.modelmanagerd.plist", "/System/Library/LaunchDaemons/com.apple.modelcatalogd.plist". https://gist.github.com/b0gdanw/0c20c2fd5d0a7e6cff01849b57108967

### 1.2 How they fit together, and their launch triggers

1. CoreGuard read the Tahoe 26.5.2 launch manifests. intelligenceflowd: "its Tahoe services include orchestration, tools, snippets, and transcript-entity queries". intelligencecontextd: "It brokers context for intelligence sessions, including UI context according to its Tahoe manifest". generativeexperiencesd: "Tahoe exposes services for summarization, classification, composition, availability, and generative sessions". https://coreguard.app/insights/apple-intelligence-daemons-mac/
2. Same source, on the pipeline: "A client requests an intelligence operation; the flow daemon coordinates it, the context daemon supplies relevant state, generative services handle supported composition or summary work". https://coreguard.app/insights/apple-intelligence-daemons-mac/
3. Same source, on post-install work: "`generativeexperiencesd` has post-install availability tasks." https://coreguard.app/insights/apple-intelligence-daemons-mac/
4. Inference, but well supported: the "services" CoreGuard lists are XPC MachServices. launchd starts a job on demand when a client looks up one of its MachServices, which matches the observed respawn after kill. The launchctl man page says: "sending a message to one of those endpoints will cause the service to launch on demand." https://manpagez.com/man/1/launchctl/osx-10.10.php
5. **Unverified:** the exact MachService names and the RunAtLoad / KeepAlive / LaunchEvents / Notification keys in these five plists on 27.0.1. I found no published dump of these plists. Reading them locally is read-only and safe: `plutil -p /System/Library/LaunchAgents/com.apple.intelligenceflowd.plist` (and the same for the other four), plus `launchctl print gui/$UID/com.apple.intelligenceflowd` and `launchctl print system/com.apple.modelmanagerd`. The `print` output shows "runs", the last exit reason and the endpoints, which settles which ones are demand-launched and which are KeepAlive.
6. **Unverified:** why modelcatalogd ignores SIGTERM. A likely explanation is that it handles TERM itself, or holds a transaction or lock on model assets. One indirect hint: RemoveMacAI issue #15 quotes an asset error "Could not eliminate as there are current locks" (https://github.com/omlahore/RemoveMacAI/issues/15). No source states this outright.

### 1.3 Do they start when Apple Intelligence is off?

1. Yes, in user reports going back to macOS 15. Reddit r/MacOS: "generativeexperiencesd and intelligenceplatformd are running too. i haven't clicked "agree" on their TOS". This is a search snippet only. Reddit blocked every fetch I tried (WebFetch, parallel, exa, firecrawl, crawl4ai, old.reddit), so the comments are unread. https://www.reddit.com/r/MacOS/comments/1le9suy/why_are_siri_processes_running_even_though_its/
2. CoreGuard says the toggle never promised to stop them: "That setting still does not promise the disappearance of every process with "intelligence" in its name." https://coreguard.app/insights/apple-intelligence-daemons-mac/
3. Bytetally on modelmanagerd: "Its presence does not by itself mean that a large model is being downloaded, that Apple Intelligence is actively processing a request" and "Apple provides no switch for disabling modelmanagerd itself." https://bytetally.app/en/process/modelmanagerd
4. On macOS 27 the question goes away, because the feature can no longer be turned off (2.1).

## 2. Is there a supported way to stop activation with SIP on?

### 2.1 Settings toggle: gone in macOS 27

1. Apple: "The next generation of Apple Intelligence is automatically available on eligible devices when you update to the 27.0 software releases". https://support.apple.com/en-us/121115
2. Apple's macOS 27 page lists only per-feature switches (Siri, Messages/Mail/notification summaries, Smart Replies, and so on), each by name, and no master switch: "You can turn off Apple Intelligence features like Siri AI (Beta),* summarization features, and more." https://support.apple.com/guide/mac-help/turn-restrict-access-apple-intelligence-mchlb2e44f94/mac
3. Daring Fireball: "Unlike with previous versions of macOS, macOS 27 Golden Gate doesn't have a toggle for turning off Apple Intelligence." https://daringfireball.net/linked/2026/10/06/cli-tool-removes-apple-intelligence-from-macos-27
4. MacDailyNews: "macOS 27 and iOS 27 removed the toggle that used to disable Apple Intelligence and delete the downloaded files." https://macdailynews.com/2026/09/25/apple-intelligence-is-eating-up-to-30gb-on-some-macs-after-macos-27/
5. iThinkDiff: "On macOS 27, testers say the toggle to turn Apple Intelligence off is gone, so the models download automatically." https://www.ithinkdiff.com/apple-intelligence-is-taking-20gb-to-30gb-on-some-macs-running-macos-27-golden-gate/

### 2.2 Configuration profile and MDM restriction keys

1. Legacy `com.apple.applicationaccess` keys exist for macOS (allowWritingTools, allowGenmoji, allowImagePlayground, allowMailSummary, allowMailSmartReplies, allowExternalIntelligenceIntegrations, allowAppleIntelligenceReport, and others). All are marked deprecated in 26.4, for example: "If `false`, disables Apple Intelligence writing tools. Deprecated: use the declarative management `com.apple.configuration.intelligence.settings` configuration." https://github.com/apple/device-management/blob/release/mdm/profiles/com.apple.applicationaccess.yaml
2. Their replacement, the DDM `com.apple.configuration.intelligence.settings` (AllowWritingTools, AllowGenmoji, AllowImagePlayground, AllowVisualIntelligence on 27, plus per-app Mail/Notes/Safari/Calendar keys), is **supervised only**: "macOS: introduced: '26.4' allowed-enrollments: - supervised". It is not available to an unmanaged personal Mac. https://raw.githubusercontent.com/apple/device-management/release/declarative/declarations/configurations/intelligence.settings.yaml
3. DDM `com.apple.configuration.siri.settings` adds `AllowSiriAI` on macOS 27: "If `false`, disables the Siri AI specific features of Siri." It is also supervised only. https://raw.githubusercontent.com/apple/device-management/release/declarative/declarations/configurations/siri.settings.yaml
4. **No key in either schema disables Apple Intelligence as a whole or controls the daemons.** I looked for `allowGenerativeModels` and found no such key; the closest is `allowSiriAI`. The keys are per feature.
5. Jamf (boberito) on macOS 15: "even if you implement all the Apple supplied restrictions, there's still features of Apple Intelligence that are not manageable." There is also an opt-in plist trick (`~/Library/Preferences/com.apple.CloudSubscriptionFeatures.optIn.plist`), which only works with no Apple Account signed in: "If a user is NOT logged into an Apple Account, this profile will disable the ability to enable Apple Intelligence completely". A 2026 reply says the AccountDSID lookup changed on 26. **Unverified whether this opt-in key does anything on 27**, where there is no opt-in. https://community.jamf.com/tech-thoughts-180/raising-your-iq-on-apple-intelligence-55524
6. RemoveMacAI (SIP on, macOS 27) uses a user-approved, manually installed profile containing the legacy restriction keys (`allowAssistant`, `allowExternalIntelligenceIntegrations`, `allowExternalIntelligenceIntegrationsSignIn`, `allowWritingTools`, `allowGenmoji`, `allowImagePlayground`, `allowMailSummary`, `allowMailSmartReplies`, `allowSafariSummary`, `allowNotesTranscriptionSummary`). It also forces preferences (`com.apple.assistant.support` "Assistant Enabled", `com.apple.Siri` VoiceTriggerUserEnabled/StatusMenuVisible, `group.com.apple.usernoted` summarize_previews, `.GlobalPreferences` NSAutomaticInlinePredictionEnabled, and others). It removes the models through the asset service and blocks re-download with `com.apple.MobileAsset` `DownloadServerBaseURLOverride-<assetType>` = `https://127.0.0.1:9/removemacai-blocked/`. Sources: https://raw.githubusercontent.com/omlahore/RemoveMacAI/main/Sources/removemacai/Profile.swift and https://raw.githubusercontent.com/omlahore/RemoveMacAI/main/Sources/removemacai/Catalog.swift. README: "System Integrity Protection stays enabled and no files under `/System` are modified directly." https://github.com/omlahore/RemoveMacAI
7. **Even so, it does not stop the daemons.** RemoveMacAI's README, under "What it doesn't do": "Mass-disable Apple's background services." / "With System Integrity Protection on, macOS refuses to unload most of them, and many start again" / "whenever an app asks for them." Its FAQ adds: "Some system services also stay loaded; they are protected by System Integrity Protection." https://raw.githubusercontent.com/omlahore/RemoveMacAI/main/README.md
8. Caveat reported by MacRumors: "some of the configuration-profile restriction keys that the tool relies on were deprecated by Apple in macOS 26.4. While they still work in macOS 27.0.1, a future version could always change that." https://www.macrumors.com/2026/10/05/apple-intelligence-removal-tool-frees-mac-storage/

### 2.3 `launchctl disable` plus reboot, and `bootout`/`remove`, under SIP

1. The man page on what `disable` means: "Once a service is disabled, it cannot be loaded in the specified domain until it is once again enabled. This state persists across boots of the device." It blocks *loading*. It does not unload a job that is already loaded. https://leancrew.com/all-this/man/man1/launchctl.html
2. The radar from 10.12.4 onward: "Starting with 10.12.4 SIP in MacOS prevents unloading of any LaunchD item from `/System`" and "the `launchctl disable` command does not seem to work for these and does not give any error message." Observed results: "Neither shuts down the service." https://openradar.me/32281471
3. mac-os-debloat (SIP-on tool, VM-tested through real reboots on 26.5): "**With SIP on, macOS drops these overrides at every boot, and relaunches some jobs while their override is still in place.**" It continues: "After a `telemetry` apply, 44 of 44 overrides were in effect; after each of two reboots, 0 of 44. launchd logs the reason at boot, once per label: `[user/501/com.apple.tipsd:] (lint): Ignoring enabled state due to rootless restrictions`". https://github.com/OleksandrKrupko/mac-os-debloat
4. Same source, on relaunch without a reboot: "With no reboot at all, 10 to 16 of the 44 were running again 90 seconds after the apply (three runs), every override still in effect". The only overrides that survive a boot belong to labels listed under `RemovableServices` in `/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist`. https://github.com/OleksandrKrupko/mac-os-debloat
5. Same source, on bootout: "`Boot-out failed: 150: Operation not permitted while System Integrity Protection is engaged` … `bootout` only kills the running process … `launchctl disable` stops the _next_ launch, it does not stop a live one." https://github.com/OleksandrKrupko/mac-os-debloat
6. On macOS 27 specifically, issue #8, eur0pa (2026-09-21): "Nothing really survives a reboot on macos27 btw". Issue #20 is titled "Overrides do not survive reboot on macOS 27". nordscope-fi: "Both files are rewritten shortly after boot, not left alone." https://github.com/OleksandrKrupko/mac-os-debloat/issues/8 , https://github.com/OleksandrKrupko/mac-os-debloat/issues/20
7. Their workaround (v0.13.0, PR #26) installs a boot/login LaunchDaemon that re-applies the overrides after boot. "Each running label is killed once; one that respawns after its kill is left alone." That is tested on 26.5 VMs only, not 27. https://github.com/OleksandrKrupko/mac-os-debloat/pull/26
8. b0gdanw, who maintains the main disable scripts, now has a Golden Gate (27) script. It lists all five of these labels, plus `com.apple.ModelCatalogAgent`, and says "Disabling SIP is required". On Sequoia he wrote: "SIP must remain disabled. If you turn SIP back on, the changes are deleted by macOS." https://gist.github.com/b0gdanw/47fe6a8c1dfec0a9b11edded58565dd5 , https://gist.github.com/b0gdanw/b349f5f72097955cf18d6e7d8035c665
9. Tahoe gist comment, hudarsono (2026-07-06): "This script doesnt work for me, those services remain running." and "It seems disabling SIP no longer enough on mac os tahoe." https://gist.github.com/b0gdanw/0c20c2fd5d0a7e6cff01849b57108967
10. Ask Different (macOS 13.1): "as soon as I reenable SIP the modification is ignored and I'm back to running with stock automountd." https://apple.stackexchange.com/questions/445028/removing-launchdaemons-in-system-library-launchdaemons

### 2.4 High CPU and respawn loops on 26/27

1. No report names intelligenceflowd, intelligencecontextd, generativeexperiencesd, modelmanagerd or modelcatalogd as a sustained CPU hog. Reports from that family concentrate on `intelligenceplatformd` and `knowledgeconstructiond` (the knowledge-graph pair). CoreGuard says knowledgeconstructiond's manifest "labels its full pipeline resource-intensive and schedules it for external power". https://coreguard.app/insights/apple-intelligence-daemons-mac/
2. After a macOS 27 update, model downloads are large: "Apple says Apple Intelligence needs up to 14 GB on M3-or-later Macs with 12 GB of memory … users report 20 to 30 GB in practice." https://deepclean.app/blog/apple-intelligence-storage-mac . Background download and verification work by model* daemons is therefore plausible right after updates, but **unverified** for these specific processes.
3. An analogous loop on Tahoe: ecosystemd retried an XPC lookup forever ("It retries immediately, forever."), and only a reboot cleared it. https://koodihommia.blogspot.com/2026/03/bird-is-causing-high-cpu-on-my-macos.html . It is not one of these five daemons, but it shows how a missing XPC peer can pin CPU in its clients.

## 3. What others tried, and what worked or broke

### 3.1 Disable and kill approaches

1. Generic watchdog loops are common and are the accepted SIP-on workaround. Ask Different: "while true do sudo killall photoanalysisd ; sleep 60 ; done", with the note "Permanent fixes all involve turning off System Integrity Protection". https://apple.stackexchange.com/questions/338001/how-to-prevent-the-photos-app-from-launching-cloudphotosd-photoanalysisd-etc . maKiller does the same for mediaanalysisd in real time, because "disabling that daemon requires disabling SIP". https://github.com/egorFiNE/maKiller
2. A bulk disable (SIP off) of the intelligence family, per CoreGuard: "If the Mac behaves differently afterward, you have learned almost nothing about which change mattered." https://coreguard.app/insights/apple-intelligence-daemons-mac/

### 3.2 Breakage reports

1. **modelmanagerd:** teqtic (2025-02-28, Sequoia gist): "Disabling 'com.apple.modelmanagerd' makes 'coreaudiod' and 'launchd' use a lot of CPU non stop." Later: "as soon as I disabled modelmanagerd coreaudiod CPU usage shot up". b0gdanw replied: "coreaudiod settles down after a minute or so." teqtic later wondered whether removing modelcatalogd from the script made the problem go away. That is one user; b0gdanw could not reproduce it. https://gist.github.com/b0gdanw/b349f5f72097955cf18d6e7d8035c665
2. **Deleting model or graph data triggers rebuilds:** "removing its store gives that builder an empty assignment sheet. More CPU and disk activity are the predictable result" (CoreGuard, on Graph.db). https://coreguard.app/insights/apple-intelligence-daemons-mac/ . RemoveMacAI issue #32: "System Data grows to 61–74 GB after removing Apple Intelligence models" (title only, not read in full). https://github.com/omlahore/RemoveMacAI/issues/32
3. **Siri.agent:** "`com.apple.Siri.agent` provides Mach services the sign-in dialog consults even with Siri off". Disabling it broke iCloud sign-in (AKAnisetteError -8025). Not one of our five, but it is the same kind of hidden XPC dependency. https://github.com/OleksandrKrupko/mac-os-debloat

### 3.3 SIGSTOP / freezing

1. MacRumors forum: SIGSTOP on mediaanalysisd via Activity Monitor or `kill -17` as a "SUSPEND" alternative to killing. https://forums.macrumors.com/threads/com-apple-mediaanalysisd-taking-space.2446697/page-2
2. Same thread, bogdanw's caution: "A word of caution about using SIGSTOP, it might cause the freeze of the app that started or wants to start the process that was suspended with SIGSTOP." His example: SIGSTOP on com.apple.geod made Safari stop responding on relaunch. The same poster says mediaanalysisd was "auto re-enabled by system" after 6 to 7 days. https://forums.macrumors.com/threads/com-apple-mediaanalysisd-taking-space.2446697/page-2
3. Inference, unverified: a stopped process keeps its MachService port registered, so launchd will not respawn it. Clients then block on XPC replies until they time out. For intelligenceflowd and generativeexperiencesd, the clients include text fields with Writing Tools hooks, Mail, Spotlight/Siri (which on 27 "runs as a process named Siri"), so hangs could appear anywhere. I found no report of SIGSTOP applied to these five daemons specifically.

### 3.4 Reports I could not read in full

1. Reddit r/MacOS "Turning off Apple Intelligence from terminal": the snippet shows `defaults write com.apple.CloudSubscriptionFeatures.optIn "device" -bool false` "on 15.3.1" and "MacOS 27 does not …" (truncated). All fetchers were blocked.
2. Reddit r/MacOSBeta "Apple Intelligence cannot be disabled": snippet only.
3. peterspath.net "What are modelcatalogd and modelmanagerd?": the site serves a bot wall ("Vale") to WebFetch, jina, exa and crawl4ai; an archive.org fetch was also refused. Snippet only.

## 4. What to try, ranked safest first

1. **Measure before fighting (read-only).** Stop the watchdog for a test window and check whether the five daemons use any CPU or memory when left alone after the post-update model work has settled. Use `ps -Ao pid,%cpu,rss,etime,comm`, Activity Monitor's Energy tab with 12 hr Power, and `launchctl print` "runs" counts. Idle demand-launched daemons cost little; killing them every 60 s guarantees a respawn plus client re-init every minute (3.2.1, 2.3.4). This is the step most likely to show that the watchdog is the larger cost.
2. **Read the five plists and launchd's view of them (read-only).** Run `plutil -p` on each plist, `launchctl print gui/$UID/<label>` / `system/<label>` (endpoints, KeepAlive, last exit reason), `launchctl print-disabled system` and `print-disabled gui/$UID`. Also read `/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist` to see whether any of the five appear under RemovableServices. Only those can keep a disable with SIP on (2.3.4). Then check `log show --last boot --predicate 'process == "launchd"' | rg 'rootless restrictions'` to confirm the overrides are dropped at boot on this machine.
3. **Turn off every per-feature Apple Intelligence and Siri switch Apple documents** (Siri off, summaries off, Smart Replies off, Screen Time > Content & Privacy > Intelligence & Siri restrictions). This is supported and reversible, and it reduces client demand. It will not unload the daemons (2.1.2).
4. **Install a user-approved restrictions profile** with the legacy `com.apple.applicationaccess` keys and, optionally, the `com.apple.MobileAsset` `DownloadServerBaseURLOverride-<assetType>` download block, as RemoveMacAI does. You can use RemoveMacAI itself after reading its source, or hand-build the profile. It needs no SIP change and removing the profile reverts it, but the keys are deprecated as of 26.4 (2.2.6–2.2.8). Expect fewer callers, not zero, and expect the daemons to stay loaded (2.2.7).
5. **If a watchdog stays, make it gentler.** Re-apply `launchctl disable` once after each boot, because the overrides are dropped at boot (2.3.3). Kill each label once, then leave alone any that respawn, which is mac-os-debloat v0.13's policy (2.3.7). Don't loop TERM/KILL every 60 s on demand-launched services, and don't target modelmanagerd given the coreaudiod/launchd CPU report (3.2.1).
6. **SIGSTOP instead of kill: not recommended.** It avoids respawn but risks hanging any client that calls the frozen service: text input, Mail, Spotlight/Siri on 27 (3.3). Use it only as a short experiment on one label, with a way to `kill -CONT` it.
7. **Least safe: SIP off (`csrutil disable`) with b0gdanw's Golden Gate script.** It is the only documented way to make these disables persist (2.3.8). It weakens platform security, and one 2026 report says it was not enough on Tahoe (2.3.9). Not recommended.
8. **Not recommended: deleting models or AssetsV2 from Recovery.** Rebuild and re-download churn is reported (3.2.2), and RemoveMacAI does the same thing through the supported asset service with SIP on.

## Sources (all fetched or seen in search results during this session)

1. https://manp.gs/mac/8/intelligenceflowd , /intelligencecontextd , /generativeexperiencesd , /modelmanagerd , /modelcatalogd , https://manp.gs/mac/8/
2. https://coreguard.app/insights/apple-intelligence-daemons-mac/
3. https://bytetally.app/en/process/modelmanagerd
4. https://support.apple.com/en-us/121115
5. https://support.apple.com/guide/mac-help/turn-restrict-access-apple-intelligence-mchlb2e44f94/mac
6. https://github.com/apple/device-management/blob/release/mdm/profiles/com.apple.applicationaccess.yaml
7. https://raw.githubusercontent.com/apple/device-management/release/declarative/declarations/configurations/intelligence.settings.yaml
8. https://raw.githubusercontent.com/apple/device-management/release/declarative/declarations/configurations/siri.settings.yaml
9. https://community.jamf.com/tech-thoughts-180/raising-your-iq-on-apple-intelligence-55524
10. https://github.com/omlahore/RemoveMacAI (README, Profile.swift, Catalog.swift, issues #14/#15/#32)
11. https://www.macrumors.com/2026/10/05/apple-intelligence-removal-tool-frees-mac-storage/
12. https://daringfireball.net/linked/2026/10/06/cli-tool-removes-apple-intelligence-from-macos-27
13. https://macdailynews.com/2026/09/25/apple-intelligence-is-eating-up-to-30gb-on-some-macs-after-macos-27/
14. https://www.ithinkdiff.com/apple-intelligence-is-taking-20gb-to-30gb-on-some-macs-running-macos-27-golden-gate/
15. https://deepclean.app/blog/apple-intelligence-storage-mac
16. https://github.com/OleksandrKrupko/mac-os-debloat (README, issues #8 and #20, PR #26)
17. https://openradar.me/32281471
18. https://leancrew.com/all-this/man/man1/launchctl.html , https://manpagez.com/man/1/launchctl/osx-10.10.php
19. https://gist.github.com/b0gdanw/47fe6a8c1dfec0a9b11edded58565dd5 (Golden Gate), https://gist.github.com/b0gdanw/0c20c2fd5d0a7e6cff01849b57108967 (Tahoe), https://gist.github.com/b0gdanw/b349f5f72097955cf18d6e7d8035c665 (Sequoia, with comments)
20. https://apple.stackexchange.com/questions/445028/removing-launchdaemons-in-system-library-launchdaemons , https://apple.stackexchange.com/questions/338001/how-to-prevent-the-photos-app-from-launching-cloudphotosd-photoanalysisd-etc
21. https://forums.macrumors.com/threads/com-apple-mediaanalysisd-taking-space.2446697/page-2
22. https://github.com/egorFiNE/maKiller
23. https://koodihommia.blogspot.com/2026/03/bird-is-causing-high-cpu-on-my-macos.html
24. Snippet only (fetch blocked): https://www.reddit.com/r/MacOS/comments/1le9suy/ , https://www.reddit.com/r/MacOS/comments/1id8tns/ , https://www.reddit.com/r/MacOSBeta/comments/1u11wet/ , https://peterspath.net/blog/mac-what-is-modelmanagerd/
