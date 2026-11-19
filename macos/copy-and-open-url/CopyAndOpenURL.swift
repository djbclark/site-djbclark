import AppKit

/// Minimal URL-handler app (for Velja or default-browser pickers) that copies
/// any opened URLs to the macOS general pasteboard (`NSPasteboard.general`),
/// opens them in the user's default browser (bypassing Velja to avoid loops),
/// and exits without showing a Dock icon or window.
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var handledURL = false
    private let selfBundleIDs: Set<String> = [
        "com.djbclark.copy-url",
        "com.djbclark.copy-and-open-url",
        "com.sindresorhus.Velja",
    ]

    func applicationDidFinishLaunching(_ notification: Notification) {
        let cliURLs = CommandLine.arguments.dropFirst().compactMap { arg -> URL? in
            guard !arg.hasPrefix("-") else { return nil }
            return URL(string: arg)
        }
        if !cliURLs.isEmpty {
            copyOpenAndQuit(cliURLs)
            return
        }

        // LaunchServices delivers Apple Events shortly after launch; exit if none arrive.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            if !self.handledURL {
                NSApp.terminate(nil)
            }
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        copyOpenAndQuit(urls)
    }

    private func resolveTargetBrowserURL() -> URL? {
        let ws = NSWorkspace.shared

        // 1. Explicit user override: `defaults write com.djbclark.copy-and-open-url browserBundleID <id>`
        if let overrideID = UserDefaults.standard.string(forKey: "browserBundleID"),
           !overrideID.isEmpty,
           let appURL = ws.urlForApplication(withBundleIdentifier: overrideID) {
            return appURL
        }

        // 2. System default https handler, unless it is Velja or a Copy URL helper
        if let probe = URL(string: "https://"),
           let sysDefault = ws.urlForApplication(toOpen: probe),
           let bundleID = Bundle(url: sysDefault)?.bundleIdentifier,
           !selfBundleIDs.contains(bundleID) {
            return sysDefault
        }

        // 3. When Velja is the system default, check Velja's configured defaultBrowser / alternativeBrowser
        if let veljaDefaults = UserDefaults(suiteName: "com.sindresorhus.Velja") {
            for key in ["defaultBrowser", "alternativeBrowser"] {
                if let value = veljaDefaults.string(forKey: key),
                   value.hasPrefix("browser:") {
                    let bundleID = String(value.dropFirst("browser:".count))
                    if !selfBundleIDs.contains(bundleID),
                       let appURL = ws.urlForApplication(withBundleIdentifier: bundleID) {
                        return appURL
                    }
                }
            }
        }

        // 4. Fallback to Safari
        return ws.urlForApplication(withBundleIdentifier: "com.apple.Safari")
    }

    private func copyOpenAndQuit(_ urls: [URL]) {
        handledURL = true
        let text = urls.map(\.absoluteString).joined(separator: "\n")
        if !text.isEmpty {
            let pb = NSPasteboard.general
            pb.clearContents()
            pb.setString(text, forType: .string)
        }

        guard let browserURL = resolveTargetBrowserURL() else {
            DispatchQueue.main.async { NSApp.terminate(nil) }
            return
        }

        let config = NSWorkspace.OpenConfiguration()
        config.activates = true
        NSWorkspace.shared.open(urls, withApplicationAt: browserURL, configuration: config) { _, _ in
            DispatchQueue.main.async {
                NSApp.terminate(nil)
            }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
