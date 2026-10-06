// corner-rescue: top-left hot corner that un-wedges keyboard/click input,
// then counts down 30 s to a logout unless cancelled.
//
// Why polling: NSEvent.mouseLocation is read straight from WindowServer, so
// the trigger keeps working even when an event tap or a stuck virtual HID
// button is eating keystrokes and clicks (pointer motion still works then).
//
// Cancel the countdown by: clicking Cancel, pressing Esc, or moving the
// pointer into the top-RIGHT corner (works even when clicks are dead).
//
// It also runs an always-on flight recorder (see Recorder) and, on trigger,
// saves an incident bundle under ~/.local/state/corner-rescue/incidents/.
// Grants it wants (run `corner-rescue --request-permissions` once after each
// rebuild): Input Monitoring (see keys), Accessibility (hung-app check and
// synthetic button-ups), Screen Recording (incident screenshot).

import AppKit
import CoreGraphics
import Carbon

let home = FileManager.default.homeDirectoryForCurrentUser.path
let logPath = "\(home)/.local/state/corner-rescue.log"
let karabinerCLI = "/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli"
let passthroughProfile = "Rescue passthrough"
let dwell: TimeInterval = 0.5
let countdownSeconds = 30
let dryRun = CommandLine.arguments.contains("--dry-run")  // skip the logout itself

let logLock = NSLock()
let stamp: DateFormatter = {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"; return f  // local time, ms
}()

func log(_ s: String) {
    logLock.lock(); defer { logLock.unlock() }
    let line = "[\(stamp.string(from: Date()))] \(s)\n"
    let fm = FileManager.default
    if let size = (try? fm.attributesOfItem(atPath: logPath))?[.size] as? Int, size > 20_000_000 {
        try? fm.removeItem(atPath: logPath + ".1")
        try? fm.moveItem(atPath: logPath, toPath: logPath + ".1")
    }
    if let h = FileHandle(forWritingAtPath: logPath) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile()
    } else {
        fm.createFile(atPath: logPath, contents: line.data(using: .utf8))
    }
}

@discardableResult
func run(_ path: String, _ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe; p.standardError = pipe
    do { try p.run() } catch { return "launch failed: \(error)" }
    // Drain before waiting: a child with >64 KB of output blocks on a full pipe.
    let out = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return String(data: out, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
}

// MARK: - Diagnostics (logged before touching anything, to catch the culprit)

func snapshot() {
    let src = CGEventSourceStateID.hidSystemState
    let buttons = (0..<3).map { CGEventSource.buttonState(src, button: CGMouseButton(rawValue: $0)!) }
    log("buttons held (L,R,M) per HID state: \(buttons)  flags=0x\(String(CGEventSource.flagsState(src).rawValue, radix: 16))")
    log("frontmost app: \(NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "?")  secureInput=\(IsSecureEventInputEnabled())")
    var n: UInt32 = 0
    CGGetEventTapList(0, nil, &n)
    var taps = [CGEventTapInformation](repeating: CGEventTapInformation(), count: Int(n))
    CGGetEventTapList(n, &taps, &n)
    for t in taps where t.enabled && t.options != .listenOnly {
        let name = NSRunningApplication(processIdentifier: t.tappingProcess)?.localizedName ?? "pid \(t.tappingProcess)"
        log(String(format: "  active tap: %@ mask=0x%llx avgLat=%.0fms maxLat=%.0fms",
                   name, t.eventsOfInterest, t.avgUsecLatency / 1000, t.maxUsecLatency / 1000))
    }
    let kLog = run("/usr/bin/tail", ["-n", "400", "/var/log/karabiner/core_service.log"])
    let recentLoads = kLog.split(separator: "\n").filter { $0.contains("Load ") }.suffix(3)
    log("karabiner last reloads: \(recentLoads.joined(separator: " | "))")
    if let w = windowUnderCursor() { log("window under cursor (gets the clicks): \(w)") }
    if let a = NSWorkspace.shared.frontmostApplication { log("frontmost responsive: \(appResponsive(a.processIdentifier).map(String.init) ?? "unknown (no AX grant)")") }
    recorder.logAges()
}

func describe(_ w: [String: Any]) -> String {
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    return "\(w[kCGWindowOwnerName as String] ?? "?") (pid \(w[kCGWindowOwnerPID as String] ?? "?")) "
        + "\"\(w[kCGWindowName as String] ?? "")\" layer=\(w[kCGWindowLayer as String] ?? "?") "
        + "alpha=\(w[kCGWindowAlpha as String] ?? "?") bounds=\(b["X"] ?? 0),\(b["Y"] ?? 0) \(b["Width"] ?? 0)x\(b["Height"] ?? 0)"
}

func onscreenWindows() -> [[String: Any]] {
    (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]) ?? []
}

/// Front-most on-screen window containing the pointer: whatever is actually
/// receiving clicks. An invisible overlay shows up here with a low alpha.
func windowUnderCursor() -> String? {
    guard let p = CGEvent(source: nil)?.location else { return nil }
    for w in onscreenWindows() {
        guard let d = w[kCGWindowBounds as String] as? NSDictionary,
              let r = CGRect(dictionaryRepresentation: d), r.contains(p) else { continue }
        return describe(w)
    }
    return nil
}

/// nil = can't tell (needs Accessibility). false = app hung (AX call timed out).
func appResponsive(_ pid: pid_t) -> Bool? {
    guard AXIsProcessTrusted() else { return nil }
    let el = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(el, 0.5)
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, kAXFocusedWindowAttribute as CFString, &v) != .cannotComplete
}

/// Everything worth having when it happens, in one directory per incident.
func captureIncident() {
    let dir = "\(home)/.local/state/corner-rescue/incidents/\(stamp.string(from: Date()).replacingOccurrences(of: " ", with: "_"))"
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    log("incident bundle: \(dir)")
    run("/usr/sbin/screencapture", ["-x", "\(dir)/screen.png"])  // wallpaper-only without Screen Recording grant
    try? onscreenWindows().map(describe).joined(separator: "\n").write(toFile: "\(dir)/windows.txt", atomically: true, encoding: .utf8)
    try? run("/bin/ps", ["-Ao", "pid,%cpu,%mem,state,etime,comm", "-r"]).write(toFile: "\(dir)/ps.txt", atomically: true, encoding: .utf8)
    try? run("/usr/sbin/ioreg", ["-l", "-w", "0", "-d", "1", "-k", "IOConsoleUsers"]).write(toFile: "\(dir)/ioreg-console.txt", atomically: true, encoding: .utf8)
    run("/bin/cp", [logPath, "\(dir)/recorder.log"])
    run("/bin/cp", ["/var/log/karabiner/core_service.log", "\(dir)/karabiner-core_service.log"])
    // Slow (tens of seconds); runs detached so the countdown isn't held up.
    DispatchQueue.global(qos: .utility).async {
        let pred = #"process IN {"WindowServer","loginwindow","universalAccessAuthWarn","SecurityAgent","UserNotificationCenter","tccd","Karabiner-Core-Service","Karabiner-Console-User-Server","cua-driver","BetterTouchTool","Raycast","Contexts"} OR subsystem BEGINSWITH "com.apple.iohid" OR subsystem == "com.apple.SkyLight""#
        try? run("/usr/bin/log", ["show", "--last", "5m", "--style", "compact", "--predicate", pred])
            .write(toFile: "\(dir)/unified.log", atomically: true, encoding: .utf8)
        log("incident unified log written")
    }
}

// MARK: - Flight recorder (always on; the evidence for next time)
//
// Two listen-only taps bracket the event pipeline: one where events enter
// WindowServer (HID level, after Karabiner's virtual device) and one after
// every app's active tap (annotated session). An event seen at the first but
// never at the second was swallowed by an active tap; its latency tells us
// if a tap is stalling. Events are paired FIFO per (type, key/button):
// timestamps can't be used, WindowServer re-stamps hardware events between
// the two points. Key codes are used for pairing in memory only, never logged.

final class Recorder {
    struct Pending { let seen: Date; let type: CGEventType; let flags: CGEventFlags }
    var pending: [String: [Pending]] = [:]  // FIFO per (type, key/button)
    let lock = NSLock()
    var counts = (hid: 0, session: 0, lost: 0, slow: 0)
    var lastHID: [String: Date] = [:]  // "key" / "click" -> last seen at HID level
    var lastTick = Date()
    var buttonHeldSince: Date?
    var secureInput = false
    var seenWindows = Set<Int>()
    var karabinerOffset: UInt64 = 0
    var karabinerLoads: [Date] = []

    static let mask: CGEventMask = [CGEventType.keyDown, .keyUp, .flagsChanged, .leftMouseDown, .leftMouseUp,
                                     .rightMouseDown, .rightMouseUp, .otherMouseDown, .otherMouseUp]
        .reduce(0) { $0 | (1 << $1.rawValue) }

    func id(_ e: CGEvent) -> String {
        let code = kind(e.type) == "key" ? e.getIntegerValueField(.keyboardEventKeycode)
                                          : e.getIntegerValueField(.mouseEventButtonNumber)
        return "\(e.type.rawValue)-\(code)"
    }

    func start() {
        log("recorder: grants inputMonitoring=\(CGPreflightListenEventAccess()) accessibility=\(AXIsProcessTrusted()) screenRecording=\(CGPreflightScreenCaptureAccess())")
        tap(.cghidEventTap, place: .headInsertEventTap) { r, e in r.sawHID(e) }
        tap(.cgAnnotatedSessionEventTap, place: .tailAppendEventTap) { r, e in r.sawSession(e) }
        Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in self?.fastTick() }
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            DispatchQueue.global(qos: .utility).async { self?.slowTick() }
        }
        let hb = Double(ProcessInfo.processInfo.environment["CORNER_RESCUE_HEARTBEAT"] ?? "") ?? 300
        Timer.scheduledTimer(withTimeInterval: hb, repeats: true) { [weak self] _ in self?.heartbeat() }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification,
                                                          object: nil, queue: .main) { n in
            let a = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            log("focus -> \(a?.bundleIdentifier ?? a?.localizedName ?? "?") (pid \(a?.processIdentifier ?? 0))")
        }
        karabinerOffset = fileSize("/var/log/karabiner/core_service.log")
        for w in onscreenWindows() { seenWindows.insert(w[kCGWindowNumber as String] as? Int ?? 0) }
    }

    typealias Handler = (Recorder, CGEvent) -> Void
    var handlers: [Handler] = []

    func tap(_ loc: CGEventTapLocation, place: CGEventTapPlacement, _ h: @escaping Handler) {
        handlers.append(h)
        let ctx = UnsafeMutableRawPointer(bitPattern: handlers.count)  // 1-based handler index
        let cb: CGEventTapCallBack = { _, type, event, ctx in
            let r = recorder
            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                log("recorder: own tap disabled (\(type.rawValue)); re-enabling")
                for t in r.machPorts { CGEvent.tapEnable(tap: t, enable: true) }
            } else if let i = ctx.map({ Int(bitPattern: $0) }) {
                r.handlers[i - 1](r, event)
            }
            return Unmanaged.passUnretained(event)
        }
        guard let port = CGEvent.tapCreate(tap: loc, place: place, options: .listenOnly,
                                           eventsOfInterest: Recorder.mask, callback: cb, userInfo: ctx) else {
            log("recorder: tapCreate failed at \(loc.rawValue)"); return
        }
        machPorts.append(port)
        CFRunLoopAddSource(CFRunLoopGetMain(), CFMachPortCreateRunLoopSource(nil, port, 0), .commonModes)
    }
    var machPorts: [CFMachPort] = []

    func kind(_ t: CGEventType) -> String {
        switch t { case .keyDown, .keyUp, .flagsChanged: return "key"; default: return "click" }
    }

    func sawHID(_ e: CGEvent) {
        lock.lock(); defer { lock.unlock() }
        counts.hid += 1
        lastHID[kind(e.type)] = Date()
        pending[id(e), default: []].append(Pending(seen: Date(), type: e.type, flags: e.flags))
    }

    func sawSession(_ e: CGEvent) {
        lock.lock(); defer { lock.unlock() }
        counts.session += 1
        let k = id(e)
        guard var q = pending[k], !q.isEmpty else { return }  // synthetic/posted at session level
        let p = q.removeFirst()
        pending[k] = q.isEmpty ? nil : q
        let ms = Date().timeIntervalSince(p.seen) * 1000
        if ms > 250 {
            counts.slow += 1
            log(String(format: "SLOW %@ type=%d took %.0f ms through the tap chain; active taps: %@",
                       kind(p.type), p.type.rawValue, ms, activeTaps()))
        }
    }

    func fastTick() {
        let now = Date()
        let drift = now.timeIntervalSince(lastTick) - 0.5
        if drift > 1.0 { log(String(format: "STALL: main thread/timer %.1f s late (system or WindowServer stall?)", drift)) }
        lastTick = now
        lock.lock()
        for (k, q) in pending {
            let expired = q.prefix { now.timeIntervalSince($0.seen) > 1.5 }
            guard !expired.isEmpty else { continue }
            pending[k] = q.count == expired.count ? nil : Array(q.dropFirst(expired.count))
            for p in expired {
                counts.lost += 1
                // Modifier flags only: enough to spot a swallowed hotkey, never the typed text.
                log("LOST \(kind(p.type)) type=\(p.type.rawValue) modifiers=0x\(String(p.flags.rawValue & 0xff0000, radix: 16)): "
                    + "entered WindowServer, never left the tap chain; active taps: \(activeTaps()); frontmost=\(NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "?")")
            }
        }
        lock.unlock()
        // A left button that stays down with no fresh HID click: stuck virtual button.
        if CGEventSource.buttonState(.hidSystemState, button: .left) {
            if buttonHeldSince == nil { buttonHeldSince = now }
            if let s = buttonHeldSince, now.timeIntervalSince(s) > 8, Int(now.timeIntervalSince(s) * 2) % 20 == 0 {
                log(String(format: "STUCK? left button held %.0f s (last HID click %@)", now.timeIntervalSince(s), age("click")))
            }
        } else if let s = buttonHeldSince {
            if now.timeIntervalSince(s) > 8 { log(String(format: "left button released after %.0f s", now.timeIntervalSince(s))) }
            buttonHeldSince = nil
        }
        let si = IsSecureEventInputEnabled()
        if si != secureInput {
            secureInput = si
            let pid = run("/bin/sh", ["-c", "ioreg -l -w 0 | grep -o 'kCGSSessionSecureInputPID\"=[0-9]*' | head -1 | cut -d= -f2"])
            log("secure input \(si ? "ON" : "off")\(si ? " by pid \(pid) (\(NSRunningApplication(processIdentifier: pid_t(pid) ?? 0)?.localizedName ?? "?"))" : "") — keyboard taps go blind while on")
        }
    }

    func slowTick() {
        // New system prompts / big overlays: things that steal focus or clicks.
        guard let main = NSScreen.screens.first?.frame else { return }
        let prompts: Set<String> = ["universalAccessAuthWarn", "SecurityAgent", "UserNotificationCenter",
                                    "CoreServicesUIAgent", "tccd", "coreautha", "Captive Network Assistant"]
        var current = Set<Int>()
        for w in onscreenWindows() {
            let n = w[kCGWindowNumber as String] as? Int ?? 0
            current.insert(n)
            guard !seenWindows.contains(n) else { continue }
            let owner = w[kCGWindowOwnerName as String] as? String ?? ""
            let layer = w[kCGWindowLayer as String] as? Int ?? 0
            let r = (w[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation: $0) } ?? .zero
            if prompts.contains(owner) || (layer > 0 && r.width * r.height > main.width * main.height * 0.25) {
                log("WINDOW appeared: \(describe(w))")
            }
        }
        seenWindows = current
        if let a = NSWorkspace.shared.frontmostApplication, appResponsive(a.processIdentifier) == false {
            log("HUNG frontmost app: \(a.bundleIdentifier ?? "?") (AX timed out; keys/clicks to it will look eaten)")
        }
        // Karabiner reload storms.
        let path = "/var/log/karabiner/core_service.log"
        let size = fileSize(path)
        if size < karabinerOffset { karabinerOffset = 0 }  // rotated
        if size > karabinerOffset, let h = FileHandle(forReadingAtPath: path) {
            h.seek(toFileOffset: karabinerOffset)
            let text = String(data: h.readDataToEndOfFile(), encoding: .utf8) ?? ""
            h.closeFile()
            karabinerOffset = size
            let now = Date()
            karabinerLoads += text.split(separator: "\n").filter { $0.contains("Load ") }.map { _ in now }
            karabinerLoads.removeAll { now.timeIntervalSince($0) > 60 }
            if karabinerLoads.count >= 10 { log("KARABINER reload storm: \(karabinerLoads.count) config loads in last 60 s") }
            for l in text.split(separator: "\n") where l.contains("[error]") || l.contains("[warn]") || l.contains("is terminated") || l.contains("monitor is stopped") {
                log("karabiner: \(l)")
            }
        }
    }

    func heartbeat() {
        lock.lock(); let c = counts; counts = (0, 0, 0, 0); lock.unlock()
        log("heartbeat: hid=\(c.hid) session=\(c.session) lost=\(c.lost) slow=\(c.slow)")
    }

    func age(_ k: String) -> String {
        lock.lock(); defer { lock.unlock() }
        return lastHID[k].map { String(format: "%.1f s ago", Date().timeIntervalSince($0)) } ?? "never"
    }

    func logAges() { log("last HID-level key: \(age("key")), last HID-level click: \(age("click")) (if 'never'/stale while you were pressing: blocked below WindowServer, i.e. Karabiner/driver)") }
}

func activeTaps() -> String {
    var n: UInt32 = 0
    CGGetEventTapList(0, nil, &n)
    var taps = [CGEventTapInformation](repeating: CGEventTapInformation(), count: Int(n))
    CGGetEventTapList(n, &taps, &n)
    return taps.filter { $0.enabled && $0.options != .listenOnly }
        .map { NSRunningApplication(processIdentifier: $0.tappingProcess)?.localizedName ?? "pid \($0.tappingProcess)" }
        .joined(separator: ",")
}

func fileSize(_ p: String) -> UInt64 { ((try? FileManager.default.attributesOfItem(atPath: p))?[.size] as? UInt64) ?? 0 }

let recorder = Recorder()

// MARK: - The fix

func releaseStuckInput() {
    // Synthetic button-up / modifier-up at WindowServer level. Needs the
    // Accessibility (post events) grant; silently a no-op without it.
    let loc = CGEvent(source: nil)?.location ?? .zero
    for (type, btn) in [(CGEventType.leftMouseUp, CGMouseButton.left),
                        (.rightMouseUp, .right), (.otherMouseUp, .center)] {
        CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: loc, mouseButton: btn)?
            .post(tap: .cghidEventTap)
    }
    if let e = CGEvent(source: nil) { e.type = .flagsChanged; e.flags = []; e.post(tap: .cghidEventTap) }
}

func waitExit(_ a: NSRunningApplication) -> Bool {
    for _ in 0..<20 where !a.isTerminated { Thread.sleep(forTimeInterval: 0.1) }
    return a.isTerminated
}

func fix() {
    snapshot()
    DispatchQueue.global(qos: .utility).async { captureIncident() }  // never let evidence-gathering block the fix
    // 1. Karabiner Settings app left open drives config-reload storms.
    for a in NSRunningApplication.runningApplications(withBundleIdentifier: "org.pqrs.Karabiner-Elements.Settings") {
        if !a.terminate() || !waitExit(a) { a.forceTerminate() }  // it ignores SIGTERM
        log("quit Karabiner Settings app")
    }
    // 2. Bounce through a profile that ignores the built-in keyboard: Karabiner
    //    ungrabs then regrabs it, releasing any stuck virtual keys/buttons.
    if FileManager.default.isExecutableFile(atPath: karabinerCLI) {
        let current = run(karabinerCLI, ["--show-current-profile-name"])
        let profiles = run(karabinerCLI, ["--list-profile-names"]).split(separator: "\n").map(String.init)
        if profiles.contains(passthroughProfile) && current != passthroughProfile && !current.isEmpty {
            run(karabinerCLI, ["--select-profile", passthroughProfile])
            Thread.sleep(forTimeInterval: 1.5)
            run(karabinerCLI, ["--select-profile", current])
            log("karabiner regrab: \(current) -> \(passthroughProfile) -> \(current)")
        } else {
            log("karabiner regrab skipped (current=\(current), passthrough present=\(profiles.contains(passthroughProfile)))")
        }
    }
    // 3. Belt and braces at the WindowServer level.
    releaseStuckInput()
    log("fix applied")
}

func logout() {
    log("countdown expired: logging out\(dryRun ? " (dry run, skipped)" : "")")
    if dryRun { return }
    // Polite logout without the confirmation dialog...
    run("/usr/bin/osascript", ["-e", "tell application \"loginwindow\" to «event aevtrlgo»"])
    // ...and if an app (unsaved doc prompt nobody can answer) blocks it, force.
    DispatchQueue.global().asyncAfter(deadline: .now() + 15) {
        log("still here 15 s after logout request: forcing gui domain bootout")
        run("/bin/launchctl", ["bootout", "gui/\(getuid())"])
    }
}

// MARK: - UI

final class Controller: NSObject {
    var panel: NSPanel?
    var label: NSTextField?
    var remaining = 0
    var tick: Timer?
    var inCornerSince: Date?
    var armed = true  // re-armed once the pointer leaves the corner
    var escMonitor: Any?

    func start() {
        Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.poll() }
        log("corner-rescue started (pid \(getpid()))\(dryRun ? " [dry run]" : "")")
    }

    func corners() -> (tl: Bool, tr: Bool) {
        guard let main = NSScreen.screens.first else { return (false, false) }  // menu-bar screen
        let p = NSEvent.mouseLocation, f = main.frame
        let top = p.y >= f.maxY - 2
        return (top && p.x <= f.minX + 2, top && p.x >= f.maxX - 3)
    }

    func poll() {
        let c = corners()
        if panel != nil { if c.tr { cancel(reason: "pointer to top-right corner") }; return }
        guard c.tl else { inCornerSince = nil; armed = true; return }
        if inCornerSince == nil { inCornerSince = Date() }
        if armed, Date().timeIntervalSince(inCornerSince!) >= dwell {
            armed = false
            trigger()
        }
    }

    func trigger() {
        log("top-left corner triggered")
        showPanel()
        DispatchQueue.global(qos: .userInitiated).async {
            fix()
            DispatchQueue.main.async { self.label?.stringValue = self.text() }
        }
    }

    func text() -> String {
        "Input rescue ran (Karabiner reset, stuck buttons released).\n"
            + "Logging out in \(remaining) s.\n"
            + "If input works now: click Cancel or press Esc.\n"
            + "If clicks still dead: move pointer to TOP-RIGHT corner to cancel."
    }

    func showPanel() {
        remaining = countdownSeconds
        let frame = NSRect(x: 0, y: 0, width: 460, height: 150)
        let p = NSPanel(contentRect: frame, styleMask: [.titled, .nonactivatingPanel, .hudWindow, .utilityWindow],
                        backing: .buffered, defer: false)
        p.title = "Corner rescue"
        p.level = .screenSaver
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        p.isFloatingPanel = true
        let l = NSTextField(wrappingLabelWithString: text())
        l.frame = NSRect(x: 16, y: 50, width: 428, height: 90)
        l.font = .systemFont(ofSize: 13, weight: .medium)
        let b = NSButton(title: "Cancel logout", target: self, action: #selector(cancelClicked))
        b.frame = NSRect(x: 16, y: 12, width: 140, height: 30)
        b.keyEquivalent = "\u{1b}"
        let now = NSButton(title: "Log out now", target: self, action: #selector(nowClicked))
        now.frame = NSRect(x: 304, y: 12, width: 140, height: 30)
        p.contentView?.addSubview(l); p.contentView?.addSubview(b); p.contentView?.addSubview(now)
        if let s = NSScreen.screens.first {
            p.setFrameOrigin(NSPoint(x: s.frame.midX - frame.width / 2, y: s.frame.midY))
        }
        p.orderFrontRegardless()
        NSApp.activate(ignoringOtherApps: true)
        p.makeKey()
        escMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] e in
            if e.keyCode == 53 { self?.cancel(reason: "Esc (global)") }
        }
        panel = p; label = l
        tick = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.remaining -= 1
            self.label?.stringValue = self.text()
            if self.remaining <= 0 { self.close(); logout() }
        }
    }

    @objc func cancelClicked() { cancel(reason: "Cancel clicked/Esc") }
    @objc func nowClicked() { close(); logout() }

    func cancel(reason: String) {
        log("logout cancelled: \(reason)")
        close()
    }

    func close() {
        tick?.invalidate(); tick = nil
        if let m = escMonitor { NSEvent.removeMonitor(m); escMonitor = nil }
        panel?.orderOut(nil); panel = nil; label = nil
    }
}

if CommandLine.arguments.contains("--request-permissions") {
    // One-time, interactive: adds this binary to the three Privacy panes.
    print("input monitoring:", CGRequestListenEventAccess())
    print("accessibility:", AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary))
    print("screen recording:", CGRequestScreenCaptureAccess())
    exit(0)
}
if CommandLine.arguments.contains("--diagnose") { snapshot(); print(try! String(contentsOfFile: logPath, encoding: .utf8).split(separator: "\n").suffix(20).joined(separator: "\n")); exit(0) }

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
recorder.start()
let controller = Controller()
controller.start()
app.run()
