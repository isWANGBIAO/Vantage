import SwiftUI
import VantageCore

@MainActor
final class DomainData: ObservableObject {
    @Published var data: JSONValue = .null
    @Published var loading = false
    @Published var error: String?
    func load(_ path: String, model: AppModel, page: AppPage? = nil) async {
        guard !loading else { return }; loading = true; defer { loading = false }
        let client = model.api
        do {
            let result: JSONValue = try await client.request(path: path)
            guard client === model.api, !Task.isCancelled else { return }
            data = result; error = nil
            if let page { model.pageLoads[page.rawValue] = "loaded" }
        } catch {
            if Task.isCancelled { return }; self.error = SensitiveText.redact(error.localizedDescription)
            if let page { model.pageLoads[page.rawValue] = "error" }
        }
    }
}
struct LoadBanner: View {
    @ObservedObject var source: DomainData
    var reload: () -> Void
    var body: some View {
        if source.loading { ProgressView() }
        if let error = source.error { HStack { Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange); Button("Retry", action: reload) } }
    }
}
struct MetricCard: View {
    let title: String
    let value: String
    var symbol = "chart.bar"
    var body: some View {
        VStack(alignment: .leading, spacing: 10) { Label(title, systemImage: symbol).font(.caption).foregroundStyle(.secondary); Text(value.isEmpty ? "—" : value).font(.title2.bold()).monospacedDigit() }
            .frame(maxWidth: .infinity, alignment: .leading).padding(18).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}
struct DashboardView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var stats = DomainData()
    @State private var status: JSONValue = .null
    @State private var sedentary: JSONValue = .null
    @State private var aqi: JSONValue = .null
    @State private var media: JSONValue = .null
    @State private var revealed = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack { VStack(alignment: .leading) { Text(model.text("今日概览", "Your day at a glance")).font(.largeTitle.bold()); Text(Date(), format: .dateTime.weekday(.wide).month().day()).foregroundStyle(.secondary) }; Spacer(); Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") } }
                LoadBanner(source: stats) { Task { await refresh() } }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 190))], spacing: 14) {
                    MetricCard(title: "CPU", value: stats.data["cpu_usage"].string + "%", symbol: "cpu")
                    MetricCard(title: model.text("内存", "Memory"), value: "\(stats.data["memory_used_gb"].string) / \(stats.data["memory_total_gb"].string) GB", symbol: "memorychip")
                    MetricCard(title: model.text("磁盘可用", "Disk free"), value: stats.data["disk_free_gb"].string + " GB", symbol: "externaldrive")
                    MetricCard(title: model.text("媒体存储", "Media storage"), value: stats.data["storage_used_mb"].string + " MB", symbol: "photo.stack")
                    MetricCard(title: model.text("专注时长", "Focus duration"), value: sedentary["duration_minutes"].string + " min", symbol: "timer")
                    MetricCard(title: "AQI · " + aqi["city"].string, value: aqi["aqi"] == .null ? model.text("不可用", "Unavailable") : aqi["aqi"].string, symbol: "aqi.medium")
                }
                HStack {
                    Label(status["camera_online"].bool == true ? model.text("相机在线", "Camera online") : model.text("相机离线", "Camera offline"), systemImage: "camera")
                    Text(sedentary["detection_status"].string).foregroundStyle(.secondary)
                    Spacer()
                    if stats.data["storage_scan_truncated"].bool == true || media["latest_media_scan_truncated"].bool == true { Label(model.text("扫描未完整，统计为部分结果", "Scan incomplete; totals are partial"), systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
                }.font(.caption)
                GroupBox(model.text("最新媒体", "Latest media")) {
                    VStack(alignment: .leading, spacing: 12) {
                        Toggle(model.text("显示照片和截图", "Reveal photos and screenshots"), isOn: $revealed)
                        HStack(alignment: .top, spacing: 16) {
                            ForEach(["photo", "screenshot"], id: \.self) { kind in
                                VStack(alignment: .leading) {
                                    if revealed { PrivateImage(path: media[kind].string).frame(height: 240) }
                                    else { RoundedRectangle(cornerRadius: 10).fill(.quaternary).overlay(Image(systemName: "eye.slash").font(.largeTitle).foregroundStyle(.secondary)).frame(height: 160) }
                                    HStack {
                                        Text(media[kind + "_name"].string).font(.caption).lineLimit(1)
                                        Spacer()
                                        Button(model.text("打开目录", "Open folder")) {
                                            Task { do { try await model.api.openMediaFolder(kind) } catch { model.report(error) } }
                                        }
                                    }
                                }.frame(maxWidth: .infinity)
                            }
                        }
                    }.padding(8)
                }
                if model.plan?.exists == true { GroupBox(model.text("今日计划", "Today's plan")) { VStack(alignment: .leading) { MarkdownDocument(text: String((model.plan?.plan?.body ?? "").prefix(1000))); Button(model.text("查看完整计划", "Open full plan")) { model.page = .plan } }.padding(8) } }
            }.padding(24)
        }.task {
            await refresh()
            while !Task.isCancelled { try? await Task.sleep(for: .seconds(15)); if Task.isCancelled { return }; await refresh() }
        }
    }
    private func refresh() async {
        await stats.load("/api/v1/system/statistics", model: model)
        do {
            status = try await model.api.request(path: "/api/v1/system/status")
            sedentary = try await model.api.request(path: "/api/v1/health/sedentary")
            aqi = try await model.api.request(path: "/api/v1/system/air-quality")
            media = try await model.api.request(path: "/api/v1/media/latest")
            model.pageLoads[AppPage.dashboard.rawValue] = stats.error == nil ? "loaded" : "error"
        } catch { if !Task.isCancelled { model.report(error); model.pageLoads[AppPage.dashboard.rawValue] = "error" } }
    }
}
struct PrivateImage: View {
    @EnvironmentObject var model: AppModel
    let path: String
    @State private var image: NSImage?
    @State private var error = false
    var body: some View {
        Group {
            if let image { Image(nsImage: image).resizable().scaledToFit() }
            else { ContentUnavailableView(error ? "Image unavailable" : "No image", systemImage: "photo") }
        }.task(id: path) {
            image = nil; error = false
            guard !path.isEmpty else { return }
            do { let data = try await model.api.mediaData(reference: path); guard !Task.isCancelled else { return }; image = NSImage(data: data); error = image == nil } catch { if !Task.isCancelled { self.error = true } }
        }
    }
}
struct ProjectsView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var source = DomainData()
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                LoadBanner(source: source) { Task { await refresh() } }
                let stats = source.data["stats"]
                HStack {
                    MetricCard(title: model.text("总任务", "Total tasks"), value: stats["total_tasks"].string)
                    MetricCard(title: model.text("完成", "Completed"), value: stats["completed_tasks"].string, symbol: "checkmark.circle")
                    MetricCard(title: model.text("完成率", "Completion"), value: ((stats["completion_rate"].double ?? 0) * 100).formatted(.number.precision(.fractionLength(0))) + "%")
                }
                ProgressView(value: stats["completion_rate"].double ?? 0)
                ForEach(["pending", "completed"], id: \.self) { state in
                    GroupBox(state == "pending" ? model.text("当前重点", "Active focus") : model.text("已完成里程碑", "Completed milestones")) {
                        VStack(alignment: .leading, spacing: 16) {
                            let tasks = source.data["tasks"][state].array
                            if tasks.isEmpty { Text(model.text("暂无任务", "No tasks")).foregroundStyle(.secondary) }
                            ForEach(Array(tasks.enumerated()), id: \.offset) { _, task in
                                HStack(alignment: .top) { Image(systemName: state == "completed" ? "checkmark.circle.fill" : "circle").foregroundStyle(.teal); VStack(alignment: .leading) { Text(task["project"].string).font(.caption.bold()).foregroundStyle(.secondary); MarkdownDocument(text: task["task"].string) } }
                            }
                        }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                GroupBox(model.text("近期提交", "Recent activity")) {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(Array(source.data["commits"].array.enumerated()), id: \.offset) { _, commit in
                            HStack(alignment: .top) { Image(systemName: "point.3.connected.trianglepath.dotted"); VStack(alignment: .leading) { Text(commit["message"].string); Text(commit["date"].string + " · " + commit["hash"].string).font(.caption.monospaced()).foregroundStyle(.secondary) } }
                        }
                    }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(24)
        }.task { await refresh() }.toolbar { Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") } }
    }
    private func refresh() async { await source.load("/api/v1/projects/progress", model: model, page: .projects) }
}
struct ExpensesView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var source = DomainData()
    @State private var selectedSheet = ""
    @State private var recommendations: JSONValue = .null
    @State private var dismissed: JSONValue = .null
    @State private var generating = false
    @State private var count = 9
    @State private var showDismissed = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                LoadBanner(source: source) { Task { await refresh() } }
                if !source.data["error"].string.isEmpty { Label(source.data["error"].string, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
                FinanceSummary(summary: source.data["summary"])
                DisclosureGroup(model.text("来源与汇总明细", "Source and summary details")) { RecordDetails(value: source.data["source"]); RecordDetails(value: source.data["summary"]) }
                ForEach(Array(source.data["suggestions"].array.enumerated()), id: \.offset) { _, suggestion in
                    if !suggestion.string.isEmpty { Label(suggestion.string, systemImage: "lightbulb") } else { RecordDetails(value: suggestion) }
                }
                GroupBox(model.text("支出趋势", "Expense trend")) { ValuesChart(rows: source.data["trend_points"].array).padding(8) }
                if !source.data["forecast_points"].array.isEmpty { GroupBox(model.text("预测（独立于实际数据）", "Forecast (separate from actual data)")) { ValuesChart(rows: source.data["forecast_points"].array).padding(8) } }
                if !source.data["sheets"].array.isEmpty {
                    Picker(model.text("工作表", "Worksheet"), selection: $selectedSheet) { ForEach(source.data["sheets"].array, id: \.self) { sheet in Text(sheet["name"].string).tag(sheet["name"].string) } }
                    let sheet = source.data["sheets"].array.first(where: { $0["name"].string == selectedSheet }) ?? source.data["sheets"].array.first ?? .null
                    DynamicGrid(columns: sheet["columns"].array.map(\.string), rows: sheet["rows"].array.map(\.array))
                }
                GroupBox(model.text("采购建议", "Purchase recommendations")) {
                    VStack(alignment: .leading, spacing: 16) {
                        ModelControls()
                        HStack {
                            Stepper(model.text("建议数量：\(count)", "Recommendations: \(count)"), value: $count, in: 3...30)
                            Button(model.text("加载/生成建议", "Load / generate")) { Task { await loadRecommendations(regenerate: false) } }.disabled(generating)
                            Button(model.text("重新生成", "Regenerate")) { Task { await loadRecommendations(regenerate: true) } }.disabled(generating)
                            Button(model.text("已隐藏", "Dismissed")) { Task { do { dismissed = try await model.api.request(path: "/api/v1/finance/purchase-recommendations/dismissed"); showDismissed = true } catch { model.report(error) } } }
                        }
                        Text(model.text("首次加载与重新生成会调用已配置的 AI 提供商", "Loading uncached recommendations or regenerating uses your configured AI provider.")).font(.caption).foregroundStyle(.secondary)
                        if generating { ProgressView() }
                        if !recommendations["error"].string.isEmpty { Text(recommendations["error"].string).foregroundStyle(.orange) }
                        ForEach(Array(recommendations["recommendation_groups"].array.enumerated()), id: \.offset) { _, group in
                            Text(group["title"].string).font(.headline)
                            ForEach(Array(group["items"].array.enumerated()), id: \.offset) { _, item in
                                VStack(alignment: .leading, spacing: 8) {
                                    HStack { Text(item["name"].string).bold(); Spacer(); Text(item["estimated_price"].string); Button(model.text("隐藏", "Dismiss")) { Task { await dismiss(item, group: group) } } }
                                    Text(item["reason"].string)
                                    DisclosureGroup(model.text("证据与风险", "Evidence and risk")) { RecordDetails(value: item) }
                                }.padding().background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
                            }
                        }
                    }.padding(8)
                }
            }.padding(24)
        }.task { await refresh() }.toolbar { Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") } }
            .sheet(isPresented: $showDismissed) {
                VStack(alignment: .leading, spacing: 16) {
                    Text(model.text("已隐藏建议", "Dismissed recommendations")).font(.title2)
                    List(Array(dismissed["items"].array.enumerated()), id: \.offset) { _, item in
                        HStack { Text(item["name"].string.isEmpty ? item["item"]["name"].string : item["name"].string); Spacer(); Button(model.text("恢复", "Restore")) { Task { await restore(item["id"].string) } } }
                    }
                    HStack { Button(model.text("恢复全部", "Restore all")) { Task { await restore(nil) } }; Spacer(); Button(model.text("关闭", "Close")) { showDismissed = false } }
                }.padding(24).frame(width: 650, height: 450)
            }
    }
    private func refresh() async { await source.load("/api/v1/finance/balance-sheet", model: model, page: .expenses); if selectedSheet.isEmpty { selectedSheet = source.data["sheets"].array.first?["name"].string ?? "" } }
    private func options() -> [String: JSONValue] {
        var body: [String: JSONValue] = ["recommendation_count": .number(Double(count))]
        if let option = model.selectedOption { body["model"] = .string(option.model); body["provider_route"] = .string(option.provider_route) }
        if !model.reasoning.isEmpty { body["reasoning_effort"] = .string(model.reasoning) }; if !model.tier.isEmpty { body["service_tier"] = .string(model.tier) }; return body
    }
    private func loadRecommendations(regenerate: Bool) async {
        generating = true; defer { generating = false }
        do {
            recommendations = try await model.api.request(path: "/api/v1/finance/purchase-recommendations" + (regenerate ? "/regenerate" : ""), method: regenerate ? "POST" : "GET", query: regenerate ? [:] : options().mapValues(\.string), body: regenerate ? .object(options()) : nil)
        } catch { model.report(error) }
    }
    private func dismiss(_ item: JSONValue, group: JSONValue) async {
        do {
            let _: JSONValue = try await model.api.request(path: "/api/v1/finance/purchase-recommendations/dismiss", method: "POST", body: .object(["cache_key": recommendations["cache_key"], "group_key": group["key"], "item": item]))
            var object = recommendations.object
            object["recommendation_groups"] = .array(recommendations["recommendation_groups"].array.map { current in var copy = current.object; copy["items"] = .array(current["items"].array.filter { $0 != item }); return .object(copy) })
            recommendations = .object(object)
        } catch { model.report(error) }
    }
    private func restore(_ id: String?) async {
        do {
            let _: JSONValue = try await model.api.request(path: "/api/v1/finance/purchase-recommendations/dismissed" + (id.map { "/\($0)" } ?? ""), method: "DELETE")
            dismissed = try await model.api.request(path: "/api/v1/finance/purchase-recommendations/dismissed")
        } catch { model.report(error) }
    }
}

struct PlotsView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var source = DomainData()
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                LoadBanner(source: source) { Task { await refresh() } }
                ForEach(Array(source.data["warnings"].array.enumerated()), id: \.offset) { _, warning in
                    DisclosureGroup { RecordDetails(value: warning) } label: { Label(warning["message"].string.isEmpty ? warning["title"].string : warning["message"].string, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
                }
                Picker(model.text("图表", "Chart"), selection: $model.selectedPlotID) {
                    Text(model.text("所有图表", "All charts")).tag("")
                    ForEach(Array(source.data["charts"].array.enumerated()), id: \.offset) { _, chart in Text(chart["title"].string).tag(chart["id"].string) }
                }
                ForEach(Array(source.data["charts"].array.filter { model.selectedPlotID.isEmpty || $0["id"].string == model.selectedPlotID }.enumerated()), id: \.offset) { _, chart in BackendChart(chart: chart) }
                if source.data["charts"].array.isEmpty && !source.loading { ContentUnavailableView(model.text("暂无图表数据", "No chart data"), systemImage: "chart.xyaxis.line") }
                Text(source.data["generated_at"].string).font(.caption).foregroundStyle(.secondary)
            }.padding(24)
        }.task { await refresh() }.toolbar {
            Button(model.text("刷新数据", "Refresh data")) { Task { do { let _: JSONValue = try await model.api.request(path: "/api/v1/plots/refresh", method: "POST"); await refresh() } catch { model.report(error) } } }
        }
    }
    private func refresh() async { await source.load("/api/v1/plots/data", model: model, page: .plots) }
}
struct FaceView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var source = DomainData()
    @State private var progress: JSONValue = .null
    @State private var live: JSONValue = .null
    @State private var preview = false
    @State private var revealPhotos = false
    @State private var busy = false
    @State private var confirmAnalyze = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Button(model.text("分析历史照片", "Analyze face history")) { confirmAnalyze = true }.buttonStyle(.borderedProminent).disabled(busy)
                    Button(model.text("导出 Excel", "Export Excel")) { Task { await export() } }
                    Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") }
                    Spacer()
                    Toggle(model.text("显示历史照片", "Reveal history photos"), isOn: $revealPhotos)
                }
                if progress["status"].string != "idle" { ProgressView(value: progress["percent"].double ?? 0, total: 100) { Text(progress["status"].string + " · " + progress["percent"].string + "%") } }
                if !progress["error"].string.isEmpty { Text(progress["error"].string).foregroundStyle(.red) }
                LoadBanner(source: source) { Task { await refresh() } }
                GroupBox(model.text("实时相机", "Live camera")) {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            Toggle(model.text("显示实时预览", "Show live preview"), isOn: $preview)
                            Button(model.text("开启本机相机", "Enable native camera")) { Task { do { try await model.camera.start() } catch { model.report(error) } } }
                            Button(model.text("检测框开关", "Toggle detection overlay")) { Task { do { let _: JSONValue = try await model.api.request(path: "/api/v1/camera/detection/toggle", method: "POST") } catch { model.report(error) } } }
                        }
                        if preview { CameraPreview().frame(height: 330); ValuesChart(rows: live["points"].array, xKey: "datetime", keys: ["score"]) }
                        else { Label(model.text("预览已隐藏", "Preview is hidden"), systemImage: "eye.slash").foregroundStyle(.secondary).padding(32) }
                    }.padding(8)
                }
                if !source.data["error"].string.isEmpty { ContentUnavailableView(model.text("暂无历史报告", "No history report"), systemImage: "person.crop.rectangle", description: Text(source.data["error"].string)) }
                ForEach(["day", "week", "month", "all"], id: \.self) { window in
                    if !source.data["trend_views"][window]["points"].array.isEmpty {
                        GroupBox(window) { ValuesChart(rows: source.data["trend_views"][window]["points"].array, xKey: "datetime", keys: ["score"]).padding(8) }
                    }
                }
                HStack(alignment: .top) {
                    ForEach(["lightest", "heaviest"], id: \.self) { key in
                        let value = source.data[key]
                        if !value.object.isEmpty {
                            GroupBox(key == "lightest" ? model.text("最低评分", "Lowest score") : model.text("最高评分", "Highest score")) {
                                VStack { Text(value["score"].string).font(.largeTitle); Text(value["date"].string).foregroundStyle(.secondary); if revealPhotos { PrivateImage(path: value["url"].string).frame(height: 250) } else { Image(systemName: "eye.slash").font(.largeTitle).frame(height: 120) } }.frame(maxWidth: .infinity).padding()
                            }
                        }
                    }
                }
            }.padding(24)
        }.task {
            await refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2)); if Task.isCancelled { return }
                do {
                    let previous = progress["status"].string
                    progress = try await model.api.request(path: "/api/v1/face/progress")
                    busy = ["running", "processing", "starting", "analyzing", "building_report"].contains(progress["status"].string)
                    if preview { live = try await model.api.request(path: "/api/v1/face/live", query: ["active": "true"]) }
                    if ["completed", "done", "success"].contains(progress["status"].string), previous != progress["status"].string { await source.load("/api/v1/face/report", model: model) }
                } catch { if !Task.isCancelled { model.report(error) } }
            }
        }
        .confirmationDialog(model.text("分析已有照片并保存面部历史报告？", "Analyze existing photos and save a face-history report?"), isPresented: $confirmAnalyze) {
            Button(model.text("开始分析", "Start analysis")) { Task { do { let _: JSONValue = try await model.api.request(path: "/api/v1/face/analyze", method: "POST"); busy = true; await refresh() } catch { model.report(error) } } }
        }
    }
    private func refresh() async {
        await source.load("/api/v1/face/report", model: model, page: .face)
        do { progress = try await model.api.request(path: "/api/v1/face/progress") } catch { model.report(error) }
    }
    private func export() async { do { let data = try await model.api.data(path: "/api/v1/face/export"); try NativePlatform.save(data, filename: "Face_Analysis_History.xlsx") } catch { model.report(error) } }
}
struct CameraPreview: View {
    @EnvironmentObject var model: AppModel
    @State private var image: NSImage?
    @State private var failure: String?
    var body: some View {
        Group {
            if let image { Image(nsImage: image).resizable().scaledToFit() }
            else if let failure { ContentUnavailableView("Camera unavailable", systemImage: "video.slash", description: Text(failure)) }
            else { ProgressView("Waiting for camera frames…") }
        }.task {
            do {
                try await model.api.jpegFrames { data in
                    await MainActor.run { image = NSImage(data: data) }
                }
            } catch { if !Task.isCancelled { failure = error.localizedDescription } }
        }
    }
}
struct UsageView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var source = DomainData()
    @State private var tab = "recent_calls"
    @State private var filter = ""
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                LoadBanner(source: source) { Task { await refresh() } }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180))]) {
                    ForEach(["session_count", "completed_call_count", "failed_call_count", "total_tokens", "prompt_tokens", "completion_tokens", "prompt_cache_hit_rate", "output_tokens_per_second"], id: \.self) { key in
                        MetricCard(title: key.replacingOccurrences(of: "_", with: " "), value: metricValue(key))
                    }
                }
                GroupBox(model.text("每日用量", "Daily usage")) { ValuesChart(rows: source.data["by_day"].array, keys: ["prompt_tokens", "completion_tokens", "total_tokens"]).padding(8) }
                GroupBox(model.text("调用速度", "Call speed")) { ValuesChart(rows: source.data["speed_series"].array, xKey: "created_at", keys: ["output_tokens_per_second", "average_tokens_per_second"]).padding(8) }
                Picker(model.text("明细", "Details"), selection: $tab) {
                    Text(model.text("调用", "Calls")).tag("recent_calls"); Text(model.text("会话", "Sessions")).tag("sessions"); Text(model.text("来源", "Sources")).tag("by_source")
                }.pickerStyle(.segmented)
                let rows = source.data[tab].array
                let keys = Array(Set(rows.flatMap { $0.object.keys })).sorted()
                DynamicGrid(columns: keys, rows: rows.map { row in keys.map { row[$0] } })
                DisclosureGroup(model.text("完整汇总", "Full summary")) { RecordDetails(value: source.data["summary"]) }
            }.padding(24)
        }.task { await refresh() }.toolbar { Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") } }
    }
    private func metricValue(_ key: String) -> String {
        let value = source.data["summary"][key]
        guard let numeric = value.double else { return value == .null ? "—" : value.string }
        if key.hasSuffix("_rate") { return numeric.formatted(.number.precision(.fractionLength(1))) + "%" }
        if key.hasSuffix("_per_second") { return numeric.formatted(.number.precision(.fractionLength(0...2))) + " tok/s" }
        return numeric.formatted(.number.precision(.fractionLength(0)))
    }
    private func refresh() async { await source.load("/api/v1/usage", model: model, page: .usage) }
}
struct LogsView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var source = DomainData()
    @State private var search = ""
    @State private var severity = "all"
    @State private var live = true
    private var lines: [String] { source.data["logs"].array.map { SensitiveText.redact($0.string) }.filter { (search.isEmpty || $0.localizedCaseInsensitiveContains(search)) && (severity == "all" || $0.localizedCaseInsensitiveContains(severity)) } }
    var body: some View {
        VStack(spacing: 14) {
            HStack {
                TextField(model.text("搜索日志", "Search logs"), text: $search).textFieldStyle(.roundedBorder)
                Picker(model.text("级别", "Level"), selection: $severity) { Text(model.text("全部", "All")).tag("all"); Text("ERROR").tag("error"); Text("WARNING").tag("warn"); Text("INFO").tag("info") }.frame(width: 150)
                Toggle(model.text("实时刷新", "Live"), isOn: $live)
                Button(model.text("复制可见日志", "Copy visible logs")) { NativePlatform.copy(lines.joined(separator: "\n")) }
            }
            LoadBanner(source: source) { Task { await refresh() } }
            GeometryReader { geometry in
                ScrollView([.vertical, .horizontal]) {
                    LazyVStack(alignment: .leading, spacing: 5) {
                        ForEach(Array(lines.enumerated()), id: \.offset) { _, line in Text(line).font(.system(.caption, design: .monospaced)).foregroundStyle(line.localizedCaseInsensitiveContains("error") ? Color.red : line.localizedCaseInsensitiveContains("warn") ? .orange : .primary).textSelection(.enabled) }
                    }.frame(minWidth: geometry.size.width, minHeight: geometry.size.height, alignment: .topLeading)
                }.background(.background, in: RoundedRectangle(cornerRadius: 10))
            }
        }.padding(24).task {
            await refresh()
            while !Task.isCancelled { try? await Task.sleep(for: .seconds(3)); if Task.isCancelled { return }; if live { await refresh() } }
        }.toolbar { Button { Task { await refresh() } } label: { Image(systemName: "arrow.clockwise") } }
    }
    private func refresh() async { await source.load("/api/v1/system/logs", model: model, page: .logs) }
}

struct FinanceSummary: View {
    @EnvironmentObject var model: AppModel
    let summary: JSONValue
    private func currency(_ value: JSONValue) -> String {
        guard let number = value.double ?? value["value"].double else { return "—" }
        return number.formatted(.currency(code: "CNY").precision(.fractionLength(0...2)))
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(model.text("资产与负债", "Assets and liabilities")).font(.title2.bold())
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180))]) {
                ForEach(["fixed_assets", "current_assets", "total_assets", "liabilities", "equity", "cash_and_stock"], id: \.self) { key in
                    MetricCard(title: key.replacingOccurrences(of: "_", with: " "), value: currency(summary["assets"][key]), symbol: "banknote")
                }
            }
            Text(model.text("时间成本与预算", "Time cost and budget")).font(.title2.bold())
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180))]) {
                MetricCard(title: model.text("每天成本", "Daily cost"), value: currency(summary["time_cost"]["daily_average"]), symbol: "calendar")
                MetricCard(title: model.text("每分钟成本", "Cost per minute"), value: currency(summary["time_cost"]["per_minute"]), symbol: "clock")
                MetricCard(title: model.text("本月总支出", "Monthly total"), value: currency(summary["time_cost"]["monthly_total"]), symbol: "calendar")
                MetricCard(title: model.text("必需月预算", "Required monthly budget"), value: currency(summary["budget"]["monthly_required"]), symbol: "checkmark.circle")
                MetricCard(title: model.text("可选月预算", "Optional monthly budget"), value: currency(summary["budget"]["monthly_optional"]), symbol: "circle.dashed")
            }
        }
    }
}
