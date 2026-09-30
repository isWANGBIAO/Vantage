import Foundation

public struct PlotBar: Sendable, Equatable {
    public let start: Double
    public let end: Double
    public let group: String
}
/// CPU chart geometry shared by drawing and tests. Values stay in data space;
/// inverse axes transform coordinates only, never the source data or labels.
public struct PlotLayout: Sendable {
    public let bars: [String: PlotBar]
    public let xBounds: ClosedRange<Double>
    public let yBounds: ClosedRange<Double>
    public let barGroups: [String]
    public init(points: [NativeChartPoint], configuration: JSONValue) {
        let axis = ChartAxis(configuration)
        var bars: [String: PlotBar] = [:]
        var stacks: [String: Double] = [:]
        var groups: [String] = []
        var yValues = points.map { axis.coordinate($0.y) }
        for point in points where point.kind == "bar" {
            let group = point.stack.isEmpty ? point.series : point.stack
            if !groups.contains(group) { groups.append(group) }
            let key = "\(point.x)|\(group)|\(point.y < 0 ? "negative" : "positive")"
            let start = point.stack.isEmpty ? 0 : stacks[key, default: 0]
            let end = start + point.y
            if !point.stack.isEmpty { stacks[key] = end }
            let bar = PlotBar(start: axis.coordinate(start), end: axis.coordinate(end), group: group)
            bars[point.id] = bar; yValues += [bar.start, bar.end]
        }
        self.bars = bars; barGroups = groups
        let xs = points.map(\.x)
        let lowX = xs.min() ?? 0; let highX = xs.max() ?? 1
        let xPadding = highX > lowX ? (highX - lowX) * (bars.isEmpty ? 0.025 : 0.08) : 0.5
        xBounds = (lowX - xPadding)...(highX + xPadding)
        if axis.includesZero { yValues.append(0) }
        let low = yValues.min() ?? 0; let high = yValues.max() ?? 1
        let padding = high > low ? (high - low) * 0.08 : max(abs(high) * 0.05, 1)
        var lower = low - padding; var upper = high + padding
        if let minimum = configuration["min"].double { if axis.inverse { upper = -minimum } else { lower = minimum } }
        if let maximum = configuration["max"].double { if axis.inverse { lower = -maximum } else { upper = maximum } }
        yBounds = lower < upper ? lower...upper : (lower - 1)...(lower + 1)
    }
    public func visibleX(zoom: Double, pan: Double) -> ClosedRange<Double> {
        let full = xBounds.upperBound - xBounds.lowerBound
        let visible = full * min(max(zoom, 0.05), 1)
        let lower = xBounds.lowerBound + (full - visible) * min(max(pan, 0), 1)
        return lower...(lower + visible)
    }
}
