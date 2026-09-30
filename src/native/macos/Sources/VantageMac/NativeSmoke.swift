import AppKit
import ScreenCaptureKit
import VantageCore

/// Real-window CI smoke entry point. Uses only an explicitly provided synthetic
/// backend and never requests camera, microphone, startup, or screen permissions.
@MainActor
enum NativeSmoke {
    static func runIfRequested(_ model: AppModel) async {
        let args = ProcessInfo.processInfo.arguments
        guard let index = args.firstIndex(of: "--smoke-test"), args.indices.contains(index + 1) else { return }
        let target = URL(fileURLWithPath: args[index + 1])
        var errors: [String] = []
        var pages: [[String: Any]] = []
        var flows: [[String: Any]] = []
        var chartCaptures: [[String: Any]] = []
        let snapshots = target.deletingPathExtension().appendingPathExtension("screenshots")
        let started = Date()
        let partial = target.deletingPathExtension().appendingPathExtension("partial.json")
        func checkpoint(_ phase: String) {
            let payload: [String: Any] = ["success": false, "phase": phase, "elapsed_seconds": Date().timeIntervalSince(started), "page_loads": model.pageLoads, "pages": pages, "flows": flows, "chart_captures": chartCaptures, "errors": errors]
            if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]) { try? data.write(to: partial, options: .atomic) }
            FileHandle.standardOutput.write(Data("[native-smoke] \(phase) elapsed=\(Date().timeIntervalSince(started)) loads=\(model.pageLoads)\n".utf8))
        }
        do {
            guard ProcessInfo.processInfo.environment["VANTAGE_BACKEND_URL"] != nil else { throw APIError.http(400, "Smoke mode requires VANTAGE_BACKEND_URL pointing to the isolated fixture server.") }
            guard model.connected, model.onboarding?.completed == true else { throw APIError.http(503, model.error ?? "Backend or onboarding is not ready.") }
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: snapshots, withIntermediateDirectories: true)
            for page in AppPage.allCases {
                let id = page == .plan ? "action-plan" : page == .expenses ? "finance" : page.rawValue
                checkpoint("navigate/" + id)
                model.pageLoads.removeValue(forKey: page.rawValue)
                model.page = page
                // Reload the actual window's detail view, including the first
                // already-selected page. This is not an offscreen replacement.
                model.pageReloadID = UUID()
                let deadline = Date().addingTimeInterval(15)
                checkpoint("load/" + id + "/start")
                while model.pageLoads[page.rawValue] == nil, Date() < deadline { try await Task.sleep(for: .milliseconds(100)) }
                let loaded = model.pageLoads[page.rawValue] == "loaded"
                checkpoint("load/" + id + "/end")
                guard loaded else { throw APIError.http(503, id + ": actual API-backed page did not finish loading") }
                try await Task.sleep(for: .milliseconds(250))
                guard let window = NSApp.windows.filter({ $0.isVisible && !($0 is NSPanel) }).max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) else {
                    throw APIError.http(503, "The native application window is not visible.")
                }
                checkpoint("capture/" + id + "/start")
                let data = try await captureOwnWindow(window)
                let destination = snapshots.appendingPathComponent(id + ".png")
                try data.write(to: destination)
                pages.append(["id": id, "loaded": true, "screenshot": destination.path, "capture": "ScreenCaptureKit current-process real window"])
                checkpoint("capture/" + id + "/end")
                if page == .plots {
                    let catalog: JSONValue = try await model.api.request(path: "/api/v1/plots/data")
                    for chart in catalog["charts"].array {
                        let chartID = chart["id"].string
                        guard !chartID.isEmpty else { continue }
                        // This is the actual visible Picker's binding, not an
                        // independently rendered or offscreen replacement view.
                        model.selectedPlotID = chartID
                        checkpoint("plot-picker/" + chartID)
                        try await Task.sleep(for: .milliseconds(300))
                        let safeID = String(chartID.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" ? $0 : "_" })
                        _ = scrollDetail(window, toBottom: false)
                        try await Task.sleep(for: .milliseconds(100))
                        let top = snapshots.appendingPathComponent("plot-" + safeID + "-top.png")
                        try await captureOwnWindow(window).write(to: top)
                        let kinds = Array(Set(chart["option"]["series"].array.map { $0["type"].string })).sorted()
                        chartCaptures.append(["chart_id": chartID, "series_kinds": kinds, "axes": max(1, chart["option"]["yAxis"].array.count), "viewport": "top", "visible_rect": detailViewport(window), "screenshot": top.path, "interaction": "programmatic binding action on the real visible chart Picker"])
                        if scrollDetail(window, toBottom: true) {
                            try await Task.sleep(for: .milliseconds(150))
                            let bottom = snapshots.appendingPathComponent("plot-" + safeID + "-bottom.png")
                            try await captureOwnWindow(window).write(to: bottom)
                            chartCaptures.append(["chart_id": chartID, "series_kinds": kinds, "viewport": "bottom", "visible_rect": detailViewport(window), "screenshot": bottom.path, "interaction": "scroll of the real NSScrollView document"])
                        }
                        checkpoint("plot-capture/" + chartID + "/end")
                    }
                    model.selectedPlotID = ""
                }
            }
            // The private fixture route must be present before exercising writes.
            // A normal Vantage backend does not expose it and fails closed here.
            let fixtureRequests: JSONValue = try await model.api.request(path: "/__test__/requests")
            guard case .array = fixtureRequests else { throw APIError.http(400, "Flow smoke requires the isolated synthetic fixture server.") }
            func record(_ id: String, _ passed: Bool) {
                flows.append(["id": id, "passed": passed, "interaction": "native-view-model action; not simulated mouse input"])
                if !passed { errors.append("Flow failed: " + id) }
            }
            for mode in ["success", "disconnect", "truncated", "failed", "cancelled"] {
                checkpoint("flow/action-plan-" + mode + "/start")
                let _: JSONValue = try await model.api.request(path: "/__test__/reset", method: "POST", body: .object(["job_mode": .string(mode)]))
                model.page = .plan
                await model.generate(replace: false)
                if mode == "cancelled" { await model.cancelJob() }
                let deadline = Date().addingTimeInterval(20)
                while !model.observationSettled, Date() < deadline {
                    try await Task.sleep(for: .milliseconds(100))
                }
                let expected: JobStatus = mode == "failed" ? .failed : mode == "cancelled" ? .cancelled : .succeeded
                record("action-plan-" + mode, model.observationSettled && model.job?.status == expected && (expected != .succeeded || (model.plan?.isComplete == true && model.verifiedResultJobID == model.job?.id)))
                checkpoint("flow/action-plan-" + mode + "/end")
                if !errors.isEmpty { throw APIError.http(503, "Action-plan flow failed; see partial report.") }
            }
            checkpoint("flow/chat/start")
            model.page = .chat
            try await model.refreshChat()
            let before = model.chat?.messages.count ?? 0
            model.draft = "Synthetic native smoke message"
            model.sendChat()
            let chatDeadline = Date().addingTimeInterval(20)
            while model.sendingChat, Date() < chatDeadline { try await Task.sleep(for: .milliseconds(100)) }
            record("chat-stream", !model.sendingChat && (model.chat?.messages.count ?? 0) > before && model.chatStream.failure == nil)
            try await model.clearChat()
            record("chat-reset", model.chat?.messages == (model.chat?.display_messages ?? []))
            model.page = .settings
            try await model.saveSettings(.object(["theme_mode": .string("light"), "action_plan_check_interval_minutes": .number(5)]))
            record("settings-save-readback", model.state?.settings.theme_mode == "light" && model.state?.settings.action_plan_check_interval_minutes == 5)
            try await model.completeOnboarding(.object(["skip_chat_setup": .bool(true), "display_language": .string("en-US")]))
            record("onboarding-complete", model.onboarding?.completed == true)
            if let error = model.error { errors.append(error) }
        } catch { errors.append(SensitiveText.redact(error.localizedDescription)); checkpoint("failed") }
        checkpoint(errors.isEmpty ? "completed" : "failed")
        let result: [String: Any] = ["success": errors.isEmpty, "pages": pages, "flows": flows, "chart_captures": chartCaptures, "errors": errors, "renderer": "SwiftUI/AppKit", "synthetic_data": true]
        do { try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: target) }
        catch { fputs("Could not write native smoke report\n", stderr) }
        model.shutdown()
        exit(errors.isEmpty ? 0 : 1)
    }
    private static func detailScroll(_ window: NSWindow) -> NSScrollView? {
        func descendants(_ view: NSView) -> [NSScrollView] {
            (view as? NSScrollView).map { [$0] } ?? view.subviews.flatMap(descendants)
        }
        guard let content = window.contentView else { return nil }
        return descendants(content).filter { $0.frame.width > content.frame.width * 0.4 && $0.documentView != nil }.max { $0.frame.width < $1.frame.width }
    }
    private static func scrollDetail(_ window: NSWindow, toBottom: Bool) -> Bool {
        guard let scroll = detailScroll(window), let document = scroll.documentView else { return false }
        let overflow = max(0, document.bounds.height - scroll.contentSize.height)
        guard overflow > 2 else { return false }
        let y = (toBottom == document.isFlipped) ? overflow : 0
        scroll.contentView.scroll(to: NSPoint(x: 0, y: y)); scroll.reflectScrolledClipView(scroll.contentView)
        return true
    }
    private static func detailViewport(_ window: NSWindow) -> [String: Double] {
        guard let scroll = detailScroll(window) else { return [:] }
        let visible = scroll.documentVisibleRect
        return ["x": Double(visible.minX), "y": Double(visible.minY), "width": Double(visible.width), "height": Double(visible.height), "document_height": Double(scroll.documentView?.bounds.height ?? 0)]
    }
    private static func captureOwnWindow(_ window: NSWindow) async throws -> Data {
        guard #available(macOS 14.4, *) else { throw APIError.http(503, "Permission-free own-window smoke capture requires macOS 14.4 or later.") }
        let content: SCShareableContent = try await withCheckedThrowingContinuation { continuation in
            let gate = SmokeContinuation(continuation)
            SCShareableContent.getCurrentProcessShareableContent { content, error in
                if let content { gate.finish(.success(content)) }
                else { gate.finish(.failure(error ?? APIError.http(503, "Own-window content is unavailable."))) }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + 10) { gate.finish(.failure(APIError.http(504, "Own-window discovery timed out."))) }
        }
        guard let own = content.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) && $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier }) else {
            throw APIError.http(503, "The app's window is not available from current-process capture.")
        }
        let filter = SCContentFilter(desktopIndependentWindow: own)
        let configuration = SCStreamConfiguration()
        configuration.width = max(1, Int(own.frame.width * window.backingScaleFactor))
        configuration.height = max(1, Int(own.frame.height * window.backingScaleFactor))
        configuration.showsCursor = false
        let captured: CGImage = try await withCheckedThrowingContinuation { continuation in
            let gate = SmokeContinuation(continuation)
            SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) { image, error in
                if let image { gate.finish(.success(image)) }
                else { gate.finish(.failure(error ?? APIError.http(503, "Own-window capture returned no pixels."))) }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + 10) { gate.finish(.failure(APIError.http(504, "Own-window screenshot timed out."))) }
        }
        guard let data = NSBitmapImageRep(cgImage: captured).representation(using: .png, properties: [:]) else { throw APIError.http(503, "Window PNG encoding failed.") }
        return data
    }

}

private final class SmokeContinuation<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Error>?
    init(_ continuation: CheckedContinuation<Value, Error>) { self.continuation = continuation }
    func finish(_ result: Result<Value, Error>) {
        lock.lock(); let pending = continuation; continuation = nil; lock.unlock()
        pending?.resume(with: result)
    }
}
