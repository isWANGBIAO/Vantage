import SwiftUI
import AppKit
import VantageCore

private let chartColors: [NSColor] = [.systemTeal, .systemBlue, .systemOrange, .systemPurple, .systemPink, .systemGreen, .systemRed, .systemIndigo]

/// A real AppKit CPU/CoreGraphics plot. No Swift Charts/Metal pipeline is used,
/// including on computers without a Metal-capable device. Receives live data.
struct CPUChart: NSViewRepresentable {
    let series: [NativeChartSeries]
    let configuration: JSONValue
    let formatter: String
    let axisTitle: String
    let timeAxis: Bool
    let zoom: Double
    let pan: Double
    @Binding var selectedX: Double?
    func makeNSView(context: Context) -> CPUPlotView { CPUPlotView() }
    func updateNSView(_ view: CPUPlotView, context: Context) {
        view.series = series; view.configuration = configuration; view.formatter = formatter
        view.axisTitle = axisTitle; view.timeAxis = timeAxis; view.zoom = zoom; view.pan = pan
        view.selectedX = selectedX; view.onSelection = { selectedX = $0 }; view.needsDisplay = true
        view.setAccessibilityLabel("Chart: " + series.map(\.name).joined(separator: ", ") + ". " + axisTitle)
    }
}
final class CPUPlotView: NSView {
    var series: [NativeChartSeries] = []
    var configuration: JSONValue = .null
    var formatter = ""
    var axisTitle = ""
    var timeAxis = false
    var zoom = 100.0
    var pan = 1.0
    var selectedX: Double?
    var onSelection: ((Double?) -> Void)?
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override var isOpaque: Bool { true }
    private var plot: CGRect { CGRect(x: 76, y: 14, width: max(1, bounds.width - 96), height: max(1, bounds.height - 59)) }
    private var points: [NativeChartPoint] { series.flatMap(\.points) }
    private var layout: PlotLayout { PlotLayout(points: points, configuration: configuration) }
    override init(frame frameRect: NSRect) { super.init(frame: frameRect); wantsLayer = false; setAccessibilityRole(.image) }
    required init?(coder: NSCoder) { super.init(coder: coder); wantsLayer = false; setAccessibilityRole(.image) }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseMoved, .mouseExited, .activeInKeyWindow, .inVisibleRect], owner: self, userInfo: nil))
    }
    override func mouseMoved(with event: NSEvent) { select(event) }
    override func mouseDown(with event: NSEvent) { window?.makeFirstResponder(self); select(event) }
    override func mouseExited(with event: NSEvent) { onSelection?(nil); toolTip = nil }
    override func keyDown(with event: NSEvent) {
        let ordered = Array(Set(points.map(\.x))).sorted()
        guard !ordered.isEmpty else { return }
        let current = ordered.firstIndex(of: selectedX ?? ordered[0]) ?? 0
        if event.keyCode == 123 { onSelection?(ordered[max(0, current - 1)]) }
        else if event.keyCode == 124 { onSelection?(ordered[min(ordered.count - 1, current + 1)]) }
        else { super.keyDown(with: event) }
    }
    private func select(_ event: NSEvent) {
        let position = convert(event.locationInWindow, from: nil)
        guard plot.contains(position), !points.isEmpty else { return }
        let domain = layout.visibleX(zoom: zoom / 100, pan: pan)
        let value = domain.lowerBound + (position.x - plot.minX) / plot.width * (domain.upperBound - domain.lowerBound)
        let nearest = points.min { abs($0.x - value) < abs($1.x - value) }
        onSelection?(nearest?.x)
        if let nearest { toolTip = nearest.label + " · " + nearest.series + ": " + ChartFormatting.value(nearest.y, kind: formatter, name: nearest.series) }
    }
    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState(); defer { context.restoreGState() }
        context.setFillColor(NSColor.controlBackgroundColor.cgColor); context.fill(bounds)
        context.setShouldAntialias(true)
        guard !points.isEmpty else { drawText("No data", in: bounds.insetBy(dx: 20, dy: 20)); return }
        if series.allSatisfy({ $0.type == "pie" }) { drawPie(context); return }
        let layout = self.layout; let axis = ChartAxis(configuration)
        let xDomain = layout.visibleX(zoom: zoom / 100, pan: pan)
        let yDomain = layout.yBounds; let plot = self.plot
        func x(_ value: Double) -> CGFloat { plot.minX + (value - xDomain.lowerBound) / (xDomain.upperBound - xDomain.lowerBound) * plot.width }
        func y(_ coordinate: Double) -> CGFloat { plot.maxY - (coordinate - yDomain.lowerBound) / (yDomain.upperBound - yDomain.lowerBound) * plot.height }
        for index in 0...4 {
            let fraction = Double(index) / 4
            let ordinate = yDomain.lowerBound + fraction * (yDomain.upperBound - yDomain.lowerBound)
            let row = y(ordinate)
            stroke(context, from: CGPoint(x: plot.minX, y: row), to: CGPoint(x: plot.maxX, y: row), color: .separatorColor, width: 0.5)
            drawText(ChartFormatting.value(axis.value(ordinate), kind: formatter, name: axisTitle), in: CGRect(x: 0, y: row - 8, width: 67, height: 18), alignment: .right)
            let abscissa = xDomain.lowerBound + fraction * (xDomain.upperBound - xDomain.lowerBound)
            let label = timeAxis ? ChartFormatting.dateTick(abscissa, includeTime: points.contains(where: { $0.label.contains(":") }) && xDomain.upperBound - xDomain.lowerBound < 172800) : points.min(by: { abs($0.x - abscissa) < abs($1.x - abscissa) })?.label ?? ""
            drawText(label, in: CGRect(x: x(abscissa) - 43, y: plot.maxY + 10, width: 86, height: 30), alignment: .center)
        }
        stroke(context, from: CGPoint(x: plot.minX, y: plot.minY), to: CGPoint(x: plot.minX, y: plot.maxY), color: .secondaryLabelColor)
        stroke(context, from: CGPoint(x: plot.minX, y: plot.maxY), to: CGPoint(x: plot.maxX, y: plot.maxY), color: .secondaryLabelColor)
        context.saveGState(); context.clip(to: plot)
        let allX = Array(Set(points.map(\.x))).sorted()
        let step = zip(allX, allX.dropFirst()).map { pair in pair.1 - pair.0 }.filter { $0 > 0 }.min() ?? (xDomain.upperBound - xDomain.lowerBound)
        let groupWidth = min(64, max(2, (x(step + xDomain.lowerBound) - x(xDomain.lowerBound)) * 0.72))
        let barWidth = groupWidth / Double(max(layout.barGroups.count, 1))
        for (seriesIndex, item) in series.enumerated() {
            let color = chartColors[seriesIndex % chartColors.count]
            if item.type == "bar" {
                for point in item.points {
                    guard let bar = layout.bars[point.id] else { continue }
                    let group = layout.barGroups.firstIndex(of: bar.group) ?? 0
                    let rectangle = CGRect(x: x(point.x) - groupWidth / 2 + Double(group) * barWidth, y: min(y(bar.start), y(bar.end)), width: max(1, barWidth - 1), height: max(0.7, abs(y(bar.start) - y(bar.end))))
                    context.setFillColor(color.withAlphaComponent(0.85).cgColor); context.fill(rectangle)
                }
            } else if item.type == "scatter" {
                context.setFillColor(color.cgColor)
                for point in item.points { context.fillEllipse(in: CGRect(x: x(point.x) - 3.5, y: y(axis.coordinate(point.y)) - 3.5, width: 7, height: 7)) }
            } else {
                context.setStrokeColor(color.cgColor); context.setLineWidth(2)
                var segment: Int?; context.beginPath()
                for point in item.points {
                    let position = CGPoint(x: x(point.x), y: y(axis.coordinate(point.y)))
                    if segment != point.segment { if segment != nil { context.strokePath(); context.beginPath() }; context.move(to: position); segment = point.segment }
                    else { context.addLine(to: position) }
                }
                context.strokePath()
                context.setFillColor(color.cgColor)
                for point in item.isolatedPoints {
                    context.fillEllipse(in: CGRect(x: x(point.x) - 3, y: y(axis.coordinate(point.y)) - 3, width: 6, height: 6))
                }
            }
        }
        if let selectedX {
            stroke(context, from: CGPoint(x: x(selectedX), y: plot.minY), to: CGPoint(x: x(selectedX), y: plot.maxY), color: .labelColor, width: 1)
        }
        context.restoreGState()
    }
    private func drawPie(_ context: CGContext) {
        let values = points.filter { $0.y > 0 }; let total = values.reduce(0) { $0 + $1.y }
        guard total > 0 else { return }
        let radius = min(bounds.width * 0.25, bounds.height * 0.42)
        let center = CGPoint(x: bounds.width * 0.36, y: bounds.height / 2)
        var angle = -Double.pi / 2
        for (index, point) in values.enumerated() {
            let next = angle + point.y / total * 2 * .pi
            context.beginPath(); context.move(to: center)
            context.addArc(center: center, radius: radius, startAngle: angle, endAngle: next, clockwise: false); context.closePath()
            context.setFillColor(chartColors[index % chartColors.count].cgColor); context.fillPath()
            let text = point.label + " · " + ChartFormatting.value(point.y, kind: formatter) + " (" + (point.y / total * 100).formatted(.number.precision(.fractionLength(0...1))) + "%)"
            drawText(text, in: CGRect(x: bounds.width * 0.64, y: 20 + Double(index) * 25, width: bounds.width * 0.35, height: 22))
            angle = next
        }
        context.setFillColor(NSColor.controlBackgroundColor.cgColor)
        context.fillEllipse(in: CGRect(x: center.x - radius * 0.48, y: center.y - radius * 0.48, width: radius * 0.96, height: radius * 0.96))
    }
}

struct CPURadarChart: NSViewRepresentable {
    let option: JSONValue
    func makeNSView(context: Context) -> CPURadarView { CPURadarView() }
    func updateNSView(_ view: CPURadarView, context: Context) { view.option = option; view.needsDisplay = true; view.setAccessibilityLabel("Radar chart. Full values are available in the data table.") }
}
final class CPURadarView: NSView {
    var option: JSONValue = .null
    override var isFlipped: Bool { true }
    override var isOpaque: Bool { true }
    override init(frame frameRect: NSRect) { super.init(frame: frameRect); wantsLayer = false; setAccessibilityRole(.image) }
    required init?(coder: NSCoder) { super.init(coder: coder); wantsLayer = false; setAccessibilityRole(.image) }
    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.saveGState(); defer { context.restoreGState() }
        context.setFillColor(NSColor.controlBackgroundColor.cgColor); context.fill(bounds); context.setShouldAntialias(true)
        let indicators = option["radar"]["indicator"].array
        let entries = option["series"].array.flatMap { $0["data"].array }
        guard indicators.count >= 3 else { drawText("No radar data", in: bounds.insetBy(dx: 20, dy: 20)); return }
        let center = CGPoint(x: bounds.midX, y: bounds.midY); let radius = min(bounds.width, bounds.height) * 0.34
        func point(_ index: Int, _ fraction: Double) -> CGPoint {
            let angle = Double(index) * 2 * .pi / Double(indicators.count) - .pi / 2
            return CGPoint(x: center.x + cos(angle) * radius * fraction, y: center.y + sin(angle) * radius * fraction)
        }
        for ring in 1...4 {
            context.beginPath()
            for index in indicators.indices { let position = point(index, Double(ring) / 4); if index == 0 { context.move(to: position) } else { context.addLine(to: position) } }
            context.closePath(); context.setStrokeColor(NSColor.separatorColor.cgColor); context.setLineWidth(0.7); context.strokePath()
        }
        for index in indicators.indices {
            stroke(context, from: center, to: point(index, 1), color: .separatorColor, width: 0.7)
            let label = point(index, 1.23)
            drawText(indicators[index]["name"].string, in: CGRect(x: label.x - 80, y: label.y - 11, width: 160, height: 28), alignment: .center)
        }
        for (entryIndex, entry) in entries.enumerated() {
            let values = entry["value"].array; guard values.count == indicators.count else { continue }
            let color = chartColors[entryIndex % chartColors.count]
            context.beginPath()
            for index in indicators.indices {
                let minimum = indicators[index]["min"].double ?? 0; let maximum = indicators[index]["max"].double ?? 1
                let fraction = maximum > minimum ? ((values[index].double ?? minimum) - minimum) / (maximum - minimum) : 0
                let position = point(index, min(max(fraction, 0), 1))
                if index == 0 { context.move(to: position) } else { context.addLine(to: position) }
            }
            context.closePath(); context.setFillColor(color.withAlphaComponent(0.14).cgColor); context.setStrokeColor(color.cgColor); context.setLineWidth(2); context.drawPath(using: .fillStroke)
        }
    }
}
private func stroke(_ context: CGContext, from: CGPoint, to: CGPoint, color: NSColor, width: Double = 1) {
    context.setStrokeColor(color.cgColor); context.setLineWidth(width); context.beginPath(); context.move(to: from); context.addLine(to: to); context.strokePath()
}
private func drawText(_ text: String, in rect: CGRect, alignment: NSTextAlignment = .left) {
    let paragraph = NSMutableParagraphStyle(); paragraph.alignment = alignment; paragraph.lineBreakMode = .byTruncatingTail
    (text as NSString).draw(in: rect, withAttributes: [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.secondaryLabelColor, .paragraphStyle: paragraph])
}
