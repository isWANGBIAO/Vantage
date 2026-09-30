import AppKit
import AVFoundation
import ServiceManagement
import VantageCore

@MainActor
final class BackendHost {
    private var process: Process?
    var ownsBackend: Bool { process?.isRunning == true }
    func connect(api: APIClient) async throws {
        let probeConfiguration = URLSessionConfiguration.ephemeral
        probeConfiguration.timeoutIntervalForRequest = 1
        probeConfiguration.timeoutIntervalForResource = 2
        let probe = APIClient(address: api.address, configuration: probeConfiguration)
        do {
            let capabilities: Capabilities = try await probe.request(path: "/api/v1/capabilities")
            try capabilities.validate(); return
        } catch let error as URLError where [.cannotConnectToHost, .networkConnectionLost].contains(error.code) {
            // Only an unreachable listener may cause launch. A different service,
            // authentication error or incompatible API must never be replaced.
        }
        guard api.address.canLaunch else { throw APIError.disconnected }
        if process?.isRunning != true {
            let environment = ProcessInfo.processInfo.environment
            let runtime = Bundle.main.resourceURL?.appendingPathComponent("backend-runtime/VantageBackend/VantageBackend")
            let process = Process()
            if let runtime, FileManager.default.isExecutableFile(atPath: runtime.path) {
                process.executableURL = runtime
                process.currentDirectoryURL = runtime.deletingLastPathComponent()
            } else if let python = environment["VANTAGE_PYTHON"], let root = environment["VANTAGE_PROJECT_ROOT"] {
                process.executableURL = URL(fileURLWithPath: python)
                process.arguments = ["-m", "src.scripts.run_server_background"]
                process.currentDirectoryURL = URL(fileURLWithPath: root)
            } else { throw APIError.http(503, "Bundled backend is missing. Build with scripts/package.sh --backend-runtime, or set VANTAGE_PYTHON and VANTAGE_PROJECT_ROOT for development.") }
            var env = environment
            env["VANTAGE_BACKEND_URL"] = api.address.url.absoluteString
            env["VANTAGE_APP_MODE"] = "packaged"
            // Packaged data defaults to ~/Library/Application Support/Vantage, never this checkout.
            process.environment = env; process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
            try process.run(); self.process = process
        }
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline {
            try Task.checkCancellation()
            if let caps: Capabilities = try? await probe.request(path: "/api/v1/capabilities") {
                try caps.validate(); let _: JSONValue = try await probe.request(path: "/api/v1/system/status"); return
            }
            if process?.isRunning == false { throw APIError.http(503, "Backend exited during startup. See the Vantage logs folder.") }
            try await Task.sleep(for: .milliseconds(500))
        }
        shutdown(); throw APIError.disconnected
    }
    func shutdown() {
        guard let owned = process else { return }; process = nil
        if owned.isRunning { owned.terminate() }
        // Quit must not let a detached cleanup task die with the app. Bound the
        // grace period, then reap the exact child process this host owns.
        let deadline = Date().addingTimeInterval(3)
        while owned.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
        if owned.isRunning { kill(owned.processIdentifier, SIGKILL) }
        owned.waitUntilExit()
    }
}

@MainActor
enum NativePlatform {
    static func openFolder(_ path: String) throws {
        let url = URL(fileURLWithPath: path, isDirectory: true)
        guard FileManager.default.fileExists(atPath: url.path), NSWorkspace.shared.open(url) else { throw APIError.http(404, "Folder is unavailable.") }
    }
    static func chooseFolder() -> String? {
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.allowsMultipleSelection = false
        return panel.runModal() == .OK ? panel.url?.path : nil
    }
    static func copy(_ text: String) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string) }
    static func setLogin(_ enabled: Bool) throws {
        if enabled && SMAppService.mainApp.status != .enabled { try SMAppService.mainApp.register() }
        if !enabled && SMAppService.mainApp.status != .notRegistered { try SMAppService.mainApp.unregister() }
    }
    static var loginStatus: String {
        switch SMAppService.mainApp.status {
        case .enabled: return "Enabled"
        case .requiresApproval: return "Approval required in System Settings → General → Login Items"
        case .notFound: return "Install Vantage.app in Applications first"
        case .notRegistered: return "Disabled"
        @unknown default: return "Unknown"
        }
    }
    static func privacySettings(_ pane: String) {
        guard ["Camera", "Microphone", "ScreenCapture"].contains(pane), let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_\(pane)") else { return }
        NSWorkspace.shared.open(url)
    }
    static func applyTheme(_ mode: String) {
        NSApp.appearance = mode == "dark" ? NSAppearance(named: .darkAqua) : mode == "light" ? NSAppearance(named: .aqua) : nil
    }
    static func save(_ data: Data, filename: String) throws {
        let panel = NSSavePanel(); panel.nameFieldStringValue = filename
        guard panel.runModal() == .OK, let url = panel.url else { return }
        try data.write(to: url, options: .atomic)
    }
}

/// App-owned AVFoundation capture gives macOS a stable bundle identity for TCC.
/// Only one upload is in flight; frames never queue without bounds.
final class CameraBridge: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "app.vantage.camera")
    private let api: APIClient
    private var uploading = false
    private var lastFrame = Date.distantPast
    private let intentLock = NSLock()
    private var intent = UUID()
    private func newIntent() -> UUID { intentLock.lock(); defer { intentLock.unlock() }; intent = UUID(); return intent }
    private func current(_ value: UUID) -> Bool { intentLock.lock(); defer { intentLock.unlock() }; return intent == value }
    private let context = CIContext()
    init(api: APIClient) { self.api = api; super.init() }
    func start() async throws {
        let intent = newIntent()
        var allowed = AVCaptureDevice.authorizationStatus(for: .video) == .authorized
        if !allowed { allowed = await AVCaptureDevice.requestAccess(for: .video) }
        guard current(intent), !Task.isCancelled else { throw CancellationError() }
        guard allowed else { throw APIError.http(403, "Enable camera access in System Settings → Privacy & Security → Camera.") }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                do {
                    guard self.current(intent) else { throw CancellationError() }
                    if self.session.isRunning { continuation.resume(); return }
                    if self.session.inputs.isEmpty {
                        guard let device = AVCaptureDevice.default(for: .video) else { throw APIError.http(404, "No camera is available.") }
                        let input = try AVCaptureDeviceInput(device: device)
                        guard self.session.canAddInput(input) else { throw APIError.http(503, "Camera cannot be opened.") }
                        self.session.beginConfiguration(); self.session.sessionPreset = .medium; self.session.addInput(input)
                        let output = AVCaptureVideoDataOutput(); output.alwaysDiscardsLateVideoFrames = true
                        output.setSampleBufferDelegate(self, queue: self.queue)
                        if self.session.canAddOutput(output) { self.session.addOutput(output) }
                        self.session.commitConfiguration()
                    }
                    self.session.startRunning(); continuation.resume()
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
    func stop() { _ = newIntent(); queue.async { self.session.stopRunning() } }
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard !uploading, Date().timeIntervalSince(lastFrame) >= 0.2, let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cg = context.createCGImage(image, from: image.extent),
              let data = NSBitmapImageRep(cgImage: cg).representation(using: .jpeg, properties: [.compressionFactor: 0.7]) else { return }
        uploading = true; lastFrame = Date()
        Task {
            try? await api.sendCameraFrame(data)
            queue.async { self.uploading = false }
        }
    }
}

@MainActor
final class VoiceRecorder: ObservableObject {
    @Published var recording = false
    private var recorder: AVAudioRecorder?
    private var file: URL?
    private var intent = UUID()
    func start() async throws {
        let request = UUID(); intent = request
        let allowed = await AVCaptureDevice.requestAccess(for: .audio)
        guard intent == request, !Task.isCancelled else { throw CancellationError() }
        guard allowed else { throw APIError.http(403, "Enable microphone access in System Settings.") }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("vantage-voice-\(UUID().uuidString).m4a")
        let recorder = try AVAudioRecorder(url: file, settings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 24000, AVNumberOfChannelsKey: 1, AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue])
        guard recorder.record() else { throw APIError.http(503, "Microphone recording could not start.") }
        self.file = file; self.recorder = recorder; recording = true
    }
    func stop() -> URL? { intent = UUID(); recorder?.stop(); recorder = nil; recording = false; return file }
    func discard() { _ = stop(); if let file { try? FileManager.default.removeItem(at: file) }; file = nil }
}
