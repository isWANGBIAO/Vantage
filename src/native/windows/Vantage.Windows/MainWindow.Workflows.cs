using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Vantage.Core;
using Vantage.Windows.Platform;
using Vantage.Windows.Views;
using Windows.System;
namespace Vantage.Windows;
public sealed partial class MainWindow
{
    async Task PlanAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("今日行动计划", "Today's action plan")));
        var models = new ModelPicker(await api.GetAsync<JsonElement>("/api/v1/models", ct)); PageContent.Children.Add(models);
        var replace = Check(T("成功后替换今日计划", "Replace today's plan after successful generation"), false);
        var wait = Check(T("等待本地服务就绪", "Wait for local provider readiness"), false);
        var progress = Text(T("尚无活动任务", "No active job")); var actualRequest = Text("");
        var eventLog = Input(T("实时进度", "Live progress"), multi: true); eventLog.IsReadOnly = true;
        var resultPanel = Stack(); string? currentJob = null; PlanResult? displayedPlan = null;
        async Task<PlanResult> LoadSaved()
        {
            var saved = await api.PlanAsync(ct); ct.ThrowIfCancellationRequested();
            if (!saved.IsComplete) { if (resultPanel.Children.Count == 0) resultPanel.Children.Add(Text(T("今天还没有完整保存的计划", "No complete plan saved for today"))); return saved; }
            if (JobObserver.MatchesSavedResult(displayedPlan, saved)) return saved;
            resultPanel.Children.Clear(); displayedPlan = saved;
            resultPanel.Children.Add(Text($"{saved.Date} · {saved.Filename}"));
            resultPanel.Children.Add(ActionButton(T("复制完整计划", "Copy complete plan"), () => { NativeDesktop.Copy(saved.Analysis!.Body + "\n\n" + saved.Plan!.Body); return Task.CompletedTask; }));
            resultPanel.Children.Add(Card(Stack(Heading(T("分析", "Analysis")), MarkdownView.Create(saved.Analysis!.Body))));
            resultPanel.Children.Add(Card(Stack(Heading(T("行动", "Plan")), MarkdownView.Create(saved.Plan!.Body))));
            if (saved.Meta is { } meta) resultPanel.Children.Add(new Expander { Header = T("模型、输入与统计", "Model, inputs and statistics"), Content = DataView(meta), HorizontalAlignment = HorizontalAlignment.Stretch });
            return saved;
        }
        async Task Observe(PlanJob job)
        {
            if (currentJob is not null) return;
            currentJob = job.Id;
            actualRequest.Text = $"{job.Id} · {(job.Reused ? T("已加入现有任务", "Joined existing job") : job.Trigger)}\n{JsonSerializer.Serialize(job.Request, JsonData.Options)}";
            try
            {
                var terminal = await new JobObserver(api).ObserveAsync(job.Id,
                    state => progress.Text = $"{state.Status} · {state.Progress?.Phase}",
                    e => { if (e.Truncated || e.EventTruncated) { eventLog.Text = T("部分事件已过期，正在重新读取完整任务结果", "Some events expired; reloading the complete job result"); } else if (e.Log is not null) AppendBounded(eventLog, e.Log); }, ct);
                if (terminal.Status == "succeeded")
                {
                    var saved = await LoadSaved();
                    if (JobObserver.MatchesSavedResult(terminal.Result, saved)) Status(T("新计划已完整保存并核对", "The new plan is saved and verified"), InfoBarSeverity.Success);
                    else Status(saved.IsComplete ? T("任务已结束；保存结果随后发生变化，当前显示最新结果", "The job finished, but the saved result changed afterward; the latest result is shown") : T("任务已结束，但尚未读到对应的完整保存结果", "The job finished, but its complete saved result could not be verified"), InfoBarSeverity.Warning);
                }
                else if (terminal.Status == "failed") Status(terminal.Error?.Message ?? T("生成失败，保留旧计划", "Generation failed; the previous plan is retained"), InfoBarSeverity.Error);
            }
            catch (JobLostException) { currentJob = null; await LoadSaved(); var jobs = await api.JobsAsync(ct); progress.Text = T("后端已重启，已重新加载保存结果", "Backend restarted; saved results reloaded"); if (jobs.Active is { } active && active.Id != job.Id) await Observe(active); }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
            catch (Exception e) { if (!ct.IsCancellationRequested) ShowError(e); }
            finally { if (currentJob == job.Id) currentJob = null; }
        }
        var generate = ActionButton(T("生成 / 加入任务", "Generate / join job"), async () =>
        {
            if (replace.IsChecked == true && !await ConfirmAsync(T("替换今日计划", "Replace today's plan"), T("新结果完整保存后才会替换今日计划，继续吗？", "The current plan will only be replaced after the new result is complete. Continue?"))) return;
            await Observe(await api.CreateJobAsync(new(models.Model, models.Route, models.Reasoning, models.Tier, replace.IsChecked == true, wait.IsChecked == true), ct));
        });
        var cancel = ActionButton(T("取消活动任务", "Cancel active job"), async () => { var active = currentJob ?? (await api.JobsAsync(ct)).Active?.Id; if (active is not null) { var result = await api.CancelJobAsync(active, ct); progress.Text = result.Status; } });
        PageContent.Children.Add(Row(generate, cancel, ActionButton(T("重新连接 / 刷新", "Reconnect / refresh"), () => NavigateAsync("plan"))));
        PageContent.Children.Add(Row(replace, wait)); PageContent.Children.Add(progress); PageContent.Children.Add(actualRequest); PageContent.Children.Add(eventLog); PageContent.Children.Add(resultPanel);
        await LoadSaved();
        var scheduler = await api.GetAsync<JsonElement>("/api/v1/action-plan/scheduler", ct);
        PageContent.Children.Add(new Expander { Header = T("后台调度状态", "Background scheduler"), Content = DataView(scheduler), HorizontalAlignment = HorizontalAlignment.Stretch });
        var list = await api.JobsAsync(ct);
        PageContent.Children.Add(new Expander { Header = T("最近任务", "Recent jobs"), Content = DataView(JsonData.Element(list.Jobs)), HorizontalAlignment = HorizontalAlignment.Stretch });
        if (list.Active is { } running) _ = Observe(running);
        if (smokeOutput is null) _ = PollAsync(async () =>
        {
            if (currentJob is not null) return;
            var recent = await api.JobsAsync(ct);
            if (recent.Active is { } active) await Observe(active);
            else await LoadSaved();
        }, TimeSpan.FromSeconds(5), ct);
    }
    async Task ChatAsync(CancellationToken ct)
    {
        PageContent.Children.Add(Heading(T("对话", "Chat")));
        var model = new ModelPicker(await api.GetAsync<JsonElement>("/api/v1/models", ct)); PageContent.Children.Add(model);
        var metadata = Text(""); var history = Stack(); var message = Input(T("消息 · Ctrl+Enter 发送", "Message · Ctrl+Enter to send"), multi: true); message.MinHeight = 100;
        var stats = new Expander { Header = T("会话统计", "Session statistics"), HorizontalAlignment = HorizontalAlignment.Stretch };
        Task? sending = null; ChatContext? authoritativeContext = null; long draftRevision = 0; bool clearingForSend = false;
        message.TextChanging += (sender, args) => { if (!clearingForSend) draftRevision++; };
        void Display(ChatContext context)
        {
            authoritativeContext = context;
            history.Children.Clear();
            metadata.Text = $"{T("会话版本", "Session revision")}: {context.ContextVersion} · {T("行动计划上下文", "Action-plan context")}: {context.HasActionPlanContext}";
            foreach (var item in context.Messages ?? []) history.Children.Add(Card(Stack(Text(item.Role == "user" ? T("你", "You") : "Vantage", 12), MarkdownView.Create(item.Content), ActionButton(T("复制", "Copy"), () => { NativeDesktop.Copy(item.Content); return Task.CompletedTask; }))));
            stats.Content = context.Stats is { } value ? DataView(value) : Text(T("还没有统计", "No statistics yet"));
        }
        async Task Refresh() => Display(await api.ChatContextAsync(ct));
        async Task Send()
        {
            if (sending is { IsCompleted: false } || string.IsNullOrWhiteSpace(message.Text)) return;
            if (authoritativeContext is null) { Status(T("会话正在加载，请稍后发送", "The session is loading; try sending once it is ready")); return; }
            var text = message.Text; var sentContextVersion = authoritativeContext.ContextVersion; var sentDraftRevision = draftRevision;
            clearingForSend = true; try { message.Text = ""; } finally { clearingForSend = false; }
            chatLifetime?.Dispose(); chatLifetime = CancellationTokenSource.CreateLinkedTokenSource(ct); var streamCt = chatLifetime.Token;
            history.Children.Add(Card(Stack(Text(T("你", "You")), MarkdownView.Create(text))));
            var response = Text(""); var thinking = Text("");
            history.Children.Add(Card(Stack(Text("Vantage"), response, new Expander { Header = T("推理", "Reasoning"), Content = thinking })));
            var state = new ChatStreamState(); var failed = false;
            async Task Stream()
            {
                try
                {
                    await foreach (var e in api.ChatAsync(new(text, model.Model, model.Route, model.Reasoning, model.Tier, DateTimeOffset.UtcNow.ToString("O")), streamCt))
                    { state.Apply(e); response.Text = state.Content; thinking.Text = state.Thinking; }
                    state.RequireSuccess();
                }
                catch (OperationCanceledException) when (streamCt.IsCancellationRequested) { failed = true; Status(T("已停止对话请求", "Chat request stopped")); }
                catch (Exception e) { failed = true; ShowError(e); }
                finally
                {
                    if (!ct.IsCancellationRequested)
                    {
                        try
                        {
                            var latest = await api.ChatContextAsync(ct);
                            if (DraftRecovery.ShouldRestore(failed, sentContextVersion, latest.ContextVersion, message.Text, sentDraftRevision, draftRevision)) message.Text = text;
                            Display(latest);
                        }
                        catch (Exception e) { ShowError(e); }
                    }
                }
            }
            sending = Stream(); await sending;
        }
        async Task Transcribe(string path)
        {
            if (transcriptionTask is { IsCompleted: false }) throw new InvalidOperationException(T("转录正在进行", "A transcription is already running"));
            transcriptionLifetime?.Dispose(); transcriptionLifetime = CancellationTokenSource.CreateLinkedTokenSource(ct); var uploadCt = transcriptionLifetime.Token;
            async Task Upload()
            {
                await using var audio = File.OpenRead(path); var result = await api.TranscribeAsync(audio, Path.GetFileName(path), uploadCt);
                uploadCt.ThrowIfCancellationRequested(); message.Text = result.Transcription ?? "";
                Status(T("转录已填入消息，可检查后发送", "Transcription is ready to review and send"));
            }
            transcriptionTask = Upload(); await transcriptionTask;
        }
        var recordingState = Text(T("录音未开始", "Not recording")); DateTimeOffset recordedAt = default;
        var record = ActionButton(T("录音 / 停止并转录", "Record / stop and transcribe"), async () =>
        {
            if (!recorder.IsRecording) { await recorder.StartAsync(); recordedAt = DateTimeOffset.Now; Status(T("正在录音，点击同一按钮停止并转录", "Recording; click again to stop and transcribe")); }
            else { try { await Transcribe(await recorder.StopAsync()); } finally { await recorder.DisposeAsync(); } }
        });
        var send = ActionButton(T("发送", "Send"), Send);
        var key = new KeyboardAccelerator { Key = VirtualKey.Enter, Modifiers = VirtualKeyModifiers.Control }; key.Invoked += async (_, e) => { e.Handled = true; await Send(); }; message.KeyboardAccelerators.Add(key);
        PageContent.Children.Add(Row(ActionButton(T("刷新会话", "Reload session"), Refresh), ActionButton(T("清空对话", "Clear chat"), async () =>
        {
            if (!await ConfirmAsync(T("清空对话", "Clear chat"), T("清空已保存的对话历史？行动计划上下文会保留。", "Clear saved messages? The action-plan context is retained."))) return;
            chatLifetime?.Cancel(); if (sending is not null) await sending;
            Display(await api.ClearChatAsync(ct));
        })));
        PageContent.Children.Add(metadata); PageContent.Children.Add(history); PageContent.Children.Add(stats); PageContent.Children.Add(message);
        PageContent.Children.Add(Row(send, ActionButton(T("停止", "Stop"), () => { chatLifetime?.Cancel(); return Task.CompletedTask; }), record,
            ActionButton(T("音频文件转录", "Transcribe audio file"), async () => { var path = await NativeDesktop.PickAudioAsync(this); if (path is not null) await Transcribe(path); })));
        PageContent.Children.Add(Row(recordingState, ActionButton(T("取消并删除录音", "Discard recording"), async () => { await StopAudioAsync(); recordingState.Text = T("录音已删除", "Recording discarded"); })));
        if (smokeOutput is null) _ = PollAsync(async () =>
        {
            if (!recorder.IsRecording) { recordingState.Text = T("录音未开始", "Not recording"); return; }
            var elapsed = DateTimeOffset.Now - recordedAt; recordingState.Text = T("正在录音 ", "Recording ") + elapsed.ToString(@"mm\:ss");
            if (elapsed >= TimeSpan.FromMinutes(5)) { await recorder.DisposeAsync(); Status(T("录音达到5分钟上限，已停止并删除临时文件", "Recording reached its five-minute limit and was stopped; the temporary file was deleted")); }
        }, TimeSpan.FromSeconds(1), ct);
        PageContent.Children.Add(Text(T("音频由共享后端发送到已配置的语音服务。录音只在点击后开始，临时录音转录后删除。", "Audio is sent through the shared backend to your configured voice provider. Recording starts only when clicked; temporary recordings are deleted after transcription.")));
        await Refresh();
    }
}
