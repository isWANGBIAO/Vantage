import SwiftUI
import VantageCore

struct ModelControls: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        HStack {
            Picker(model.text("模型", "Model"), selection: $model.selectedModel) {
                Text(model.text("后端默认", "Backend default")).tag("")
                ForEach(model.models) { option in Text(option.label).tag(option.id) }
            }.frame(maxWidth: 420)
            Picker(model.text("推理", "Reasoning"), selection: $model.reasoning) {
                Text(model.text("默认", "Default")).tag("")
                ForEach(model.selectedOption?.reasoning_tiers ?? ["low", "medium", "high", "xhigh", "max"], id: \.self) { Text($0).tag($0) }
            }.frame(width: 170)
            Picker(model.text("服务层级", "Tier"), selection: $model.tier) {
                Text(model.text("默认", "Default")).tag(""); Text("priority").tag("priority"); Text("fast").tag("fast")
            }.frame(width: 160)
        }
        .onChange(of: model.selectedModel) { _, _ in
            if let option = model.selectedOption, !option.reasoning_tiers.contains(model.reasoning) { model.reasoning = option.default_reasoning_effort ?? option.reasoning_tiers.first ?? "" }
        }
    }
}
struct ActionPlanView: View {
    @EnvironmentObject var model: AppModel
    @State private var replace = false
    @State private var confirmReplace = false
    @State private var scheduler: JSONValue = .null
    @State private var showAnalysis = true
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                ModelControls()
                HStack {
                    if model.job?.status.terminal == false {
                        ProgressView().controlSize(.small)
                        Text(model.job?.progress.phase ?? "")
                        Button(model.text("停止生成", "Cancel generation"), role: .destructive) { Task { await model.cancelJob() } }
                    } else {
                        Button(model.text("生成计划", "Generate plan")) {
                            if model.plan?.exists == true && replace { confirmReplace = true } else { Task { await model.generate(replace: replace) } }
                        }.buttonStyle(.borderedProminent).disabled(model.creatingPlan)
                        Toggle(model.text("成功后替换今日计划", "Replace today's plan after success"), isOn: $replace).toggleStyle(.checkbox)
                    }
                    Spacer()
                    Button { Task { await model.refreshPlanAndJobs() } } label: { Image(systemName: "arrow.clockwise") }.help(model.text("刷新", "Refresh"))
                }
                if let job = model.job {
                    GroupBox(model.text("后台任务", "Backend job")) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("\(job.id) · \(job.status.rawValue)").font(.caption.monospaced())
                            if job.reused { Text(model.text("已加入正在运行的任务；以下为实际请求参数", "Joined the active job; these are its actual request parameters")).foregroundStyle(.orange) }
                            Text("\(job.request.model ?? "default") · \(job.request.provider_route ?? "default") · \(job.request.reasoning_effort ?? "default")")
                            Text(model.planConnection).foregroundStyle(.secondary)
                            if !model.planStream.lastLog.isEmpty { Text(model.planStream.lastLog).font(.caption) }
                            if let error = job.error { Text(error.message).foregroundStyle(.red) }
                            if model.planStream.needsSnapshot { Text(model.text("部分进度已截断，正在读取完整后台结果", "Some progress was truncated; waiting for the complete backend result")).foregroundStyle(.orange) }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                if !model.planStream.plan.isEmpty && model.job?.status.terminal == false {
                    GroupBox(model.text("生成中 · 尚未保存", "Generating · not yet saved")) { MarkdownDocument(text: model.planStream.plan) }
                }
                if let plan = model.plan, plan.exists {
                    HStack { Text(plan.date ?? "").font(.title3).foregroundStyle(.secondary); Spacer(); Button(model.text("复制计划", "Copy plan")) { NativePlatform.copy(plan.plan?.body ?? "") } }
                    MarkdownDocument(text: plan.plan?.body ?? "")
                    DisclosureGroup(model.text("综合分析", "Analysis"), isExpanded: $showAnalysis) { MarkdownDocument(text: plan.analysis?.body ?? "") }
                    if let meta = plan.meta { DisclosureGroup(model.text("生成信息与用量", "Generation details and usage")) { RecordDetails(value: meta) } }
                } else { ContentUnavailableView(model.text("今日尚无完整计划", "No complete plan for today"), systemImage: "checklist", description: Text(model.text("先配置模型，再生成行动计划", "Configure a model, then generate a plan."))) }
                if !scheduler.object.isEmpty { DisclosureGroup(model.text("后台调度状态", "Backend scheduler")) { RecordDetails(value: scheduler) } }
            }.padding(24)
        }
        .task { await model.refreshPlanAndJobs(); do { scheduler = try await model.api.request(path: "/api/v1/action-plan/scheduler") } catch { model.report(error) } }
        .confirmationDialog(model.text("新计划成功保存后，替换今天已有的计划？", "Replace today's saved plan after the new plan succeeds?"), isPresented: $confirmReplace) {
            Button(model.text("生成并替换", "Generate and replace")) { Task { await model.generate(replace: true) } }
        }
    }
}
struct ChatView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var voice = VoiceRecorder()
    @State private var confirmClear = false
    @State private var transcribing = false
    @State private var showBase = false
    @State private var sendVoice = true
    @State private var recordingTask: Task<Void, Never>?
    @State private var voiceEpoch = UUID()
    private var messages: [ChatMessage] {
        let all = model.chat?.messages ?? []
        let base = model.chat?.display_messages ?? []
        return !showBase && all.starts(with: base) ? Array(all.dropFirst(base.count)) : all
    }
    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 12) {
                ModelControls()
                HStack {
                    Label(model.chat?.has_action_plan_context == true ? model.text("已载入行动计划上下文", "Action-plan context loaded") : model.text("独立会话", "Standalone session"), systemImage: "doc.text")
                    Toggle(model.text("显示基础计划对话", "Show plan context"), isOn: $showBase).toggleStyle(.checkbox)
                    Spacer()
                    Button(model.text("清空会话", "Clear conversation"), role: .destructive) { confirmClear = true }.disabled(model.sendingChat)
                }.font(.caption)
            }.padding(18)
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        if messages.isEmpty && !model.sendingChat { ContentUnavailableView(model.text("开始对话", "Start a conversation"), systemImage: "bubble.left.and.bubble.right") }
                        ForEach(Array(messages.enumerated()), id: \.offset) { index, message in
                            VStack(alignment: .leading, spacing: 8) {
                                Label(message.role == "user" ? model.text("你", "You") : "Vantage", systemImage: message.role == "user" ? "person.crop.circle" : "sparkles").font(.caption.bold()).foregroundStyle(.secondary)
                                MarkdownDocument(text: message.content)
                            }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(message.role == "user" ? Color.accentColor.opacity(0.07) : Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: 12)).id(index)
                        }
                        if model.sendingChat || !model.chatStream.content.isEmpty {
                            VStack(alignment: .leading, spacing: 12) {
                                if model.sendingChat { ProgressView(model.text("正在回复…", "Replying…")) }
                                if !model.chatStream.thinking.isEmpty { DisclosureGroup(model.text("推理过程", "Reasoning")) { MarkdownDocument(text: model.chatStream.thinking) } }
                                MarkdownDocument(text: model.chatStream.content)
                            }.padding().id("stream")
                        }
                        Color.clear.frame(height: 1).id("bottom")
                    }.padding(20)
                }.onChange(of: model.chatStream.content) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
                    .onChange(of: messages.count) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
            }
            if let stats = model.chatStream.stats ?? model.chat?.stats { DisclosureGroup(model.text("会话用量", "Session usage")) { RecordDetails(value: stats).frame(maxHeight: 180) }.font(.caption).padding(.horizontal, 20) }
            Divider()
            HStack {
                Text(model.state?.settings.voice_model ?? "").font(.caption).foregroundStyle(.secondary)
                Toggle(model.text("录音转录后发送", "Send after voice transcription"), isOn: $sendVoice).toggleStyle(.checkbox).font(.caption)
                if voice.recording {
                    TimelineView(.periodic(from: .now, by: 1)) { _ in Label("\(Int(voice.duration))s", systemImage: "record.circle").foregroundStyle(.red) }
                }
                Spacer()
            }.padding(.horizontal, 18).padding(.top, 10)
            HStack(alignment: .bottom, spacing: 12) {
                TextEditor(text: $model.draft).font(.body).frame(minHeight: 60, maxHeight: 130).padding(7).background(.background, in: RoundedRectangle(cornerRadius: 8)).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor)))
                Button { recordingTask = Task { await toggleRecording() } } label: { Image(systemName: voice.recording ? "stop.circle.fill" : "mic.fill").foregroundStyle(voice.recording ? .red : .primary) }.disabled(transcribing || model.sendingChat || (!model.chatReady && !voice.recording)).help(model.text("录音转文字", "Record and transcribe"))
                Button {
                    guard let file = NativePlatform.chooseAudio() else { return }
                    recordingTask = Task { await transcribeFile(file) }
                } label: { Image(systemName: "waveform.badge.plus") }
                    .disabled(voice.recording || transcribing || model.sendingChat || !model.chatReady)
                    .help(model.text("选择音频文件转录", "Transcribe an audio file"))
                if transcribing {
                    ProgressView().controlSize(.small)
                    Button(model.text("取消转录", "Cancel transcription")) { voiceEpoch = UUID(); recordingTask?.cancel(); transcribing = false }
                }
                if model.sendingChat { Button(model.text("停止", "Stop")) { model.stopChat() } }
                else { Button(model.text("发送", "Send")) { model.sendChat() }.buttonStyle(.borderedProminent).disabled(!model.chatReady || model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || voice.recording || transcribing).keyboardShortcut(.return, modifiers: .command) }
            }.padding(18)
        }
        .task { do { try await model.refreshChat() } catch { model.report(error) } }
        .onDisappear { voiceEpoch = UUID(); recordingTask?.cancel(); voice.discard() }
        .confirmationDialog(model.text("清空对话？行动计划上下文将保留", "Clear conversation? The action-plan context will be retained."), isPresented: $confirmClear) {
            Button(model.text("清空", "Clear"), role: .destructive) { Task { do { try await model.clearChat() } catch { model.report(error) } } }
        }
    }
    private func transcribeFile(_ file: URL) async {
        let epoch = voiceEpoch; let client = model.api
        transcribing = true
        let scoped = file.startAccessingSecurityScopedResource()
        defer { if scoped { file.stopAccessingSecurityScopedResource() }; if epoch == voiceEpoch { transcribing = false } }
        do {
            let text = try await client.transcribe(file: file)
            guard epoch == voiceEpoch, client === model.api, !Task.isCancelled else { return }
            model.draft += (model.draft.isEmpty ? "" : "\n") + text
        } catch { if epoch == voiceEpoch { model.report(error) } }
    }
    private func toggleRecording() async {
        let epoch = voiceEpoch; let client = model.api
        do {
            if voice.recording {
                guard let file = voice.stop() else { return }; transcribing = true
                defer { voice.discard(); transcribing = false }
                let text = try await client.transcribe(file: file)
                guard epoch == voiceEpoch, !Task.isCancelled, client === model.api else { return }
                model.draft += (model.draft.isEmpty ? "" : "\n") + text
                if sendVoice && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { model.sendChat() }
            } else { try await voice.start() }
        } catch { voice.discard(); model.report(error) }
    }
}

struct MarkdownDocument: View {
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(MarkdownBlocks.parse(text).enumerated()), id: \.offset) { _, block in
                switch block {
                case .heading(let title, let level):
                    Text(.init(title)).font(level == 1 ? .title.bold() : level == 2 ? .title2.bold() : .headline).padding(.top, 8)
                case .code(let language, let code):
                    VStack(alignment: .leading, spacing: 6) {
                        HStack { Text(language.isEmpty ? "Code" : language).font(.caption).foregroundStyle(.secondary); Spacer(); Button("Copy") { NativePlatform.copy(code) } }
                        ScrollView(.horizontal) { Text(code).font(.system(.body, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading) }
                    }.padding(12).background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                case .table(let columns, let rows):
                    DynamicGrid(columns: columns, rows: rows.map { $0.map(JSONValue.string) })
                case .quote(let content):
                    HStack(alignment: .top) { Rectangle().fill(Color.accentColor).frame(width: 3); Text(.init(content)).foregroundStyle(.secondary).padding(.vertical, 4) }.fixedSize(horizontal: false, vertical: true)
                case .paragraph(let line):
                    if line.hasPrefix("- [x] ") || line.hasPrefix("- [ ] ") {
                        Label { Text(.init(String(line.dropFirst(6)))) } icon: { Image(systemName: line.hasPrefix("- [x]") ? "checkmark.circle.fill" : "circle").foregroundStyle(.teal) }
                    } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                        HStack(alignment: .firstTextBaseline) { Text("•"); Text(.init(String(line.dropFirst(2)))) }
                    } else { Text(.init(line.isEmpty ? " " : line)).frame(maxWidth: .infinity, alignment: .leading) }
                }
            }
        }.textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
    }
}
struct RecordDetails: View {
    let value: JSONValue
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(value.object.keys.sorted(), id: \.self) { key in
                if !value[key].object.isEmpty || !value[key].array.isEmpty {
                    DisclosureGroup(key.replacingOccurrences(of: "_", with: " ")) { Text(value[key].pretty).font(.caption.monospaced()).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                } else { LabeledContent(key.replacingOccurrences(of: "_", with: " "), value: value[key] == .null ? "—" : value[key].string).textSelection(.enabled) }
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
