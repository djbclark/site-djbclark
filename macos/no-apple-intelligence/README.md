# no-apple-intelligence.mobileconfig

Hand-built (2026-10-13) after reading RemoveMacAI's `Profile.swift`/`Catalog.swift`
(github.com/omlahore/RemoveMacAI); their binary is not used. `just install`
from `macos/` applies this profile and loads `com.quiet-mac.enforce`, which
SIGSTOPs this user's jobs and SIGTERMs the short system jobs every 60 seconds.
Persistent clients (assistantd, coreaudiod, Siri AI.app) reactivate the
daemons within ~1 s, and with SIP on nothing can unload them. This profile
reduces what the clients ask for; the daemons stay loaded.

[`../sip-doit-with-sudo.sh`](../sip-doit-with-sudo.sh) is the older flag
applier. NeoFinder's `just services` and `just services-status` still run it,
and on this machine `~/.hermes/scripts/check-macos-daemon-disables.sh` runs
its `--check`. The site `apple-daemons` rule also TERMs the same list. The
standing hold for a Mac that has run `just install` is `com.quiet-mac.enforce`.

Contains:
1. `com.apple.applicationaccess` restrictions (all `false`): allowAssistant,
   allowExternalIntelligenceIntegrations (+SignIn), allowWritingTools,
   allowGenmoji, allowImagePlayground, allowMailSummary, allowMailSmartReplies,
   allowSafariSummary, allowNotesTranscriptionSummary. Deprecated by Apple in
   26.4 but still working on 27.0.1 (MacRumors, 2026-10-05).
2. Forced preferences: Siri off (`com.apple.assistant.support`, `com.apple.Siri`),
   Mail and Messages summaries and smart replies, notification summaries.
3. `com.apple.MobileAsset` `DownloadServerBaseURLOverride-` for
   `com.apple.MobileAsset.UAF.FM.GenerativeModels` and `...FM.Visual`, pointed at
   `https://127.0.0.1:9/no-apple-intelligence/` so the model downloads fail.

Deliberately not touched: Xcode code completion, Photos Clean Up, Spatial Photos,
inline text predictions.

Install: `just install` from `macos/`, or `just profile` to open it again.
Since macOS 11, `profiles` cannot install a configuration profile. On macOS 15
and later (this Mac is 27) the clicks are System Settings → General →
Device Management → the Downloaded profile "No Apple Intelligence (djbclark)".
macOS 13 and 14 use Privacy & Security → Profiles. A downloaded profile is
dropped after about 8 minutes. Check: `sudo profiles list` shows
`com.djbclark.no-apple-intelligence` (it installs at computer level; the
user-level `profiles list` does not show it, verified 2026-10-15). Remove:
`just factory`, or delete it in the same pane. That undoes the profile.
