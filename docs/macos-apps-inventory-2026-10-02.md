# macOS apps inventory — 2026-10-02

Catalog of every app installed on djbclark's Mac, as of 2026-10-02. Source: `ls /Applications` (re-verified live, not copied from any prior list), plus `mdls`/`defaults read .../Info CFBundleIdentifier` for bundle IDs on anything not immediately obvious, plus one item (Witch) that lives outside `/Applications` entirely. 119 apps total, including four apps nested inside non-`.app` folders (ACS Fido Tools, Adobe Acrobat DC, BiglyBT, Blackmagic RAW) and one legacy System Preferences pane (Witch). Uninstaller helpers, `Icon` resource files, license folders, and one stray `.textClipping` file were excluded as not apps. One empty, non-functional leftover folder (`digiKam.org`, zero contents) was also excluded.

## Hashtag vocabulary (used consistently throughout)

`#menubar #switcher #clipboard #security #vpn #network #backup #dev #browser #communication #email #social #media #photo #video #audio #productivity #utility #system-monitor #remote-access #finance #ai #automation #input #customization #storage #sync #window-management #hardware #gaming #design #terminal #firewall #calendar #reading #notes #LoginItems #uncertain`

`#LoginItems` is applied only to apps that appear in the Background Task Management (`sfltool dumpbtm`) registration dump provided for this inventory — meaning the app registers as a login item / background item with macOS, regardless of whether that registration is currently toggled on or off. Apps not in that dump do not get the tag, even if they plausibly could run in the background.

## Menubar/organizer overlap callout

Several installed apps compete for the same menu-bar-organizing jobs. Flagged here by function only — no deep investigation, that's a separate task:

1. **Hiding/decluttering menu bar icons:** Hidden Bar, ExtraBar — both exist purely to collapse/hide overflow menu bar icons.
2. **App/window switching:** AltTab, Contexts, Witch (`witchdaemon`), and to a lesser extent Spaceman (space-switching rather than app/window) — four tools doing overlapping Cmd-Tab-replacement or window-cycling jobs.
3. **Clipboard management:** CopyClip, Octoclip, PopClip — three clipboard-history/clipboard-action tools installed simultaneously.
4. **System stats in the menu bar:** iStat Menus, Stats — both full system-monitor menu bar suites (CPU/RAM/disk/network/battery). CodexBar and DockPops sit adjacent (status widgets, not system stats) and Only Switch is a quick-toggle switcher rather than a stats display, but all five crowd the same menu bar real estate.
5. **Power-user menu bar/customization umbrella:** BetterTouchTool can itself replace pieces of clusters 1–3 (it does clipboard, window snapping, and menu bar customization) — worth knowing it overlaps with several single-purpose tools above.

---

## Menu bar, switching & window management

- **AltTab** — Windows-style Cmd-Tab window switcher with previews. `#switcher #window-management #menubar #LoginItems`
- **Contexts** — app/window switcher and dock replacement, alternative to Cmd-Tab. `#switcher #window-management #menubar #LoginItems`
- **Spaceman** — menu bar indicator and switcher for macOS Spaces. `#switcher #menubar #window-management #LoginItems`
- **Hidden Bar** — hides/collapses overflow menu bar icons. `#menubar #utility #LoginItems`
- **ExtraBar** — hides/organizes menu bar icons, alternative to Hidden Bar. `#menubar #utility #LoginItems`
- **AeroSpace** — tiling window manager (i3-style) for macOS. `#window-management #productivity #utility`
- **Forel** — menu-bar-only utility (LSUIElement agent) doing window/dock-menu management; exact feature set unconfirmed beyond window-handling API usage and a GitHub-based update check. `#window-management #menubar #uncertain #LoginItems`

## Clipboard managers

- **CopyClip** — clipboard history manager living in the menu bar. `#clipboard #menubar #productivity #LoginItems`
- **Octoclip** — clipboard manager, alternative to CopyClip. `#clipboard #menubar #productivity`
- **PopClip** — popup action menu on text selection, plus clipboard extensions. `#clipboard #productivity #automation #LoginItems`

## System monitoring (menu bar)

- **iStat Menus** — full system monitor suite (CPU, RAM, disk, network, battery, sensors) in the menu bar. `#system-monitor #menubar #utility #LoginItems`
- **Stats** — open-source system monitor menu bar suite, alternative to iStat Menus. `#system-monitor #menubar #utility`
- **DockPops** — Dock enhancement tool (pop-up previews/menus from Dock icons). `#utility #productivity #LoginItems`
- **CodexBar** — menu bar status widget for Codex/AI coding-agent activity. `#ai #menubar #dev #LoginItems`
- **Only Switch** — menu bar quick-toggle panel (Wi-Fi, Bluetooth, Dark Mode, etc.). `#menubar #utility #automation #LoginItems`
- **OpenUsage** — tracks and displays AI API usage/spend. `#ai #system-monitor #utility #LoginItems`
- **ProcessSpy** — process activity monitoring/inspection tool. `#system-monitor #dev #utility #LoginItems`

## Input, customization & automation

- **Karabiner-Elements** — low-level keyboard remapping and customization. `#input #customization #utility`
- **Karabiner-EventViewer** — companion event-inspection tool for Karabiner-Elements. `#input #dev #utility`
- **BetterTouchTool** — gesture, shortcut, window-snap, and menu bar customization powertool. `#customization #automation #window-management #input #LoginItems`
- **iRightMouse** — right-click/mouse-button customization utility. `#input #customization #utility`
- **logioptionsplus** — Logitech device configuration (mice/keyboards). `#input #hardware #customization #LoginItems`
- **Raycast** — app launcher, command palette, and automation/productivity hub. `#productivity #automation #utility`

## Security & privacy

- **1Password** — password manager and vault. `#security #productivity #LoginItems`
- **1Password for Safari** — Safari browser-extension helper for 1Password. `#security #browser #LoginItems`
- **OneAuth** — Zoho's authenticator/2FA login app. `#security`
- **LuLu** — open-source outbound firewall (Objective-See). `#firewall #security #network`
- **Warden** — screen auto-lock/security utility with Touch ID auto-unlock, lid-close locking, and screen-blur-on-lock. `#security #utility #LoginItems`
- **PPPC Utility** — Apple's Privacy Preferences Policy Control (TCC) profile-building tool for admins/developers. `#dev #security #utility`
- **TCCExplorer** — inspector/browser for the macOS TCC (privacy permissions) database. `#dev #security #utility`
- **ACS Fido Tools / FidoKeyManager** — management tool for ACS FIDO/U2F hardware security keys. `#security #hardware`
- **ACS Fido Tools / PocketKey-OTP** — OTP/2FA companion tool for ACS FIDO hardware keys. `#security #hardware`
- **Thetis Manager** — FIDO hardware security key manager (Thetis brand). `#security #hardware`
- **CertAid** — MIT IS&T certificate-installation helper tool. `#security #utility`
- **App Tamer** — throttles/limits CPU usage of background apps (also a lightweight security-adjacent system hygiene tool). `#utility #system-monitor #LoginItems`

## VPN & networking

- **GlobalProtect** — Palo Alto Networks enterprise VPN client. `#vpn #network #security #LoginItems`
- **Tailscale** — mesh VPN / Wireguard-based private networking. `#vpn #network #LoginItems`
- **Eddie** — AirVPN's official OpenVPN/WireGuard client. `#vpn #network`
- **Speedtest** — internet speed test utility (Ookla). `#network #utility`
- **WakeOnCommand** — Wake-on-LAN utility to remotely wake machines. `#network #utility`

## Remote access

- **RustDesk** — open-source remote desktop client/server. `#remote-access #LoginItems`
- **TeamViewer** — remote desktop and screen-sharing tool. `#remote-access #LoginItems`
- **Windows App** — Microsoft's remote desktop client for Windows 365/Azure Virtual Desktop/RDP. `#remote-access #LoginItems`

## Backup & disk/storage utilities

- **Carbon Copy Cloner** — disk cloning and backup tool. `#backup #storage #LoginItems`
- **DriveDx** — disk health (SMART) monitoring tool. `#storage #system-monitor #LoginItems`
- **GrandPerspective** — disk usage visualizer (treemap). `#storage #utility`
- **OmniDiskSweeper** — disk usage analyzer, simpler alternative to GrandPerspective. `#storage #utility`
- **Drive Capacity Tester** — tests real vs. advertised capacity of USB/external drives (detects counterfeit drives). `#storage #utility`
- **F3XSwift** — fake flash drive / counterfeit storage capacity detector. `#storage #utility`
- **Syncthing** — peer-to-peer continuous file synchronization. `#sync #storage #LoginItems`
- **PhotoSync** — transfers/syncs photos and files between devices. `#photo #sync #utility #LoginItems`
- **AirSync** — syncs an Android phone's notifications/clipboard/files with the Mac (KDE-Connect-style). `#sync #communication #LoginItems`
- **Folder Tidy** — automatically organizes/cleans up a messy desktop or folder. `#utility #productivity`
- **NeoFinder** — media/file cataloging tool across drives. `#utility #storage #photo #LoginItems`
- **AppCleaner** — uninstaller utility that removes apps and their associated leftover files. `#utility #LoginItems`

## Developer tools

- **Xcode** — Apple's IDE for macOS/iOS development. `#dev #LoginItems`
- **Xcodes** — Xcode version manager/installer. `#dev`
- **GitHub Desktop** — GUI client for Git/GitHub. `#dev`
- **GitHub Copilot** — AI coding-assistant desktop app. `#ai #dev #LoginItems`
- **Ghostty** — GPU-accelerated terminal emulator. `#terminal #dev #LoginItems`
- **iTerm** — popular third-party terminal emulator. `#terminal #dev`
- **iTermBrowserPlugin** — browser-integration helper plugin for iTerm. `#terminal #dev`
- **Zed** — high-performance collaborative code editor. `#dev`
- **Developer** — Apple's official Developer app (WWDC videos, dev news, docs). `#dev`
- **CuaDriver** — computer-use automation driver for AI agent control of the desktop/apps. `#ai #automation #dev #LoginItems`
- **OpenCLIApp** — browser-bridge companion app for a CLI tool (connects a command-line tool to browser interaction). `#dev #utility #uncertain`

## AI tools

- **Claude** — Anthropic's Claude desktop chat/assistant app. `#ai #productivity`
- **Grok Bot** — xAI's Grok chatbot/agent desktop app. `#ai #communication #LoginItems`
- **GitHub Copilot** — see Developer tools above. `#ai #dev #LoginItems`
- **BetterStage** — multi-provider AI/LLM client connecting to several model APIs (Anthropic, Google AI Studio, DeepSeek, Groq, Tencent Hunyuan, etc.). `#ai #productivity #LoginItems`
- **OpenUsage** — see System monitoring above. `#ai #system-monitor #LoginItems`
- **CodexBar** — see Menu bar above. `#ai #menubar #dev #LoginItems`
- **Hermes** — djbclark's personal AI agent/automation hub app (messaging, cron jobs, MCP server, Gmail indexing and more). `#ai #automation #communication`
- **HermesDesktop** — desktop companion/UI app for Hermes. `#ai #automation #communication`

## Browsers

- **Safari** — Apple's default browser (system symlink). `#browser`
- **Google Chrome** — Google's browser. `#browser #LoginItems`
- **Brave Browser** — privacy-focused Chromium-based browser. `#browser`
- **Firefox** — Mozilla's browser. `#browser`
- **Zen** — Firefox-based browser focused on tab/workspace organization. `#browser`

## Communication & social

- **Slack** — team chat/collaboration. `#communication #LoginItems`
- **Discord** — voice/text chat, gaming-community focused. `#communication #LoginItems`
- **BetterDiscord Installer** — installs the BetterDiscord client mod for Discord. `#utility #communication`
- **VencordInstaller** — installs the Vencord client mod for Discord. `#utility #communication`
- **Telegram** — official Telegram client (Mac App Store build). `#communication #LoginItems`
- **Telegram Desktop** — official Telegram client (direct-download build, separate from the App Store app above). `#communication #LoginItems`
- **Element** — Matrix protocol chat client. `#communication`
- **Beeper Desktop** — unified multi-network chat client. `#communication #LoginItems`
- **Bluesky** — Bluesky social network client. `#social #communication`
- **zoom.us** — Zoom video conferencing. `#communication #video #LoginItems`
- **Fieldy** — Fieldy.ai desktop app, AI-assisted meeting/call productivity tool. `#ai #productivity #communication #LoginItems`

## Email

- **Shortwave** — third-party Gmail-focused email client. `#email #communication`
- **Texty** — Tunabelly Software app for syncing/sending Android SMS messages on the Mac. `#communication #sync`

## Media — audio, video, photo

- **Spotify** — music streaming. `#audio #media #LoginItems`
- **VLC** — universal media player. `#media #video #audio`
- **Audacity 4** — audio editor/recorder. `#audio #media`
- **GIMP** — raster image editor. `#photo #media`
- **Lyn** — fast image viewer. `#photo #media`
- **XnViewMP** — image viewer/browser/batch converter. `#photo #media`
- **QuickLook Video** — adds Spotlight/QuickLook preview support for video files. `#media #utility #LoginItems`
- **Blackmagic Proxy Generator Lite** — generates proxy/transcoded video files for editing workflows. `#video #media`
- **Blackmagic RAW Player** — plays Blackmagic RAW (.braw) video files. `#video #media #LoginItems`
- **Blackmagic RAW Speed Test** — benchmarks read/decode speed for Blackmagic RAW footage. `#video #utility`
- **PlayCover** — runs sideloaded iOS apps/games on Apple Silicon Macs. `#gaming #utility`
- **Deepnest-mac** — nesting/layout optimizer for laser-cutting/CNC material usage. `#design #utility`

## Productivity, notes & calendar

- **Logseq** — outliner-style note-taking/knowledge-base app. `#notes #productivity`
- **Marked 2** — live Markdown previewer. `#productivity #dev`
- **CalenGoo** — calendar client (Google Calendar focused). `#calendar #productivity`
- **Bulk Edit Calendar Events** — bulk-editing utility for calendar events. `#calendar #productivity #utility`
- **Amazon Kindle** — e-book reader. `#reading #media`
- **Pocket** — read-it-later/article-saving app. `#reading #productivity`
- **QR Capture** — QR code scanner/generator. `#utility`
- **Google Docs** — Chrome web-app shortcut for Google Docs. `#productivity #browser`
- **Google Sheets** — Chrome web-app shortcut for Google Sheets. `#productivity #browser`
- **Google Slides** — Chrome web-app shortcut for Google Slides. `#productivity #browser`
- **Better Rename 9** — batch file-renaming utility. `#utility #productivity`

## Finance

- **Banktivity** — personal finance and budgeting app. `#finance`

## Hardware & misc utilities

- **GrandPerspective, OmniDiskSweeper, F3XSwift, Drive Capacity Tester** — see Backup & disk/storage utilities above.
- **Paletro** — macOS color/design utility by appmakes.io; exact feature set beyond "productivity"-category design tooling unconfirmed. `#design #productivity #uncertain #LoginItems`
- **Reef** — menu-bar-only utility (LSUIElement agent) with licensing/checkout integration and timer-related code; likely a menu bar timer or productivity tool, feature set unconfirmed. `#menubar #productivity #uncertain #LoginItems`
- **Vorssaint** — menu-bar-only utility combining an AI-agent pricing/cost reference (`agent-prices.json`) with a "Now Playing" media-status component; open source (`vorssaint/vorssaint-utils`). `#ai #menubar #system-monitor #uncertain #LoginItems`
- **Adobe Acrobat (Adobe Acrobat DC)** — PDF reader/editor. `#productivity #utility #LoginItems`

## Login-item apps with no clearer category above

(All already covered in their functional sections; this is just a cross-check note, not a separate list — every app tagged `#LoginItems` above appears in the background-task-management registration dump provided for this inventory.)

## Witch (not in /Applications)

- **Witch** — Many Tricks' app/window switcher, installed as a legacy System Preferences pane at `/Users/djbclark/Library/PreferencePanes/Witch.prefPane`, with background helper `witchdaemon` (`com.manytricks.witchdaemon`) currently enabled/running. Same functional category as AltTab/Contexts. `#switcher #window-management #LoginItems`

---

## Notes on uncertain entries

A handful of small, mostly `LSUIElement` (menu-bar-agent) apps had no discoverable description, App Store category text, or clear marketing strings even after checking bundle identifiers, linked frameworks, and embedded URL strings: **Forel**, **Paletro**, **Reef**, **Vorssaint**, and **OpenCLIApp**. Best-effort descriptions above are inferred from binary strings (API endpoints, framework names, update-check URLs) and are flagged `#uncertain`. Everything else in this inventory was identified with reasonable confidence from its bundle ID, vendor, linked frameworks, or direct knowledge of the app.

One empty, non-functional folder — `digiKam.org` (zero contents, likely a leftover from an uninstalled or never-completed digiKam install) — was found in `/Applications` but excluded from the count above since there is nothing to catalog.
