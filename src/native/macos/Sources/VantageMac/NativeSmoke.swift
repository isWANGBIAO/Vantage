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
                if let window = NSApp.windows.first(where: { $0.title == "Vantage" }), let view = window.contentView {
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
            if let error = model.error { errors.append(error) }
        } catch { errors.append(SensitiveText.redact(error.localizedDescription)) }
        let result: [String: Any] = ["success": errors.isEmpty, "pages": pages, "errors": errors, "renderer": "SwiftUI/AppKit", "synthetic_data": true]
        do { try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: target) }
        catch { fputs("Could not write native smoke report\n", stderr) }
        model.shutdown()
        exit(errors.isEmpty ? 0 : 1)
    }
}
