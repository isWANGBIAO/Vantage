import SwiftUI
import Charts
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
                        if !matching.isEmpty { NativeSeriesChart(series: matching, axisTitle: axisName(axis), axisConfiguration: axisValue(axis), formatter: chart["formatter"].string, timeAxis: xAxis["type"].string == "time") }
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
    @State private var selectedX: Double?
    @State private var zoom = 100.0
    private var points: [NativeChartPoint] { series.flatMap(\.points) }
    private var axis: ChartAxis { ChartAxis(axisConfiguration) }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !axisTitle.isEmpty { Text(axisTitle).font(.caption).foregroundStyle(.secondary) }
            if series.allSatisfy({ $0.type == "pie" }) {
                Chart(points) { point in
                    SectorMark(angle: .value("Value", point.y), innerRadius: .ratio(0.48), angularInset: 2)
                        .foregroundStyle(by: .value("Category", point.label))
                        .annotation(position: .overlay) { Text(point.y.formatted(.number.precision(.fractionLength(0...1)))).font(.caption).foregroundStyle(.white) }
                }.frame(height: 260)
            } else {
                Chart(points) { point in
                    if point.kind == "bar" {
                        BarMark(x: .value("Date", point.x), y: .value("Value", axis.coordinate(point.y)), stacking: point.stack.isEmpty ? .unstacked : .standard)
                            .foregroundStyle(by: .value("Series", point.series))
                            .position(by: .value("Group", point.stack.isEmpty ? point.series : point.stack))
                    } else if point.kind == "scatter" {
                        PointMark(x: .value("Date", point.x), y: .value("Value", axis.coordinate(point.y))).foregroundStyle(by: .value("Series", point.series))
                    } else {
                        LineMark(x: .value("Date", point.x), y: .value("Value", axis.coordinate(point.y)), series: .value("Segment", "\(point.series)-\(point.segment)"))
                            .foregroundStyle(by: .value("Series", point.series))
                    }
                    if let selectedX, abs(point.x - selectedX) < 0.0001 { RuleMark(x: .value("Selected", selectedX)).foregroundStyle(.secondary).annotation(position: .top) { Text("\(point.label): \(point.y.formatted())").font(.caption) } }
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 5)) { axis in
                        AxisGridLine(); AxisTick()
                        AxisValueLabel {
                            if let value = axis.as(Double.self) {
                                if timeAxis { Text(ChartFormatting.dateTick(value)) }
                                else { Text(points.min(by: { abs($0.x - value) < abs($1.x - value) })?.label ?? "") }
                            }
                        }
                    }
                }
                .chartYAxis {
                    AxisMarks { axis in
                        AxisGridLine(); AxisTick()
                        AxisValueLabel { if let number = axis.as(Double.self) { Text(ChartFormatting.value(self.axis.value(number), kind: formatter, name: axisTitle)) } }
                    }
                }
                .modifier(NativeChartScale(configuration: axisConfiguration))
                .chartXSelection(value: $selectedX)
                .chartScrollableAxes(.horizontal)
                .chartXVisibleDomain(length: max(1, ((points.map(\.x).max() ?? 1) - (points.map(\.x).min() ?? 0)) * zoom / 100))
                .frame(height: 260)
                HStack { Text("Zoom").font(.caption); Slider(value: $zoom, in: 5...100); Text("\(Int(zoom))%").font(.caption.monospacedDigit()) }
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
    private let colors: [Color] = [.teal, .blue, .orange, .purple, .pink]
    var body: some View {
        let indicators = option["radar"]["indicator"].array
        let entries = option["series"].array.flatMap { $0["data"].array }
        VStack {
            Canvas { context, size in
                guard indicators.count >= 3 else { return }
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let radius = min(size.width, size.height) * 0.36
                func point(_ index: Int, _ fraction: Double) -> CGPoint {
                    let angle = Double(index) * 2 * .pi / Double(indicators.count) - .pi / 2
                    return CGPoint(x: center.x + cos(angle) * radius * fraction, y: center.y + sin(angle) * radius * fraction)
                }
                for ring in 1...4 {
                    var path = Path()
                    for index in indicators.indices { let p = point(index, Double(ring) / 4); if index == 0 { path.move(to: p) } else { path.addLine(to: p) } }
                    path.closeSubpath(); context.stroke(path, with: .color(.secondary.opacity(0.3)), lineWidth: 1)
                }
                for index in indicators.indices {
                    var path = Path(); path.move(to: center); path.addLine(to: point(index, 1)); context.stroke(path, with: .color(.secondary.opacity(0.3)))
                    context.draw(Text(indicators[index]["name"].string).font(.caption), at: point(index, 1.2))
                }
                for (entryIndex, entry) in entries.enumerated() {
                    let values = entry["value"].array
                    guard values.count == indicators.count else { continue }
                    var path = Path()
                    for index in indicators.indices {
                        let maximum = indicators[index]["max"].double ?? 1
                        let value = values[index].double ?? 0
                        let p = point(index, maximum > 0 ? min(max(value / maximum, 0), 1) : 0)
                        if index == 0 { path.move(to: p) } else { path.addLine(to: p) }
                    }
                    path.closeSubpath(); let color = colors[entryIndex % colors.count]
                    context.fill(path, with: .color(color.opacity(0.15))); context.stroke(path, with: .color(color), lineWidth: 2)
                }
            }.frame(height: 320)
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
            let series = numericKeys.map { key in JSONValue.object(["name": .string(key), "type": .string("line"), "data": .array(rows.map { $0[key] })]) }
            NativeSeriesChart(series: ChartData.series(.object(["xAxis": .object(["type": .string("category"), "data": .array(x.map(JSONValue.string))]), "series": .array(series)])))
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

private struct NativeChartScale: ViewModifier {
    let configuration: JSONValue
    @ViewBuilder func body(content: Content) -> some View {
        let axis = ChartAxis(configuration)
        if let bounds = axis.bounds { content.chartYScale(domain: bounds) }
        else { content.chartYScale(domain: .automatic(includesZero: axis.includesZero)) }
    }
}
