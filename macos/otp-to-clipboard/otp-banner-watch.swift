// otp-banner-watch: near-instant notification banner watcher for otp-to-clipboard.
//
// Reads the text of notification banners straight from Notification Center's
// accessibility tree and pipes each new banner to `otp-to-clipboard --text`,
// which owns extraction, dedupe and the copy. Banners show up ~8 s before the
// usernoted DB row exists, and the DB can't be read without Full Disk Access.
//
// Push vs poll: an AXObserver is registered (window/created/layout events) but
// on macOS 27 Notification Center never delivers those events (verified: zero
// callbacks with 9 notification types, with and without the AX enable flags),
// so the real trigger is a 0.25 s tick that only reads each window's top few
// AX levels and descends into elements whose subrole is AXNotificationCenter*
// (banner / alert / alert stack). The desktop-widget windows that live in the
// same process (Weather, Calendar, Photos) never match. Otifier does a full
// tree walk every 1.5 s; this is ~6x faster and much cheaper per tick.
//
//   otp-banner-watch                 run (what the LaunchAgent does)
//   otp-banner-watch --dump          log banner text and AX events to stderr
//   otp-banner-watch --request-permissions   trigger the Accessibility prompt
//
// Needs Accessibility. Run it from a launchd job so the prompt names it.

import AppKit
import ApplicationServices

let home = FileManager.default.homeDirectoryForCurrentUser.path
let extractor = "\(home)/ops/site-djbclark/bin/otp-to-clipboard"
let dump = CommandLine.arguments.contains("--dump")
let ncBundleIDs = ["com.apple.notificationcenterui", "com.apple.NotificationCenter"]

func log(_ s: String) {
    FileHandle.standardError.write(("\(Date()) \(s)\n").data(using: .utf8)!)
}

if CommandLine.arguments.contains("--request-permissions") {
    let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    log("accessibility trusted: \(AXIsProcessTrustedWithOptions(opts))")
    exit(0)
}

func attr(_ el: AXUIElement, _ name: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, name as CFString, &v) == .success ? (v as AnyObject?) : nil
}

/// Collect every text-bearing string under el (depth-capped).
func texts(_ el: AXUIElement, depth: Int = 0, into out: inout [String]) {
    if depth > 8 { return }
    for k in [kAXTitleAttribute, kAXValueAttribute] {
        if let s = attr(el, k) as? String, !s.isEmpty, !out.contains(s) { out.append(s) }
    }
    for c in (attr(el, kAXChildrenAttribute) as? [AXUIElement]) ?? [] { texts(c, depth: depth + 1, into: &out) }
}

/// Find banner/alert/stack elements (subrole AXNotificationCenter*) near the top of a window.
func bannerElements(_ el: AXUIElement, depth: Int = 0, into out: inout [AXUIElement]) {
    if depth > 4 { return }
    if let sr = attr(el, kAXSubroleAttribute) as? String, sr.hasPrefix("AXNotificationCenter") {
        out.append(el); return
    }
    for c in (attr(el, kAXChildrenAttribute) as? [AXUIElement]) ?? [] { bannerElements(c, depth: depth + 1, into: &out) }
}

var present = Set<String>()   // banner texts visible on the previous tick
var appEl: AXUIElement!

func scan() {
    var banners: [AXUIElement] = []
    for w in (attr(appEl, kAXWindowsAttribute) as? [AXUIElement]) ?? [] { bannerElements(w, into: &banners) }
    var now = Set<String>()
    for b in banners {
        var all: [String] = []
        texts(b, into: &all)
        let text = all.joined(separator: "\n")
        guard !text.isEmpty else { continue }
        now.insert(text)
        // Only a banner that was not on screen last tick is new. Keying on "newly
        // appeared" (not a time window) means a banner that lingers in the stack never
        // re-copies, while a genuinely re-sent identical code, after the old one is
        // gone, does.
        if present.contains(text) { continue }
        if dump { log("banner: \(all)") }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        // Banner description is "<App>, <title>, <body>": pass only the app name for the log.
        let appName = (attr(b, kAXDescriptionAttribute) as? String)?.components(separatedBy: ", ").first ?? "?"
        p.arguments = [extractor, "--text", "--app", appName]
        let pipe = Pipe()
        p.standardInput = pipe
        do { try p.run() } catch { log("spawn failed: \(error)"); continue }
        pipe.fileHandleForWriting.write(text.data(using: .utf8)!)
        try? pipe.fileHandleForWriting.close()
    }
    present = now
}

func schedule() { scan() }

let callback: AXObserverCallback = { _, el, note, _ in
    if dump { log("event \(note) role=\(attr(el, kAXRoleAttribute) as? String ?? "?") subrole=\(attr(el, kAXSubroleAttribute) as? String ?? "?")") }
    schedule()
}

func attach() -> Bool {
    guard let app = NSWorkspace.shared.runningApplications.first(where: { ncBundleIDs.contains($0.bundleIdentifier ?? "") }) else {
        log("Notification Center not running"); return false
    }
    appEl = AXUIElementCreateApplication(app.processIdentifier)
    var obs: AXObserver?
    guard AXObserverCreate(app.processIdentifier, callback, &obs) == .success, let o = obs else { log("AXObserverCreate failed"); return false }
    var added = 0
    for n in [kAXWindowCreatedNotification, kAXCreatedNotification, kAXLayoutChangedNotification,
              "AXChildrenChanged", kAXUIElementDestroyedNotification, kAXFocusedUIElementChangedNotification,
              kAXMainWindowChangedNotification, kAXFocusedWindowChangedNotification, kAXApplicationShownNotification] {
        if AXObserverAddNotification(o, appEl, n as CFString, nil) == .success { added += 1 }
    }
    CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(o), .defaultMode)
    log("observing pid \(app.processIdentifier) (\(added) notifications)")
    return added > 0
}

if !AXIsProcessTrusted() {
    log("not trusted for Accessibility; waiting for the grant")
    while !AXIsProcessTrusted() { Thread.sleep(forTimeInterval: 10) }
}
// NotificationCenter restarts (logout, crashes): re-attach when it relaunches.
while !attach() { Thread.sleep(forTimeInterval: 5) }
NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main) { n in
    if let a = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, ncBundleIDs.contains(a.bundleIdentifier ?? "") {
        _ = attach()
    }
}
Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { _ in scan() }
RunLoop.main.run()
