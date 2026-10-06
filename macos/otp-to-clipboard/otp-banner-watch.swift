// otp-banner-watch: push-based notification banner watcher for otp-to-clipboard.
//
// Registers an AXObserver on the Notification Center process, so the moment a
// banner window is created the text is read from its accessibility tree (no
// polling, unlike Otifier's 1.5 s AX poll, and ~8 s sooner than the usernoted
// DB, which is written late). Each new banner's text is piped to
// `otp-to-clipboard --text`, which owns extraction, dedupe, and the copy.
//
//   otp-banner-watch                 run (what the LaunchAgent does)
//   otp-banner-watch --dump          log each banner's text tree to stderr
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
    if depth > 14 { return }
    let role = attr(el, kAXRoleAttribute) as? String ?? ""
    for k in [kAXTitleAttribute, kAXValueAttribute, kAXDescriptionAttribute] {
        if let s = attr(el, k) as? String, !s.isEmpty, !out.contains(s) {
            out.append(s)
            if dump { log("  " + String(repeating: " ", count: depth) + "\(role).\(k)=\(s)") }
        }
    }
    for c in (attr(el, kAXChildrenAttribute) as? [AXUIElement]) ?? [] { texts(c, depth: depth + 1, into: &out) }
}

var seen: [String: Date] = [:]
var pending: DispatchWorkItem?
var appEl: AXUIElement!

func scan() {
    var all: [String] = []
    for w in (attr(appEl, kAXWindowsAttribute) as? [AXUIElement]) ?? [] { texts(w, into: &all) }
    let text = all.joined(separator: "\n")
    guard !text.isEmpty else { return }
    seen = seen.filter { Date().timeIntervalSince($0.value) < 120 }
    if seen[text] != nil { return }
    seen[text] = Date()
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    p.arguments = [extractor, "--text"]
    let pipe = Pipe()
    p.standardInput = pipe
    do { try p.run() } catch { log("spawn failed: \(error)"); return }
    pipe.fileHandleForWriting.write(text.data(using: .utf8)!)
    try? pipe.fileHandleForWriting.close()
}

// Banner contents can settle a beat after the window appears; coalesce events.
func schedule() {
    pending?.cancel()
    let w = DispatchWorkItem { scan() }
    pending = w
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.12, execute: w)
}

let callback: AXObserverCallback = { _, _, _, _ in schedule() }

func attach() -> Bool {
    guard let app = NSWorkspace.shared.runningApplications.first(where: { ncBundleIDs.contains($0.bundleIdentifier ?? "") }) else {
        log("Notification Center not running"); return false
    }
    appEl = AXUIElementCreateApplication(app.processIdentifier)
    var obs: AXObserver?
    guard AXObserverCreate(app.processIdentifier, callback, &obs) == .success, let o = obs else { log("AXObserverCreate failed"); return false }
    var added = 0
    for n in [kAXWindowCreatedNotification, kAXCreatedNotification, kAXLayoutChangedNotification] {
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
RunLoop.main.run()
