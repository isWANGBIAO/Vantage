import SwiftUI
import VantageCore

@MainActor
final class AppModel: ObservableObject {
    @Published var api: APIClient
    @Published var connected = false
    @Published var connecting = false
    @Published var error: String?
    @Published var state: SettingsState?
    @Published var onboarding: OnboardingState?
    @Published var page: AppPage? = .dashboard
    @Published var pageReloadID = UUID()
    @Published var selectedPlotID = ""
    @Published var models: [ModelOption] = []
    @Published var selectedModel = ""
    @Published var reasoning = "high"
    @Published var tier = ""
    @Published var plan: PlanResult?
    @Published var creatingPlan = false
    @Published var job: ActionPlanJob?
    @Published var planStream = PlanStreamState()
    @Published var planConnection = ""
    @Published var observationSettled = true
    @Published var verifiedResultJobID: String?
    @Published var chat: ChatContext?
    @Published var chatStream = ChatStreamState()
    @Published var sendingChat = false
    @Published var chatReady = false
    @Published var draft = ""
    @Published var failedChatDraft: String?
    @Published var pageLoads: [String: String] = [:]
    let host = BackendHost()
    private var startupError: Error?
    private var observation: Task<Void, Never>?
    private var chatTask: Task<Void, Never>?
    private var monitor: Task<Void, Never>?
    private(set) var camera: CameraBridge
    private var generation = UUID()
    private var connectionID = UUID()
    var selectedOption: ModelOption? { models.first { $0.id == selectedModel } }
    var chinese: Bool { state?.settings.display_language == "zh-CN" || (state?.settings.display_language != "en-US" && Locale.preferredLanguages.first?.hasPrefix("zh") == true) }
    func text(_ zh: String, _ en: String) -> String { chinese ? zh : en }
    init() {
        let address: BackendAddress
        do { address = try .resolve() } catch { startupError = error; address = try! BackendAddress("http://127.0.0.1:8000") }
        let client = APIClient(address: address); api = client; camera = CameraBridge(api: client)
    }
    func report(_ error: Error) {
        if error is CancellationError || (error as NSError).code == NSURLErrorCancelled { return }
        self.error = SensitiveText.redact(error.localizedDescription)
    }
    func connect() async {
        guard !connecting else { return }
        let epoch = connectionID; let client = api
        connecting = true; defer { if connectionID == epoch { connecting = false } }
        do {
            if let startupError { throw startupError }
            try await host.connect(api: client)
            guard connectionID == epoch else { return }
            let caps: Capabilities = try await client.request(path: "/api/v1/capabilities"); try caps.validate()
            let _: JSONValue = try await client.request(path: "/api/v1/operations")
            guard connectionID == epoch else { return }
            try await refreshSettings()
            let onboarding: OnboardingState = try await client.request(path: "/api/v1/onboarding")
            guard connectionID == epoch else { return }; self.onboarding = onboarding
            try await refreshModels()
            guard connectionID == epoch else { return }
            connected = true; error = nil
            if let enabled = state?.settings.launch_at_login, !ProcessInfo.processInfo.arguments.contains("--smoke-test") {
                do { try NativePlatform.setLogin(enabled) } catch { self.error = "Settings are saved, but macOS login startup could not be applied: " + error.localizedDescription }
            }
            if onboarding.completed { await refreshPlanAndJobs(); try await refreshChat() }
            monitor?.cancel()
            monitor = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(10))
                    guard !Task.isCancelled, let self else { return }
                    do {
                        let _: JSONValue = try await client.request(path: "/api/v1/system/status")
                        guard self.connectionID == epoch, !Task.isCancelled else { return }
                        self.connected = true
                        if self.job?.status.terminal != false { await self.refreshPlanAndJobs() }
                    } catch { if self.connectionID == epoch { self.connected = false } }
                }
            }
        } catch { if connectionID == epoch { report(error) } }
    }
    func reconnect(address: String) async {
        do {
            let replacement = APIClient(address: try BackendAddress(address))
            shutdown(); api = replacement; camera = CameraBridge(api: replacement); startupError = nil
            await connect()
        } catch { report(error) }
    }
    func refreshSettings() async throws {
        let epoch = connectionID; let client = api
        let result: SettingsState = try await client.request(path: "/api/v1/settings")
        guard connectionID == epoch else { throw CancellationError() }
        state = result; NativePlatform.applyTheme(result.settings.theme_mode)
    }
    func saveSettings(_ payload: JSONValue) async throws {
        let epoch = connectionID; let client = api
        let _: SettingsState = try await client.request(path: "/api/v1/settings", method: "PUT", body: payload)
        guard connectionID == epoch else { throw CancellationError() }
        try await refreshSettings()
        guard connectionID == epoch else { throw CancellationError() }
        if let enabled = payload["launch_at_login"].bool {
            do { try NativePlatform.setLogin(enabled) } catch { throw APIError.http(409, "Settings were saved, but macOS login startup could not be applied. " + error.localizedDescription) }
        }
        try await refreshModels()
    }
    func completeOnboarding(_ body: JSONValue) async throws {
        let epoch = connectionID; let client = api
        let _: JSONValue = try await client.request(path: "/api/v1/onboarding/complete", method: "POST", body: body)
        guard connectionID == epoch else { throw CancellationError() }
        try await refreshSettings()
        let result: OnboardingState = try await client.request(path: "/api/v1/onboarding")
        guard connectionID == epoch else { throw CancellationError() }; onboarding = result
        if let enabled = body["launch_at_login"].bool { try NativePlatform.setLogin(enabled) }
        try await refreshModels(); await refreshPlanAndJobs(); try await refreshChat()
    }
    func refreshModels() async throws {
        let epoch = connectionID; let client = api
        let result: ModelCatalog = try await client.request(path: "/api/v1/models")
        guard connectionID == epoch else { throw CancellationError() }
        models = result.model_options ?? []
        if !models.contains(where: { $0.id == selectedModel }) { selectedModel = models.first(where: { $0.is_default == true })?.id ?? models.first?.id ?? "" }
    }
    func refreshPlanAndJobs() async {
        let epoch = connectionID; let client = api
        do {
            let saved: PlanResult = try await client.request(path: "/api/v1/action-plan/today")
            let result: JobList = try await client.request(path: "/api/v1/action-plan/jobs")
            guard connectionID == epoch, !Task.isCancelled else { return }; plan = saved
            if let active = result.active { if job?.id != active.id || observation == nil { observe(active) } }
            else if job?.status.terminal == false && observation == nil {
                // A read begun before create must not cancel a newer observer.
                job = result.jobs.first
                planConnection = text("后端任务已结束或已重启；已重新读取保存结果", "Job ended or backend restarted; saved result reloaded")
            }
            pageLoads[AppPage.plan.rawValue] = "loaded"
        } catch { if connectionID == epoch { report(error); pageLoads[AppPage.plan.rawValue] = "error" } }
    }
    func generate(replace: Bool) async {
        guard !creatingPlan else { return }
        let epoch = connectionID; let client = api
        creatingPlan = true; defer { if connectionID == epoch { creatingPlan = false } }
        do {
            var request = ActionPlanRequest(); request.model = selectedOption?.model; request.provider_route = selectedOption?.provider_route
            request.reasoning_effort = reasoning.isEmpty ? nil : reasoning; request.service_tier = tier.isEmpty ? nil : tier
            request.replace_today = replace
            let result: ActionPlanJob = try await client.request(path: "/api/v1/action-plan/jobs", method: "POST", body: try .encode(request))
            guard connectionID == epoch else { return }; observe(result)
        } catch { report(error) }
    }
    func cancelJob() async {
        guard let job, !job.status.terminal else { return }
        let epoch = connectionID; let client = api
        do {
            let result: ActionPlanJob = try await client.request(path: "/api/v1/action-plan/jobs/\(job.id)/cancel", method: "POST")
            guard connectionID == epoch else { return }; self.job = result
        } catch { if connectionID == epoch { report(error) } }
    }
    private func observe(_ initial: ActionPlanJob) {
        observation?.cancel(); job = initial; planStream = PlanStreamState(); planConnection = ""
        observationSettled = false; verifiedResultJobID = nil
        let identity = UUID(); generation = identity
        let client = api
        observation = Task { [weak self] in
            guard let self else { return }
            var delay = 1
            while !Task.isCancelled, self.generation == identity {
                do {
                    let snapshot: ActionPlanJob = try await client.request(path: "/api/v1/action-plan/jobs/\(initial.id)")
                    guard self.generation == identity, !Task.isCancelled else { break }
                    self.job = snapshot
                    if snapshot.status.terminal {
                        if snapshot.status == .succeeded {
                            guard snapshot.error == nil, snapshot.result?.isComplete == true else {
                                self.planConnection = APIError.incompleteStream.localizedDescription; break
                            }
                            let saved: PlanResult = try await client.request(path: "/api/v1/action-plan/today")
                            guard self.generation == identity, !Task.isCancelled else { break }
                            guard saved.isComplete, saved.date == snapshot.result?.date, saved.filename == snapshot.result?.filename else {
                                self.plan = saved; self.planConnection = self.text("保存结果已变化，已重新读取当前计划", "Saved result changed; current plan reloaded"); break
                            }
                            self.plan = saved; self.planConnection = self.text("已保存完整计划", "Complete plan saved")
                            try await self.refreshChat()
                            guard self.generation == identity else { break }
                            self.verifiedResultJobID = snapshot.id
                        } else { self.planConnection = snapshot.error?.message ?? snapshot.status.rawValue }
                        break
                    }
                    self.planConnection = self.text("正在接收进度", "Receiving progress")
                    try await client.stream(path: "/api/v1/action-plan/jobs/\(initial.id)/events", query: ["after": String(self.planStream.cursor)]) { [weak self] event in
                        if let receiver = self { await receiver.receivePlanEvent(event, identity: identity) }
                    }
                    delay = 1
                    // Always reread authoritative state; neither EOF nor partial text proves success.
                } catch {
                    if Task.isCancelled { break }
                    if case APIError.http(404, _) = error {
                        self.job = nil; await self.refreshPlanAndJobs(); break
                    }
                    self.planConnection = self.text("连接中断，正在重连", "Connection interrupted; reconnecting") + " (\(delay)s)"
                    try? await Task.sleep(for: .seconds(delay)); delay = min(delay * 2, 15)
                }
            }
            if self.generation == identity { self.observation = nil; self.observationSettled = true }
        }
    }
    private func receivePlanEvent(_ event: StreamEvent, identity: UUID) {
        guard generation == identity else { return }; planStream.apply(event)
    }
    private func receiveChatEvent(_ event: StreamEvent, epoch: UUID) {
        guard connectionID == epoch else { return }; chatStream.apply(event)
    }
    func refreshChat() async throws {
        chatReady = false
        let epoch = connectionID; let client = api
        let snapshot: ChatContext = try await client.request(path: "/api/v1/chat/context")
        guard connectionID == epoch else { throw CancellationError() }
        if chat == nil || chat?.base_context_version != snapshot.base_context_version {
            if let preferred = snapshot.preferred_model_option_id, models.contains(where: { $0.id == preferred }) { selectedModel = preferred }
        }
        chat = snapshot; chatReady = true
        pageLoads[AppPage.chat.rawValue] = "loaded"
    }
    func clearChat() async throws {
        guard !sendingChat else { return }
        let epoch = connectionID; let client = api
        let result: ChatContext = try await client.request(path: "/api/v1/chat/context", method: "DELETE")
        guard connectionID == epoch else { throw CancellationError() }
        chat = result; chatStream = ChatStreamState(); failedChatDraft = nil
    }
    func sendChat() {
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !sendingChat, chatReady else { return }
        let submittedDraft = draft
        let beforeVersion = chat?.context_version
        let request = ChatRequest(message: message, option: selectedOption, reasoning: reasoning.isEmpty ? nil : reasoning, tier: tier.isEmpty ? nil : tier)
        sendingChat = true; chatStream = ChatStreamState(); draft = ""
        let epoch = connectionID; let client = api
        chatTask = Task { [weak self] in
            guard let self else { return }; defer { if self.connectionID == epoch { self.sendingChat = false; self.chatTask = nil } }
            do {
                try await client.stream(path: "/api/v1/chat", method: "POST", body: try .encode(request)) { [weak self] event in
                    if let receiver = self { await receiver.receiveChatEvent(event, epoch: epoch) }
                }
                guard self.connectionID == epoch else { return }
                try Task.checkCancellation()
                if let failure = self.chatStream.failure { throw APIError.http(502, failure) }
                guard self.chatStream.done else { throw APIError.incompleteStream }
                try await self.refreshChat(); self.chatStream = ChatStreamState()
            } catch {
                guard self.connectionID == epoch else { return }
                self.report(error)
                var verifiedVersion: String?
                do { try await self.refreshChat(); verifiedVersion = self.chat?.context_version } catch { }
                guard self.connectionID == epoch else { return }
                let recovery = ChatDraftRecovery.recover(submitted: submittedDraft, currentDraft: self.draft, beforeVersion: beforeVersion, afterVersion: verifiedVersion)
                self.draft = recovery.draft; self.failedChatDraft = recovery.retainedCopy
            }
        }
    }
    func stopChat() { chatTask?.cancel() }
    func shutdown() {
        connectionID = UUID(); generation = UUID()
        monitor?.cancel(); observation?.cancel(); chatTask?.cancel()
        monitor = nil; observation = nil; chatTask = nil
        camera.stop(); host.shutdown(); connecting = false; connected = false; sendingChat = false; chatReady = false; creatingPlan = false
        chat = nil; state = nil; onboarding = nil; plan = nil; job = nil; observationSettled = true; verifiedResultJobID = nil
    }
}

enum AppPage: String, CaseIterable, Identifiable {
    case dashboard, plan, chat, projects, expenses, plots, face, usage, logs, settings
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .dashboard: return "square.grid.2x2"; case .plan: return "checklist"; case .chat: return "bubble.left.and.bubble.right"
        case .projects: return "target"; case .expenses: return "banknote"; case .plots: return "chart.xyaxis.line"
        case .face: return "person.crop.rectangle"; case .usage: return "gauge.with.dots.needle.67percent"; case .logs: return "terminal"; case .settings: return "gearshape"
        }
    }
    @MainActor func title(_ model: AppModel) -> String {
        switch self {
        case .dashboard: return model.text("仪表盘", "Dashboard"); case .plan: return model.text("行动计划", "Action plan")
        case .chat: return model.text("对话", "Chat"); case .projects: return model.text("项目进度", "Projects")
        case .expenses: return model.text("资产与支出", "Finances"); case .plots: return model.text("趋势图表", "Trends")
        case .face: return model.text("面部历史", "Face history"); case .usage: return model.text("模型用量", "Usage")
        case .logs: return model.text("系统日志", "System logs"); case .settings: return model.text("设置", "Settings")
        }
    }
}
