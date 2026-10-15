# no-apple-intelligence.mobileconfig

Hand-built (2026-10-13) after reading RemoveMacAI's `Profile.swift`/`Catalog.swift`
(github.com/omlahore/RemoveMacAI); their binary is not used. Complements
`../sip-doit-with-sudo.sh`: that script sets disable flags and the watchdogd
`apple-daemons` rule TERMs the daemons, but persistent clients (assistantd,
coreaudiod, Siri AI.app) reactivate them within ~1 s, and with SIP on nothing
can unload them. This profile reduces what the clients ask for; the daemons stay
loaded.

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

Install: `open no-apple-intelligence.mobileconfig`, then approve it in System
Settings > Privacy & Security > Profiles. Check: `sudo profiles list` shows
`com.djbclark.no-apple-intelligence` (it installs at computer level; the
user-level `profiles list` does not show it, verified 2026-10-15). Remove: delete it in the same pane; that
undoes everything.
