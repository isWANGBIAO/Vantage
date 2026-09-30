import SwiftUI
import VantageCore

struct BackendChart: View {
    let chart: JSONValue
    @State private var selectedSeries = ""
    @State private var showData = false
    private var series: [NativeChartSeries] { ChartData.series(chart["option"]) }
    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                Text(chart["description"].string).foregroundStyle(.secondary)
                if chart["empty"].bool == true { Text(chart["error"].string).foregroundStyle(.secondary) }
                else if chart["option"]["series"].array.contains(where: { $0["type"].string == "radar" }) { RadarChart(option: chart["option"]) }
                else {
                    if series.count > 1 {
                        Picker("Series", selection: $selectedSeries) { Text("All series").tag(""); ForEach(series) { Text($0.name).tag($0.id) } }.pickerStyle(.menu)
                    }
                    ForEach(Array(Set(series.map(\.axis))).sorted(), id: \.self) { axis in
                        let matching = series.filter { $0.axis == axis && (selectedSeries.isEmpty || selectedSeries == $0.id) }
                        if !matching.isEmpty { NativeSeriesChart(series: matching, axisTitle: axisName(axis), axisConfiguration: axisValue(axis), formatter: chart["formatter"].string, timeAxis: xAxis["type"].string == "time", categoryAxis: xAxis["type"].string != "time" && xAxis["type"].string != "value") }
                    }
                }
                HStack {
                    ForEach(Array(chart["summary"].array.enumerated()), id: \.offset) { _, summary in
                        VStack(alignment: .leading) { Text(summary["label"].string).font(.caption).foregroundStyle(.secondary); Text(ChartFormatting.summary(summary)).bold() }.padding(8).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                    }
                }
                DisclosureGroup("Data", isExpanded: $showData) {
                    ForEach(series) { series in
                        Text(series.name).font(.headline)
                        DynamicGrid(columns: ["x", "value"], rows: series.points.map { [.string($0.label), .number($0.y)] })
                    }
                }
            }.padding(8)
        } label: { Text(chart["title"].string).font(.title3.bold()) }
    }
    private var xAxis: JSONValue { chart["option"]["xAxis"].array.first ?? chart["option"]["xAxis"] }
    private func axisValue(_ index: Int) -> JSONValue {
        let axes = chart["option"]["yAxis"].array
        return axes.indices.contains(index) ? axes[index] : chart["option"]["yAxis"]
    }
    private func axisName(_ index: Int) -> String { axisValue(index)["name"].string }
}
struct NativeSeriesChart: View {
    let series: [NativeChartSeries]
    var axisTitle = ""
    var axisConfiguration: JSONValue = .null
    var formatter = ""
    var timeAxis = false
    var categoryAxis = true
    @State private var selectedX: Double?
    @State private var zoom = 100.0
    @State private var pan = 1.0
    private var points: [NativeChartPoint] { series.flatMap(\.points) }
    private let colors: [Color] = [.teal, .blue, .orange, .purple, .pink, .green, .red, .indigo]
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !axisTitle.isEmpty { Text(axisTitle).font(.caption).foregroundStyle(.secondary) }
            CPUChart(series: series, configuration: axisConfiguration, formatter: formatter, axisTitle: axisTitle, timeAxis: timeAxis, categoryAxis: categoryAxis, zoom: zoom, pan: pan, selectedX: $selectedX)
                .frame(height: 280).clipShape(RoundedRectangle(cornerRadius: 6))
            if !series.allSatisfy({ $0.type == "pie" }) {
                HStack {
                    ForEach(Array(series.enumerated()), id: \.element.id) { index, item in Label(item.name, systemImage: "circle.fill").font(.caption).foregroundStyle(colors[index % colors.count]) }
                }
                HStack { Text("Zoom").font(.caption); Slider(value: $zoom, in: 5...100); Text("\(Int(zoom))%").font(.caption.monospacedDigit()) }
                if zoom < 100 { HStack { Text("Position").font(.caption); Slider(value: $pan, in: 0...1) } }
                if let selectedX, let nearest = points.min(by: { abs($0.x - selectedX) < abs($1.x - selectedX) }) {
                    Text(nearest.label).font(.caption.bold())
                    ForEach(points.filter { abs($0.x - nearest.x) < 0.0001 }) { point in
                        Text(point.series + ": " + ChartFormatting.value(point.y, kind: formatter, name: point.series)).font(.caption)
                    }
                }
            }
        }
    }
}
struct RadarChart: View {
    let option: JSONValue
    private let colors: [Color] = [.teal, .blue, .orange, .purple, .pink, .green, .red, .indigo]
    var body: some View {
        let indicators = option["radar"]["indicator"].array
        let entries = option["series"].array.flatMap { $0["data"].array }
        VStack {
            CPURadarChart(option: option).frame(height: 340).clipShape(RoundedRectangle(cornerRadius: 6))
            HStack { ForEach(Array(entries.enumerated()), id: \.offset) { index, entry in Label(entry["name"].string, systemImage: "circle.fill").foregroundStyle(colors[index % colors.count]).font(.caption) } }
            DynamicGrid(columns: ["Series"] + indicators.map { $0["name"].string }, rows: entries.map { [.string($0["name"].string)] + $0["value"].array })
        }
    }
}
struct ValuesChart: View {
    let rows: [JSONValue]
    var xKey = "date"
    var keys: [String] = []
    var body: some View {
        let numericKeys = keys.isEmpty ? Array(Set(rows.flatMap { row in row.object.filter { $0.value.double != nil && $0.key != xKey }.map(\.key) })).sorted() : keys
        if !rows.isEmpty, !numericKeys.isEmpty {
            let x = rows.map { $0[xKey].string }
            let timed = !x.isEmpty && rows.allSatisfy { ChartData.timestamp($0[xKey]) != nil }
            let series = numericKeys.map { key in JSONValue.object(["name": .string(key), "type": .string("line"), "data": .array(rows.map { row in timed ? .array([row[xKey], row[key]]) : row[key] })]) }
            NativeSeriesChart(series: ChartData.series(.object(["xAxis": .object(["type": .string(timed ? "time" : "category"), "data": .array(x.map(JSONValue.string))]), "series": .array(series)])), timeAxis: timed, categoryAxis: !timed)
        }
    }
}
struct DynamicGrid: View {
    let columns: [String]
    let rows: [[JSONValue]]
    @State private var query = ""
    @State private var limit = 100
    var filtered: [[JSONValue]] { query.isEmpty ? rows : rows.filter { $0.contains { $0.string.localizedCaseInsensitiveContains(query) } } }
    var body: some View {
        VStack(alignment: .leading) {
            HStack { TextField("Filter rows", text: $query).textFieldStyle(.roundedBorder).frame(maxWidth: 280); Text("\(filtered.count) rows").font(.caption).foregroundStyle(.secondary) }
            ScrollView(.horizontal) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 0) { ForEach(Array(columns.enumerated()), id: \.offset) { _, column in Text(column).font(.caption.bold()).frame(width: 165, alignment: .leading).padding(8).background(.quaternary) } }
                    ForEach(Array(filtered.prefix(limit).enumerated()), id: \.offset) { index, row in
                        HStack(spacing: 0) { ForEach(Array(columns.enumerated()), id: \.offset) { cell, _ in Text(row.indices.contains(cell) ? row[cell].string : "—").font(.caption).frame(width: 165, alignment: .leading).padding(8).background(index.isMultiple(of: 2) ? Color.secondary.opacity(0.035) : Color.clear) } }
                    }
                }.textSelection(.enabled)
            }
            if filtered.count > limit { Button("Show more") { limit += 100 } }
        }
    }
}
