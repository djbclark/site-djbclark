# Local findings: why the five Apple Intelligence daemons respawn (macOS 27.0.1, SIP on, 2026-10-13)

Source: `log show` of launchd/xpcproxy and per-process lines around respawns, 08:52-08:56.

1. launchd logs "Successfully spawned X because ipc (mach)" (intelligencecontextd, modelmanagerd,
   modelcatalogd, generativeexperiencesd) or "because xpc event" (intelligenceflowd), ~1 s after each kill.
2. Observed reconnecting clients (log lines in the same second as the spawn):
   - assistantd: "com.apple.intelligenceflow.toolbox: Connection to XPC Server interrupted" -> intelligenceflowd;
     intelligenceflowd then connects to intelligencecontextd.
   - coreaudiod: "(ModelManagerServices) modelmanagerd connection cancellation", then activates `com.apple.modelmanager`.
   - Siri AI.app / BackgroundShortcutRunner: `com.apple.generativeexperiences.ExternalProviderTCCManagingXPC`
     -> generativeexperiencesd. (One observation; modelcatalogd's caller was NOT identified.)
3. Siri was already off (`com.apple.assistant.support` "Assistant Enabled" = 0); the clients run anyway.
4. Per-spawn CPU time (ps TIME at ~35 s): intelligenceflowd 1.62 s, modelmanagerd 0.47 s,
   intelligencecontextd 0.19 s: ~2.3 s per cycle, an estimate, not a system-wide measurement.
5. After the restrictions profile (macos/no-apple-intelligence) was installed, the trio was still
   respawned every minute 09:41-09:52; hence all five became flag-only (site-djbclark 863e3f5, 3951e89).
6. Plist facts (plutil -p): intelligenceflowd has a feature-flag-conditional `Disabled`;
   modelmanagerd MachServices `com.apple.modelmanager`, ThrottleInterval 1; modelcatalogd launches on
   notifyd matching (first unlock, MobileAsset, setup done) and mach lookups; all but modelmanagerd set EnablePressuredExit.
