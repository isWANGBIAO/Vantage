import AppKit
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
        let snapshots = target.deletingPathExtension().appendingPathExtension("screenshots")
        do {
            guard ProcessInfo.processInfo.environment["VANTAGE_BACKEND_URL"] != nil else { throw APIError.http(400, "Smoke mode requires VANTAGE_BACKEND_URL pointing to the isolated fixture server.") }
            guard model.connected, model.onboarding?.completed == true else { throw APIError.http(503, model.error ?? "Backend or onboarding is not ready.") }
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: snapshots, withIntermediateDirectories: true)
            for page in AppPage.allCases {
                model.pageLoads.removeValue(forKey: page.rawValue)
                model.page = page
                let deadline = Date().addingTimeInterval(30)
                while model.pageLoads[page.rawValue] == nil, Date() < deadline { try await Task.sleep(for: .milliseconds(100)) }
                let loaded = model.pageLoads[page.rawValue] == "loaded"
                let id = page == .plan ? "action-plan" : page == .expenses ? "finance" : page.rawValue
                try await Task.sleep(for: .milliseconds(350))
                var screenshot = ""
                if let window = NSApp.windows.filter({ $0.isVisible && !($0 is NSPanel) }).max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }), let view = window.contentView {
                    view.layoutSubtreeIfNeeded()
                    if let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                        view.cacheDisplay(in: view.bounds, to: bitmap)
                        if let data = bitmap.representation(using: .png, properties: [:]) {
                            let url = snapshots.appendingPathComponent("\(id).png"); try data.write(to: url); screenshot = url.path
                        }
                    }
                }
                if !loaded { errors.append("\(id): API-backed page did not finish loading") }
                if screenshot.isEmpty { errors.append("\(id): native window snapshot unavailable") }
                pages.append(["id": id, "loaded": loaded, "screenshot": screenshot])
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
            }
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
        } catch { errors.append(SensitiveText.redact(error.localizedDescription)) }
        let result: [String: Any] = ["success": errors.isEmpty, "pages": pages, "flows": flows, "errors": errors, "renderer": "SwiftUI/AppKit", "synthetic_data": true]
        do { try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: target) }
        catch { fputs("Could not write native smoke report\n", stderr) }
        model.shutdown()
        exit(errors.isEmpty ? 0 : 1)
    }
}
