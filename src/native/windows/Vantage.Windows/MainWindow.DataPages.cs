using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Vantage.Core;
using Vantage.Windows.Platform;
using Vantage.Windows.Views;
namespace Vantage.Windows;
public sealed partial class MainWindow
{
    async Task DashboardAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("概览", "Dashboard")));
        var statistics = Stack(); var health = Stack(); var images = Stack(); var cameraStatus = Text("");
        async Task Refresh()
        {
            var status = await api.StatusAsync(ct); var stats = await api.GetAsync<SystemStatistics>("/api/v1/system/statistics", ct);
            var sedentary = await api.GetAsync<JsonElement>("/api/v1/health/sedentary", ct); var aqi = await api.GetAsync<JsonElement>("/api/v1/system/air-quality", ct);
            ct.ThrowIfCancellationRequested(); statistics.Children.Clear(); health.Children.Clear();
            foreach (var (title, value) in new[] { (T("CPU", "CPU"), $"{stats.CpuUsage:0.0}%"), (T("内存", "Memory"), $"{stats.MemoryUsedGb:0.0} / {stats.MemoryTotalGb:0.0} GB"), (T("可用磁盘", "Disk available"), $"{stats.DiskFreeGb:0.0} GB"), (T("媒体存储", "Media storage"), $"{stats.StorageUsedMb:0.0} MB{(stats.StorageScanTruncated ? " · partial" : "")}") })
                statistics.Children.Add(Card(Row(Text(title), Text(value, 24))));
            health.Children.Add(Card(Stack(Text(T("专注 / 久坐状态", "Focus / sedentary status"), 18), DataView(sedentary))));
            health.Children.Add(Card(Stack(Text(T("空气质量", "Air quality"), 18), DataView(aqi))));
            cameraStatus.Text = status.CameraOnline ? status.CameraFrameDark ? T("相机在线 · 光线偏暗", "Camera online · dark frame") : T("相机在线", "Camera online") : T("相机离线", "Camera offline");
        }
        PageContent.Children.Add(Row(ActionButton(T("刷新", "Refresh"), Refresh), ActionButton(T("相机权限", "Camera permissions"), () => { NativeDesktop.PermissionSettings("webcam"); return Task.CompletedTask; }), ActionButton(T("位置权限", "Location permissions"), () => { NativeDesktop.PermissionSettings("location"); return Task.CompletedTask; })));
        PageContent.Children.Add(statistics); PageContent.Children.Add(health); PageContent.Children.Add(cameraStatus);
        var camera = new Image { Height = 350, Stretch = Stretch.Uniform }; var cameraToggle = new ToggleSwitch { Header = T("显示实时相机（默认遮挡）", "Show live camera (hidden by default)") }; CancellationTokenSource? cameraCts = null; privacyToggles.Add(cameraToggle);
        cameraToggle.Toggled += async (_, _) =>
        {
            cameraCts?.Cancel(); cameraCts?.Dispose(); camera.Source = null;
            if (!cameraToggle.IsOn) return;
            cameraCts = CancellationTokenSource.CreateLinkedTokenSource(ct); var streamCt = cameraCts.Token;
            try { await api.StreamCameraAsync(bytes => ImageBytesAsync(camera, bytes), streamCt); }
            catch (OperationCanceledException) when (streamCt.IsCancellationRequested) { }
            catch (Exception e) { if (!ct.IsCancellationRequested) ShowError(e); }
        };
        PageContent.Children.Add(Card(Stack(cameraToggle, camera, ActionButton(T("切换检测框", "Toggle detection boxes"), async () => { await api.PostAsync("/api/v1/camera/detection/toggle", ct: ct); await Refresh(); }))));
        var reveal = new ToggleSwitch { Header = T("显示最近照片与截图（默认遮挡）", "Show latest photo and screenshot (hidden by default)") };
        privacyToggles.Add(reveal);
        reveal.Toggled += async (_, _) =>
        {
            images.Children.Clear(); if (!reveal.IsOn) return;
            try
            {
                var latest = await api.GetAsync<LatestMedia>("/api/v1/media/latest", ct);
                foreach (var (label, path) in new[] { (T("照片", "Photo"), latest.Photo), (T("截图", "Screenshot"), latest.Screenshot) })
                {
                    if (string.IsNullOrEmpty(path)) continue; var image = new Image { MaxHeight = 360, Stretch = Stretch.Uniform }; await ImageBytesAsync(image, await api.DownloadAsync(path, ct));
                    if (!reveal.IsOn || ct.IsCancellationRequested) break; images.Children.Add(Card(Stack(Text(label), image)));
                }
            }
            catch (OperationCanceledException) { }
            catch (Exception e) { ShowError(e); }
        };
        PageContent.Children.Add(reveal); PageContent.Children.Add(images);
        PageContent.Children.Add(Row(ActionButton(T("打开照片目录", "Open photo folder"), () => api.PostAsync("/api/v1/media/open-folder", new { type = "photo" }, ct)), ActionButton(T("打开截图目录", "Open screenshot folder"), () => api.PostAsync("/api/v1/media/open-folder", new { type = "screenshot" }, ct))));
        await Refresh(); if (smokeOutput is null) _ = PollAsync(Refresh, TimeSpan.FromSeconds(10), ct);
    }
    async Task ProjectsAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("项目进度", "Project progress")));
        var body = Stack();
        async Task Refresh()
        {
            var data = await api.GetAsync<ProjectsResponse>("/api/v1/projects/progress", ct); ct.ThrowIfCancellationRequested(); body.Children.Clear();
            body.Children.Add(Card(Stack(Text($"{data.Stats.CompletedTasks} / {data.Stats.TotalTasks} · {data.Stats.CompletionRate:P0}", 24), new ProgressBar { Minimum = 0, Maximum = 100, Value = data.Stats.CompletionRate * 100 })));
            foreach (var (label, items) in new[] { (T("待完成", "Pending"), data.Tasks.Pending), (T("已完成", "Completed"), data.Tasks.Completed) })
            {
                var section = Stack(Text(label, 20)); foreach (var group in items.GroupBy(x => x.Project)) { section.Children.Add(Text(group.Key, 18)); foreach (var task in group) section.Children.Add(MarkdownView.Create((task.Status == "completed" ? "✓ " : "○ ") + task.Task)); }
                if (items.Length == 0) section.Children.Add(Text(T("暂无任务", "No tasks"))); body.Children.Add(Card(section));
            }
            body.Children.Add(DataView(JsonData.Element(data.Commits), T("近期提交", "Recent commits")));
        }
        PageContent.Children.Add(ActionButton(T("刷新", "Refresh"), Refresh)); PageContent.Children.Add(body); await Refresh();
    }
    async Task PlotsAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("数据图表", "Data plots"))); var content = Stack(); var filter = Input(T("搜索图表", "Find a chart"));
        PlotsResponse? data = null;
        void Render()
        {
            content.Children.Clear(); if (data is null) return;
            if (data.Warnings.ValueKind == JsonValueKind.Array && data.Warnings.GetArrayLength() > 0) content.Children.Add(Card(DataView(data.Warnings, T("数据质量提示", "Data quality warnings"))));
            foreach (var chart in data.Charts.Where(c => (PlotText.Translate(c.Title, English) + PlotText.Translate(c.Description ?? "", English)).Contains(filter.Text, StringComparison.CurrentCultureIgnoreCase)))
                content.Children.Add(Card(Stack(Text(PlotText.Translate(chart.Title, English), 22), Text(PlotText.Translate(chart.Description ?? "", English)), DataView(PlotText.Localize(chart.Summary, English)), chart.Empty || chart.Error is not null ? Text(chart.Error ?? T("无源数据", "No source data")) : new NativeChart(PlotText.Localize(chart.Option, English), English))));
            if (data.Charts.Length == 0) content.Children.Add(Text(T("源工作簿中暂无图表数据", "No chart data in the source workbooks")));
        }
        async Task Refresh(bool rebuild) { if (rebuild) await api.PostAsync("/api/v1/plots/refresh", ct: ct); data = await api.GetAsync<PlotsResponse>("/api/v1/plots/data", ct); ct.ThrowIfCancellationRequested(); Render(); }
        filter.TextChanged += (_, _) => Render();
        PageContent.Children.Add(Row(ActionButton(T("刷新图表缓存", "Refresh chart cache"), () => Refresh(true)), ActionButton(T("重新读取", "Reload"), () => Refresh(false)))); PageContent.Children.Add(filter); PageContent.Children.Add(content); await Refresh(false);
    }
    async Task FinanceAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("资产与消费", "Assets and expenses"))); var finance = Stack(); var recommendations = Stack(); var dismissed = Stack();
        var model = new ModelPicker(await api.GetAsync<JsonElement>("/api/v1/models", ct));
        var count = new NumberBox { Header = T("建议数量", "Recommendation count"), Minimum = 3, Maximum = 30, Value = 10, SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline };
        async Task Refresh()
        {
            var data = await api.GetAsync<JsonElement>("/api/v1/finance/balance-sheet", ct); ct.ThrowIfCancellationRequested(); finance.Children.Clear();
            if (data.Field("status").Text() == "unavailable") finance.Children.Add(Text(data.Field("error").Text()));
            finance.Children.Add(FinanceSummary(data.Field("summary"))); finance.Children.Add(DataView(data.Field("suggestions"), T("建议", "Suggestions")));
            foreach (var key in new[] { "trend_points", "forecast_points" }) { finance.Children.Add(Text(key == "trend_points" ? T("消费趋势", "Expense trend") : T("余额预测", "Balance forecast"), 20)); finance.Children.Add(ChartForRows(data.Field(key), key)); }
            finance.Children.Add(ActionButton(T("复制分析输入", "Copy analysis input"), () => { NativeDesktop.Copy(data.Field("prompt_payload").ToString()); return Task.CompletedTask; }));
            foreach (var sheet in data.Field("sheets").Items())
            {
                var columns = sheet.Field("columns").Items().Select(v => v.Text()).ToArray();
                var rows = sheet.Field("rows").Items().Select(row => columns.Select((column, i) => new { column, value = row.Items().ElementAtOrDefault(i) }).ToDictionary(p => p.column, p => p.value));
                finance.Children.Add(new Expander { Header = $"{sheet.Field("name").Text()} · {sheet.Field("row_count").Text()} rows", Content = DataView(JsonData.Element(rows)), HorizontalAlignment = HorizontalAlignment.Stretch });
            }
        }
        JsonElement Request() => JsonData.Element(new { recommendation_count = (int)count.Value, model = model.Model, provider_route = model.Route, reasoning_effort = model.Reasoning, service_tier = model.Tier });
        async Task LoadDismissed()
        {
            var data = await api.GetAsync<JsonElement>("/api/v1/finance/purchase-recommendations/dismissed", ct); ct.ThrowIfCancellationRequested(); dismissed.Children.Clear();
            foreach (var item in data.Field("items").Items()) dismissed.Children.Add(Card(Stack(DataView(item), ActionButton(T("恢复此建议", "Restore item"), async () => { await api.SendAsync<JsonElement>(HttpMethod.Delete, $"/api/v1/finance/purchase-recommendations/dismissed/{item.Field("id").Text()}", ct: ct); await LoadDismissed(); if (recommendations.Children.Count > 0) await LoadRecommendations(false); }))));
            if (!data.Field("items").Items().Any()) dismissed.Children.Add(Text(T("没有已隐藏的建议", "No dismissed recommendations")));
        }
        async Task LoadRecommendations(bool regenerate)
        {
            var request = Request();
            var query = string.Join("&", request.EnumerateObject().Where(p => p.Value.ValueKind != JsonValueKind.Null).Select(p => $"{p.Name}={Uri.EscapeDataString(p.Value.Text())}"));
            var data = regenerate ? await api.PostAsync("/api/v1/finance/purchase-recommendations/regenerate", request, ct) : await api.GetAsync<JsonElement>("/api/v1/finance/purchase-recommendations?" + query, ct);
            ct.ThrowIfCancellationRequested(); recommendations.Children.Clear();
            if (data.Field("error").ValueKind == JsonValueKind.String) recommendations.Children.Add(Text(data.Field("error").Text()));
            foreach (var group in data.Field("recommendation_groups").Items())
            {
                recommendations.Children.Add(Text(group.Field("title").Text(), 20));
                foreach (var item in group.Field("items").Items()) recommendations.Children.Add(Card(Stack(DataView(item), ActionButton(T("隐藏此建议", "Dismiss recommendation"), async () =>
                {
                    await api.PostAsync("/api/v1/finance/purchase-recommendations/dismiss", new { cache_key = data.Field("cache_key").Text(), group_key = group.Field("key").Text(), item }, ct);
                    await LoadRecommendations(false); await LoadDismissed();
                }))));
            }
            if (!data.Field("recommendation_groups").Items().Any()) recommendations.Children.Add(Text(T("暂无采购建议", "No purchase recommendations")));
        }
        PageContent.Children.Add(ActionButton(T("刷新资产负债表", "Refresh balance sheet"), Refresh)); PageContent.Children.Add(finance);
        PageContent.Children.Add(Heading(T("采购建议", "Purchase recommendations"))); PageContent.Children.Add(model); PageContent.Children.Add(count);
        PageContent.Children.Add(Text(T("读取建议可能由后端生成并产生模型费用。点击下方按钮开始。", "Loading recommendations may generate them and incur model usage. Choose a button to begin.")));
        PageContent.Children.Add(Row(ActionButton(T("读取建议", "Load recommendations"), () => LoadRecommendations(false)), ActionButton(T("重新生成", "Regenerate"), () => LoadRecommendations(true)))); PageContent.Children.Add(recommendations);
        PageContent.Children.Add(new Expander { Header = T("已隐藏的建议", "Dismissed recommendations"), Content = Stack(ActionButton(T("读取已隐藏项", "Load dismissed"), LoadDismissed), ActionButton(T("恢复全部", "Restore all"), async () => { if (await ConfirmAsync(T("恢复全部", "Restore all"), T("恢复所有已隐藏的采购建议？", "Restore every dismissed recommendation?"))) { await api.SendAsync<JsonElement>(HttpMethod.Delete, "/api/v1/finance/purchase-recommendations/dismissed", ct: ct); await LoadDismissed(); if (recommendations.Children.Count > 0) await LoadRecommendations(false); } }), dismissed), HorizontalAlignment = HorizontalAlignment.Stretch });
        await Refresh();
    }
    UIElement ChartForRows(JsonElement rows, string title, string? xName = null, string? yName = null)
    {
        var data = rows.Items().ToArray(); if (data.Length == 0) return Text(T("暂无数据", "No data"));
        var keys = data.Where(x => x.ValueKind == JsonValueKind.Object).SelectMany(x => x.EnumerateObject()).Select(x => x.Name).Distinct().ToArray();
        xName ??= keys.FirstOrDefault(k => k is "datetime" or "date" or "timestamp" or "month" or "created_at") ?? keys.FirstOrDefault();
        var numeric = yName is not null ? new[] { yName } : keys.Where(k => k != xName && data.Any(row => row.Field(k).Number().HasValue)).ToArray();
        var series = numeric.Select(k => new { name = k, type = "line", data = data.Select((row, i) => new object?[] { xName is null ? i : row.Field(xName), row.Field(k).Number() }) });
        return Stack(new NativeChart(JsonData.Element(new { xAxis = new { type = "time" }, yAxis = new { type = "value" }, series }), English), new Expander { Header = T("原始记录", "Source records"), Content = DataView(rows), HorizontalAlignment = HorizontalAlignment.Stretch });
    }
    async Task FaceAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("面部历史", "Face history"))); var progress = new ProgressBar { Minimum = 0, Maximum = 100 }; var status = Text(""); var report = Stack(); var live = Stack(); var liveToggle = new ToggleSwitch { Header = T("实时面部状态", "Live face status") };
        privacyToggles.Add(liveToggle);
        var range = Choice(T("时间范围", "Time range"), new[] { "day", "week", "month", "all" }, "week"); JsonElement current = default;
        void Render()
        {
            report.Children.Clear(); if (current.Field("error").ValueKind == JsonValueKind.String) { report.Children.Add(Text(current.Field("error").Text())); return; }
            report.Children.Add(ChartForRows(current.Field("trend_views").Field(Value(range)).Field("points"), "Face", "datetime", "score"));
            foreach (var key in new[] { "lightest", "heaviest" })
            {
                var entry = current.Field(key); var image = new Image { Height = 260, Stretch = Stretch.Uniform }; var reveal = new ToggleSwitch { Header = T("显示照片", "Reveal photo") }; privacyToggles.Add(reveal);
                reveal.Toggled += async (_, _) => { image.Source = null; var path = entry.Field("url").Text(); if (reveal.IsOn && path.Length > 0) { try { var bytes = await api.DownloadAsync(path, ct); if (reveal.IsOn && !ct.IsCancellationRequested) await ImageBytesAsync(image, bytes); } catch (Exception e) { if (!ct.IsCancellationRequested) ShowError(e); } } };
                report.Children.Add(Card(Stack(Text($"{key} · {entry.Field("date").Text()} · {entry.Field("score").Text()}", 18), reveal, image)));
            }
        }
        async Task RefreshReport() { current = await api.GetAsync<JsonElement>("/api/v1/face/report", ct); ct.ThrowIfCancellationRequested(); Render(); }
        async Task Poll()
        {
            var p = await api.GetAsync<FaceProgress>("/api/v1/face/progress", ct); progress.Value = p.Percent; status.Text = $"{p.Status} · {p.Percent:0}% {p.Error}";
            if (liveToggle.IsOn) { var data = await api.GetAsync<JsonElement>("/api/v1/face/live?active=true", ct); live.Children.Clear(); live.Children.Add(ChartForRows(data.Field("points"), "Live", "datetime", "score")); }
        }
        range.SelectionChanged += (_, _) => Render();
        liveToggle.Toggled += async (_, _) => { try { if (liveToggle.IsOn) await Poll(); else { live.Children.Clear(); await api.GetAsync<JsonElement>("/api/v1/face/live?active=false", ct); } } catch (Exception e) { if (!ct.IsCancellationRequested) ShowError(e); } };
        PageContent.Children.Add(Row(ActionButton(T("分析历史", "Analyze history"), async () => { await api.PostAsync("/api/v1/face/analyze", ct: ct); while (true) { await Task.Delay(750, ct); await Poll(); var p = await api.GetAsync<FaceProgress>("/api/v1/face/progress", ct); if (p.Status == "error" || p.Error is not null) throw new InvalidDataException(p.Error ?? "Face analysis failed."); if (p.Status == "done" && p.Percent >= 100) { await RefreshReport(); break; } if (p.Status == "idle") { status.Text = T("没有可分析的数据，或任务未开始；可重新开始", "No analyzable data, or the task did not start; you can retry"); break; } } }),
            ActionButton(T("刷新报告", "Refresh report"), RefreshReport), ActionButton(T("导出 Excel", "Export Excel"), async () => { var path = await NativeDesktop.PickSaveAsync(this, "Face_Analysis_History", ".xlsx"); if (path is not null) { var bytes = await api.DownloadAsync("/api/v1/face/export", ct); await File.WriteAllBytesAsync(path, bytes, ct); Status(T("Excel 已保存", "Excel saved"), InfoBarSeverity.Success); } })));
        PageContent.Children.Add(status); PageContent.Children.Add(progress); PageContent.Children.Add(range); PageContent.Children.Add(report); PageContent.Children.Add(liveToggle); PageContent.Children.Add(live);
        await RefreshReport(); await Poll(); if (smokeOutput is null) _ = PollAsync(Poll, TimeSpan.FromSeconds(2), ct);
    }
    async Task UsageAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("模型用量", "Model usage"))); var content = Stack();
        async Task Refresh()
        {
            var data = await api.GetAsync<JsonElement>("/api/v1/usage", ct); ct.ThrowIfCancellationRequested(); content.Children.Clear();
            content.Children.Add(UsageSummary(data.Field("summary"))); content.Children.Add(ChartForRows(data.Field("by_day"), "Tokens", "date", "total_tokens"));
            content.Children.Add(UsageSpeedChart(data.Field("speed_series")));
            foreach (var (key, title) in new[] { ("by_source", T("按来源", "By source")), ("by_day", T("按日期", "By day")), ("sessions", T("会话", "Sessions")), ("recent_calls", T("最近调用", "Recent calls")) }) content.Children.Add(new Expander { Header = title, Content = DataView(data.Field(key)), HorizontalAlignment = HorizontalAlignment.Stretch });
        }
        PageContent.Children.Add(ActionButton(T("刷新", "Refresh"), Refresh)); PageContent.Children.Add(content); await Refresh();
    }
    async Task LogsAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("系统日志", "System logs"))); var search = Input(T("搜索日志", "Search logs")); var severity = Choice(T("级别", "Severity"), new[] { "All", "ERROR", "WARNING", "INFO", "DEBUG" }, "All"); var automatic = Check(T("自动刷新", "Auto refresh"), true);
        var log = new TextBox { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 400, FontFamily = new FontFamily("Consolas") }; string[] lines = [];
        void Render() => log.Text = string.Join("\n", lines.Select(x => x.TrimEnd()).Where(x => x.Contains(search.Text, StringComparison.CurrentCultureIgnoreCase) && (Value(severity) == "All" || x.Contains(Value(severity), StringComparison.OrdinalIgnoreCase))));
        async Task Refresh() { var data = await api.GetAsync<LogsResponse>("/api/v1/system/logs", ct); ct.ThrowIfCancellationRequested(); lines = data.Logs; Render(); }
        search.TextChanged += (_, _) => Render(); severity.SelectionChanged += (_, _) => Render();
        PageContent.Children.Add(Row(search, severity)); PageContent.Children.Add(Row(automatic, ActionButton(T("刷新", "Refresh"), Refresh), ActionButton(T("复制已筛选日志", "Copy filtered logs"), () => { NativeDesktop.Copy(log.Text); return Task.CompletedTask; })));
        PageContent.Children.Add(log); await Refresh(); if (smokeOutput is null) _ = PollAsync(async () => { if (automatic.IsChecked == true) await Refresh(); }, TimeSpan.FromSeconds(3), ct);
    }
}
