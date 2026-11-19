import AppKit

/// Minimal URL-handler app (for Velja or default-browser pickers) that copies
/// any opened URLs to the macOS general pasteboard (`NSPasteboard.general`)
/// and exits without showing a Dock icon or window.
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var handledURL = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let cliURLs = CommandLine.arguments.dropFirst().compactMap { arg -> URL? in
            guard !arg.hasPrefix("-") else { return nil }
            return URL(string: arg)
        }
        if !cliURLs.isEmpty {
            copyAndQuit(cliURLs)
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
        copyAndQuit(urls)
    }

    private func copyAndQuit(_ urls: [URL]) {
        handledURL = true
        let text = urls.map(\.absoluteString).joined(separator: "\n")
        if !text.isEmpty {
            let pb = NSPasteboard.general
            pb.clearContents()
            pb.setString(text, forType: .string)
        }
        DispatchQueue.main.async {
            NSApp.terminate(nil)
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
