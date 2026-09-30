import SwiftUI
import AVFoundation
import CoreGraphics
import ServiceManagement
import VantageCore

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var draft: SettingsState?
    @State private var providerRoute = ""
    @State private var newRoute = ""
    @State private var providerKeys: [String: String] = [:]
    @State private var clearKeys: Set<String> = []
    @State private var voiceKey = ""
    @State private var imageKey = ""
    @State private var clearVoice = false
    @State private var clearImage = false
    @State private var profiles = "{}"
    @State private var sampling = "{}"
    @State private var saving = false
    @State private var saved = false
    @State private var removeProvider = false
    @State private var cameraEnabled = false
    @State private var connection = ""
    var body: some View {
        Group {
            if draft != nil {
                Form {
                    generalSection
                    providerSection
                    specialSection("voice")
                    specialSection("image")
                    Section(model.text("模型参数", "Model parameters")) {
                        Text(model.text("默认采样参数（JSON）", "Sampling defaults (JSON)"))
                        TextEditor(text: $sampling).font(.system(.body, design: .monospaced)).frame(height: 90)
                        Text(model.text("按模型定义参数、推理层级、别名与输出上限（JSON）", "Per-model parameters, reasoning tiers, aliases and token limits (JSON)"))
                        TextEditor(text: $profiles).font(.system(.body, design: .monospaced)).frame(height: 140)
                    }
                    permissionsSection
                    Section(model.text("数据与日志", "Data and logs")) {
                        ForEach(["data_dir", "config_dir", "history_dir", "log_dir", "plot_dir", "cache_dir", "runtime_dir"], id: \.self) { key in
                            LabeledContent(key) {
                                Text(draft?.runtime_paths[key] ?? "").font(.caption).textSelection(.enabled)
                                Button(model.text("打开", "Open")) { do { try NativePlatform.openFolder(draft?.runtime_paths[key] ?? "") } catch { model.report(error) } }
                            }
                        }
                    }
                    Section(model.text("后端连接", "Backend connection")) {
                        TextField("Loopback URL", text: $connection)
                        Button(model.text("连接此地址", "Connect to this address")) { Task { await model.reconnect(address: connection); reload() } }
                        Text(model.text("仅接受本机 HTTP(S) 地址。HTTPS 或路径前缀代理须先单独启动后端", "Only loopback HTTP(S) is accepted. HTTPS/path-prefix proxies must already be running.")).font(.caption).foregroundStyle(.secondary)
                    }
                    HStack {
                        Button(model.text("重新读取", "Reload")) { Task { do { try await model.refreshSettings(); reload() } catch { model.report(error) } } }
                        Spacer()
                        if saved { Label(model.text("已保存并验证", "Saved and verified"), systemImage: "checkmark.circle").foregroundStyle(.green) }
                        Button(model.text("保存所有更改", "Save changes")) { Task { await save() } }.buttonStyle(.borderedProminent).disabled(saving)
                    }
                }.formStyle(.grouped).disabled(saving)
            } else { ProgressView() }
        }.task { reload(); model.pageLoads[AppPage.settings.rawValue] = "loaded" }
        .confirmationDialog(model.text("删除此提供商？", "Remove this provider?"), isPresented: $removeProvider) {
            Button(model.text("删除", "Remove"), role: .destructive) { draft?.provider.providers.removeValue(forKey: providerRoute); providerRoute = draft?.provider.providers.keys.sorted().first ?? "" }
        }
    }
    private var generalSection: some View {
        Section(model.text("通用", "General")) {
            Picker(model.text("显示语言", "Language"), selection: settings(\.display_language, "system")) {
                Text(model.text("跟随系统", "System")).tag("system"); Text("简体中文").tag("zh-CN"); Text("English").tag("en-US")
            }
            LabeledContent(model.text("系统区域", "System locale"), value: Locale.current.identifier)
            Picker(model.text("外观", "Appearance"), selection: settings(\.theme_mode, "auto")) {
                Text(model.text("自动", "Automatic")).tag("auto"); Text(model.text("浅色", "Light")).tag("light"); Text(model.text("深色", "Dark")).tag("dark")
            }
            Toggle(model.text("登录时启动", "Launch at login"), isOn: settings(\.launch_at_login, false))
            LabeledContent(model.text("系统启动项状态", "Login item status"), value: NativePlatform.loginStatus)
            Button(model.text("管理登录项", "Manage login items")) { SMAppService.openSystemSettingsLoginItems() }
            Toggle(model.text("自动生成缺失的今日计划", "Automatically generate missing daily plan"), isOn: settings(\.action_plan_auto_generate, false))
            TextField(model.text("检查数据变化间隔（分钟，0 关闭）", "Source check interval (minutes, 0 disables)"), value: settings(\.action_plan_check_interval_minutes, 0), format: .number)
        }
    }
    private var providerSection: some View {
        Section(model.text("AI 提供商", "AI providers")) {
            Picker(model.text("编辑提供商", "Edit provider"), selection: $providerRoute) {
                Text("—").tag("")
                ForEach(draft?.provider.providers.keys.sorted() ?? [], id: \.self) { route in Text(draft?.provider.providers[route]?.name ?? route).tag(route) }
            }
            Picker(model.text("默认提供商", "Default provider"), selection: Binding(get: { draft?.provider.selected_provider ?? "" }, set: { draft?.provider.selected_provider = $0.isEmpty ? nil : $0 })) {
                Text("—").tag("")
                ForEach(draft?.provider.providers.keys.sorted() ?? [], id: \.self) { route in Text(route).tag(route) }
            }
            HStack {
                TextField(model.text("新提供商标识", "New provider route"), text: $newRoute)
                Button(model.text("添加", "Add")) {
                    let route = newRoute.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !route.isEmpty, draft?.provider.providers[route] == nil else { return }
                    draft?.provider.providers[route] = Provider(route: route); providerRoute = route; newRoute = ""
                }
            }
            if draft?.provider.providers[providerRoute] != nil {
                Toggle(model.text("启用", "Enabled"), isOn: provider(\.enabled, false))
                TextField(model.text("名称", "Name"), text: provider(\.name, ""))
                TextField("Base URL", text: provider(\.base_url, ""))
                SecureField(model.text("新 API key（留空保留）", "New API key (blank keeps saved key)"), text: Binding(get: { providerKeys[providerRoute] ?? "" }, set: { providerKeys[providerRoute] = $0 }))
                Toggle(model.text("清除此提供商保存的密钥", "Clear this provider's saved key"), isOn: Binding(get: { clearKeys.contains(providerRoute) }, set: { if $0 { clearKeys.insert(providerRoute) } else { clearKeys.remove(providerRoute) } }))
                Text(model.text("更改 API 地址需要重新输入密钥或明确清除。密钥只写入后端，不复制到客户端存储", "Changing the API destination requires a new key or an explicit clear. Keys are write-only and never saved in client preferences.")).font(.caption).foregroundStyle(.secondary)
                TextField(model.text("默认模型", "Default model"), text: provider(\.model, ""))
                TextField(model.text("模型列表（逗号分隔）", "Models (comma-separated)"), text: Binding(get: { draft?.provider.providers[providerRoute]?.models.joined(separator: ", ") ?? "" }, set: { draft?.provider.providers[providerRoute]?.models = split($0) }))
                HStack {
                    Button(model.text("发现模型", "Discover models")) { Task { await discoverProvider() } }
                    Button(model.text("删除提供商", "Remove provider"), role: .destructive) { removeProvider = true }
                }
                TextField(model.text("上下文窗口 token 上限（可留空）", "Context window tokens (optional)"), text: optionalInt(\.context_window_tokens))
                TextField(model.text("最大输出 token（可留空）", "Maximum output tokens (optional)"), text: optionalInt(\.max_output_tokens))
            }
        }
    }
    @ViewBuilder private func specialSection(_ kind: String) -> some View {
        let voice = kind == "voice"
        Section(voice ? model.text("语音转录", "Voice transcription") : model.text("图像模型", "Image model")) {
            Picker(model.text("提供商设置", "Provider configuration"), selection: settings(voice ? \.voice_provider_mode : \.image_provider_mode, "inherit_ai")) {
                Text(model.text("继承 AI 提供商", "Inherit AI provider")).tag("inherit_ai"); Text(model.text("自定义", "Custom")).tag("custom")
            }
            TextField("Base URL", text: settings(voice ? \.voice_base_url : \.image_base_url, ""))
            SecureField(model.text("新 API key（留空保留）", "New API key (blank keeps saved key)"), text: voice ? $voiceKey : $imageKey)
            Toggle(model.text("清除已保存密钥", "Clear saved key"), isOn: voice ? $clearVoice : $clearImage)
            TextField(model.text("模型", "Model"), text: settings(voice ? \.voice_model : \.image_model, ""))
            Button(model.text("发现模型", "Discover models")) { Task { await discoverSpecial(kind) } }.disabled(voice ? clearVoice : clearImage)
            let available = voice ? draft?.settings.voice_models : draft?.settings.image_models
            if !(available ?? []).isEmpty { Text((available ?? []).joined(separator: ", ")).font(.caption).textSelection(.enabled) }
        }
    }
    private var permissionsSection: some View {
        Section(model.text("隐私与权限", "Privacy and permissions")) {
            LabeledContent(model.text("相机", "Camera"), value: String(describing: AVCaptureDevice.authorizationStatus(for: .video)))
            HStack {
                Button(cameraEnabled ? model.text("停止相机采集", "Stop camera capture") : model.text("开启相机采集", "Enable camera capture")) {
                    Task { do { if cameraEnabled { model.camera.stop(); cameraEnabled = false } else { try await model.camera.start(); cameraEnabled = true } } catch { model.report(error) } }
                }
                Button(model.text("相机权限设置", "Camera permissions")) { NativePlatform.privacySettings("Camera") }
                Button(model.text("麦克风权限设置", "Microphone permissions")) { NativePlatform.privacySettings("Microphone") }
                Button(model.text("申请录屏权限", "Request screen recording access")) { _ = CGRequestScreenCaptureAccess() }
                Button(model.text("录屏权限设置", "Screen recording permissions")) { NativePlatform.privacySettings("ScreenCapture") }
            }
            Text(model.text("照片与截图默认隐藏，打开预览才显示。录音只在按下麦克风后开始，临时文件在转录后删除", "Photos and screenshots stay hidden until revealed. Audio records only after pressing the microphone and temporary files are removed after transcription.")).font(.caption)
        }
    }
    private func settings<T>(_ key: WritableKeyPath<SettingsValues, T>, _ fallback: T) -> Binding<T> { Binding(get: { draft?.settings[keyPath: key] ?? fallback }, set: { draft?.settings[keyPath: key] = $0; saved = false }) }
    private func provider<T>(_ key: WritableKeyPath<Provider, T>, _ fallback: T) -> Binding<T> { Binding(get: { draft?.provider.providers[providerRoute]?[keyPath: key] ?? fallback }, set: { draft?.provider.providers[providerRoute]?[keyPath: key] = $0; saved = false }) }
    private func optionalInt(_ key: WritableKeyPath<Provider, Int?>) -> Binding<String> { Binding(get: { draft?.provider.providers[providerRoute]?[keyPath: key].map(String.init) ?? "" }, set: { draft?.provider.providers[providerRoute]?[keyPath: key] = Int($0) }) }
    private func split(_ value: String) -> [String] { value.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } }
    private func reload() {
        draft = model.state; providerRoute = draft?.provider.selected_provider ?? draft?.provider.providers.keys.sorted().first ?? ""
        profiles = JSONValue.object(draft?.provider.model_profiles ?? [:]).pretty; sampling = JSONValue.object(draft?.provider.sampling_defaults ?? [:]).pretty
        providerKeys = [:]; clearKeys = []; voiceKey = ""; imageKey = ""; clearVoice = false; clearImage = false; connection = model.api.address.url.absoluteString
    }
    private func save() async {
        guard var draft else { return }; saving = true; saved = false; defer { saving = false }
        do {
            guard (0...35791).contains(draft.settings.action_plan_check_interval_minutes) else { throw APIError.http(422, "Interval must be 0…35791 minutes.") }
            draft.provider.sampling_defaults = try JSONDecoder().decode([String: JSONValue].self, from: Data(sampling.utf8))
            draft.provider.model_profiles = try JSONDecoder().decode([String: JSONValue].self, from: Data(profiles.utf8))
            for route in draft.provider.providers.keys {
                if clearKeys.contains(route) { draft.provider.providers[route]?.api_key = "" }
                else if let key = providerKeys[route], !key.isEmpty { draft.provider.providers[route]?.api_key = key }
            }
            var payload = try JSONValue.encode(draft.settings).object
            for key in ["version", "onboarding_completed", "voice_has_api_key", "image_has_api_key", "voice_api_key", "image_api_key"] { payload.removeValue(forKey: key) }
            if clearVoice || !voiceKey.isEmpty { payload["voice_api_key"] = .string(clearVoice ? "" : voiceKey) }
            if clearImage || !imageKey.isEmpty { payload["image_api_key"] = .string(clearImage ? "" : imageKey) }
            payload["provider_config"] = try .encode(draft.provider)
            try await model.saveSettings(.object(payload)); reload(); saved = true
        } catch { model.report(error) }
    }
    private func discoverProvider() async {
        let route = providerRoute; let client = model.api
        guard let provider = draft?.provider.providers[route] else { return }
        do {
            var request: [String: JSONValue] = ["route": .string(route), "base_url": .string(provider.base_url), "type": .string(provider.type)]
            if let key = providerKeys[route], !key.isEmpty { request["api_key"] = .string(key) }
            if clearKeys.contains(route) { request["route"] = .string(""); request["api_key"] = .string("") }
            let result: JSONValue = try await client.request(path: "/api/v1/models/discover", method: "POST", body: .object(request))
            guard client === model.api, draft?.provider.providers[route]?.base_url == provider.base_url else { return }
            draft?.provider.providers[route]?.models = result["models"].array.map(\.string)
            draft?.provider.providers[route]?.last_refreshed_at = ISO8601DateFormatter().string(from: Date())
        } catch { model.report(error) }
    }
    private func discoverSpecial(_ kind: String) async {
        guard let settings = draft?.settings else { return }; let voice = kind == "voice"; let client = model.api
        do {
            var body: [String: JSONValue] = ["kind": .string(kind), "mode": .string(voice ? settings.voice_provider_mode : settings.image_provider_mode), "base_url": .string(voice ? settings.voice_base_url : settings.image_base_url)]
            let key = voice ? voiceKey : imageKey; if !key.isEmpty { body["api_key"] = .string(key) }
            let result: JSONValue = try await client.request(path: "/api/v1/providers/models/discover", method: "POST", body: .object(body))
            guard client === model.api,
                  (voice ? draft?.settings.voice_base_url : draft?.settings.image_base_url) == (voice ? settings.voice_base_url : settings.image_base_url),
                  (voice ? draft?.settings.voice_provider_mode : draft?.settings.image_provider_mode) == (voice ? settings.voice_provider_mode : settings.image_provider_mode) else { return }
            let values = result["models"].array.map(\.string); let timestamp = ISO8601DateFormatter().string(from: Date())
            if voice { draft?.settings.voice_models = values; draft?.settings.voice_last_refreshed_at = timestamp }
            else { draft?.settings.image_models = values; draft?.settings.image_last_refreshed_at = timestamp }
        } catch { model.report(error) }
    }
}

struct OnboardingView: View {
    @EnvironmentObject var model: AppModel
    @State private var step = 0
    @State private var language = "system"
    @State private var startup = false
    @State private var skip = false
    @State private var route = "custom"
    @State private var baseURL = ""
    @State private var key = ""
    @State private var modelName = ""
    @State private var importing = false
    @State private var legacyRoot = ""
    @State private var busy = false
    @State private var failure: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Label("Vantage", systemImage: "eye.circle.fill").font(.largeTitle.bold()).foregroundStyle(.teal)
            Text(model.text("欢迎 · 第 \(step + 1) / 3 步", "Welcome · Step \(step + 1) of 3")).font(.title2)
            Form {
                if step == 0 {
                    Picker(model.text("显示语言", "Language"), selection: $language) { Text("System").tag("system"); Text("简体中文").tag("zh-CN"); Text("English").tag("en-US") }
                    Toggle(model.text("登录时启动", "Launch at login"), isOn: $startup)
                    Text(model.text("Vantage 在本机运行；AI 请求发送至你配置的提供商", "Vantage runs locally; AI requests go to the provider you configure.")).foregroundStyle(.secondary)
                } else if step == 1 {
                    Toggle(model.text("稍后配置 AI，保留已有设置", "Set up AI later; keep existing configuration"), isOn: $skip)
                    if !skip {
                        TextField(model.text("提供商标识", "Provider route"), text: $route)
                        TextField("Base URL", text: $baseURL)
                        SecureField("API key", text: $key)
                        TextField(model.text("默认模型", "Default model"), text: $modelName)
                    }
                } else {
                    Toggle(model.text("导入现有个人数据", "Import existing personal data"), isOn: $importing)
                    if importing {
                        HStack { Text(legacyRoot.isEmpty ? model.text("选择数据根目录", "Choose a data folder") : legacyRoot); Button(model.text("选择…", "Choose…")) { if let path = NativePlatform.chooseFolder() { legacyRoot = path } } }
                        Text(model.text("仅在完成引导时复制缺失的历史/状态文件。原始目录保留", "Missing history/state files are copied only when you finish. The source folder is retained.")).font(.caption)
                    }
                    Text(model.text("相机、麦克风和录屏权限可以在设置中按需开启", "Enable camera, microphone and screen recording in Settings when needed."))
                }
            }.formStyle(.grouped)
            if let failure { Text(failure).foregroundStyle(.red) }
            HStack {
                if step > 0 { Button(model.text("上一步", "Back")) { step -= 1 } }
                Spacer()
                Button(step == 2 ? model.text("完成设置", "Finish setup") : model.text("下一步", "Continue")) {
                    if step < 2 { step += 1 } else { Task { await finish() } }
                }.buttonStyle(.borderedProminent).disabled(busy || (step == 1 && !skip && route.trimmingCharacters(in: .whitespaces).isEmpty) || (step == 2 && importing && legacyRoot.isEmpty))
            }
        }.padding(40).frame(maxWidth: 800).disabled(busy)
        .onAppear {
            language = model.onboarding?.displayLanguage ?? "system"; startup = model.onboarding?.launchAtLogin ?? false
            if let selected = model.state?.provider.selected_provider, let provider = model.state?.provider.providers[selected] {
                route = selected; baseURL = provider.base_url; modelName = provider.model
            }
        }
    }
    private func finish() async {
        busy = true; failure = nil; defer { busy = false }
        var body: [String: JSONValue] = ["display_language": .string(language), "launch_at_login": .bool(startup), "skip_chat_setup": .bool(skip), "import_legacy_data": .bool(importing)]
        if !skip {
            body["selected_provider"] = .string(route); body["base_url"] = .string(baseURL); body["model"] = .string(modelName)
            if !key.isEmpty { body["api_key"] = .string(key) }
        }
        if importing { body["legacy_root"] = .string(legacyRoot) }
        do { try await model.completeOnboarding(.object(body)); key = "" } catch { failure = SensitiveText.redact(error.localizedDescription) }
    }
}
