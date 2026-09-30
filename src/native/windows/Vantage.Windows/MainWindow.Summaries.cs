using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Vantage.Core;
using Vantage.Windows.Views;
namespace Vantage.Windows;
public sealed partial class MainWindow
{
    UIElement MetricGrid(IEnumerable<(string title, string value)> metrics)
    {
        var grid = new Grid { ColumnSpacing = 12, RowSpacing = 12 };
        for (int col = 0; col < 3; col++) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var i = 0;
        foreach (var (title, value) in metrics)
        {
            if (i % 3 == 0) grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var card = Card(Stack(Text(title, 13), Text(value, 24))); Grid.SetColumn(card, i % 3); Grid.SetRow(card, i / 3); grid.Children.Add(card); i++;
        }
        return grid;
    }
    string Amount(JsonElement value) => value.Number() is { } number ? $"¥{number:N2}" : T("未记录", "Not recorded");
    UIElement FinanceSummary(JsonElement summary)
    {
        var assets = summary.Field("assets"); var costs = summary.Field("time_cost"); var budget = summary.Field("budget");
        var section = Stack(Text(T("资产概览", "Asset overview"), 22), MetricGrid(new[] {
            (T("总资产", "Total assets"), Amount(assets.Field("total_assets").Field("value"))),
            (T("净资产", "Equity"), Amount(assets.Field("equity").Field("value"))),
            (T("负债", "Liabilities"), Amount(assets.Field("liabilities").Field("value"))),
            (T("流动资产", "Current assets"), Amount(assets.Field("current_assets").Field("value"))),
            (T("固定资产", "Fixed assets"), Amount(assets.Field("fixed_assets").Field("value"))),
            (T("现金与股票", "Cash and stocks"), Amount(assets.Field("cash_and_stock").Field("value"))) }),
            Text(T("消费与预算", "Spending and budget"), 22), MetricGrid(new[] {
                (T("日均支出", "Daily average"), Amount(costs.Field("daily_average"))),
                (T("本月支出", "Monthly spending"), Amount(costs.Field("monthly_total"))),
                (T("每分钟成本", "Cost per minute"), Amount(costs.Field("per_minute"))),
                (T("必要月预算", "Required monthly budget"), Amount(budget.Field("monthly_required"))),
                (T("可选月预算", "Optional monthly budget"), Amount(budget.Field("monthly_optional"))),
                (T("数据日期", "Source date"), costs.Field("latest_date").Text("—")) }),
            new Expander { Header = T("计算与来源明细", "Calculation and source details"), Content = DataView(summary), HorizontalAlignment = HorizontalAlignment.Stretch });
        return section;
    }
    UIElement UsageSummary(JsonElement summary)
    {
        string N(string key) => summary.Field(key).Number() is { } value ? value.ToString("N0") : T("未记录", "Not recorded");
        string Rate(string key) => summary.Field(key).Number() is { } value ? $"{value:N1} tok/s" : "—";
        var rate = summary.Field("prompt_cache_hit_rate").Number();
        return Stack(MetricGrid(new[] {
            (T("总 Token", "Total tokens"), N("total_tokens")), (T("输入 Token", "Input tokens"), N("prompt_tokens")), (T("输出 Token", "Output tokens"), N("completion_tokens")),
            (T("成功调用", "Completed calls"), N("completed_call_count")), (T("失败调用", "Failed calls"), N("failed_call_count")), (T("会话数", "Sessions"), N("session_count")),
            (T("缓存命中", "Cache hits"), N("prompt_cache_hit_tokens")), (T("缓存未命中", "Cache misses"), N("prompt_cache_miss_tokens")), (T("缓存命中率", "Cache hit rate"), rate is { } r ? $"{r:N1}%" : "—"),
            (T("输出速度", "Output speed"), Rate("output_tokens_per_second")), (T("总 Token 速度", "Total token speed"), Rate("average_tokens_per_second")), (T("推理 Token", "Reasoning tokens"), N("completion_reasoning_tokens")) }),
            new Expander { Header = T("调用时长与详细统计", "Duration and detailed statistics"), Content = DataView(summary), HorizontalAlignment = HorizontalAlignment.Stretch });
    }
    UIElement UsageSpeedChart(JsonElement rows)
    {
        var data = rows.Items().ToArray(); if (data.Length == 0) return Text(T("暂无速度记录", "No speed records"));
        var series = new List<object>();
        foreach (var group in data.GroupBy(x => x.Field("model").Text(T("未知模型", "Unknown model"))))
        {
            foreach (var (metric, label) in new[] { ("output_tokens_per_second", T("输出", "Output")), ("average_tokens_per_second", T("总计", "Total")) })
                series.Add(new { name = group.Key + " · " + label, type = "line", data = group.OrderBy(x => x.Field("created_at").Text()).Select(row => new object?[] { row.Field("created_at").Text(), row.Field(metric).Number() }).ToArray() });
        }
        return Stack(Text(T("逐调用速度趋势", "Per-call speed trend"), 22), new NativeChart(JsonData.Element(new { xAxis = new { type = "time" }, yAxis = new { type = "value", name = "tok/s" }, series }), English));
    }
}
