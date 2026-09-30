import Foundation

public struct NativeChartPoint: Identifiable, Sendable {
    public let id: String
    public let series: String
    public let segment: Int
    public let x: Double
    public let label: String
    public let y: Double
    public let kind: String
    public let axis: Int
    public let stack: String
}
public struct NativeChartSeries: Identifiable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let axis: Int
    public let stack: String
    public let points: [NativeChartPoint]
}
/// ECharts is a backend data contract, not a rendering dependency. Normalize
/// numbers, [x,y], {value:...}, null gaps, time/category axes without flattening units.
public enum ChartData {
    public static func series(_ option: JSONValue) -> [NativeChartSeries] {
        let axis = option["xAxis"].array.first ?? option["xAxis"]
        let categories = axis["data"].array.map(\.string)
        let time = axis["type"].string == "time"
        return option["series"].array.enumerated().map { seriesIndex, series in
            let name = series["name"].string.isEmpty ? "Series \(seriesIndex + 1)" : series["name"].string
            let type = series["type"].string
            let axis = Int(series["yAxisIndex"].double ?? 0)
            let stack = series["stack"].string
            var segment = 0
            let points: [NativeChartPoint] = series["data"].array.enumerated().compactMap { index, item in
                let value = item.object["value"] ?? item
                let pair = value.array
                let y = pair.count >= 2 ? pair[1].double : value.double
                guard let y, y.isFinite else { segment += 1; return nil }
                let xValue = pair.count >= 2 ? pair[0] : .number(Double(index))
                let label = !item["name"].string.isEmpty ? item["name"].string : pair.count >= 2 ? xValue.string : categories.indices.contains(index) ? categories[index] : String(index + 1)
                let x = time ? timestamp(xValue) ?? Double(index) : pair.count >= 2 ? xValue.double ?? Double(index) : Double(index)
                return NativeChartPoint(id: "\(seriesIndex)-\(index)", series: name, segment: segment, x: x, label: label, y: y, kind: type, axis: axis, stack: stack)
            }
            return NativeChartSeries(id: String(seriesIndex), name: name, type: type, axis: axis, stack: stack, points: points)
        }
    }
    public static func timestamp(_ value: JSONValue) -> Double? {
        if let number = value.double { return number > 10_000_000_000 ? number / 1000 : number }
        let string = value.string
        let iso = ISO8601DateFormatter(); iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: string) { return date.timeIntervalSince1970 }
        iso.formatOptions = [.withInternetDateTime]
        if let date = iso.date(from: string) { return date.timeIntervalSince1970 }
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.timeZone = TimeZone(secondsFromGMT: 0)
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: string) { return date.timeIntervalSince1970 }
        }
        return nil
    }
}

public enum ChartFormatting {
    public static func dateTick(_ timestamp: Double) -> String {
        let formatter = DateFormatter(); formatter.locale = .current; formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.setLocalizedDateFormatFromTemplate("MMMd")
        return formatter.string(from: Date(timeIntervalSince1970: timestamp))
    }
    public static func value(_ value: Double, kind: String = "", name: String = "") -> String {
        let name = name.lowercased()
        if kind == "clock" || kind == "sleep-schedule" {
            let total = ((Int((value * 60).rounded()) % 1440) + 1440) % 1440
            return String(format: "%02d:%02d", total / 60, total % 60)
        }
        if kind == "pace" || name.contains("配速") || name.contains("pace") {
            let seconds = Int((value * 60).rounded())
            return String(format: "%d:%02d /km", seconds / 60, abs(seconds % 60))
        }
        if kind == "currency" || name.contains("¥") || name.contains("余额") || name.contains("资产") || name.contains("支出") || name.contains("expense") || name.contains("income") {
            return value.formatted(.currency(code: "CNY").precision(.fractionLength(0...1)))
        }
        if kind == "duration" || kind == "hours" { let minutes = Int((value * 60).rounded()); return "\(minutes / 60)h \(abs(minutes % 60))m" }
        if kind == "percent" || name.contains("%") || name.contains("体脂") { return value.formatted(.number.precision(.fractionLength(0...1))) + "%" }
        if kind == "days" { return value.formatted(.number.precision(.fractionLength(0...1))) + " d" }
        return value.formatted(.number.precision(.fractionLength(0...2)))
    }
    public static func summary(_ item: JSONValue) -> String {
        if !item["text"].string.isEmpty { return item["text"].string }
        let value = item["value"]
        let unit = item["unit"].string.isEmpty ? item["suffix"].string : item["unit"].string
        guard let numeric = value.double else { return value == .null ? "—" : value.string + (unit.isEmpty ? "" : " " + unit) }
        let kind = item["type"].string
        if !kind.isEmpty { return self.value(numeric, kind: kind) }
        if ["¥", "元"].contains(unit) { return self.value(numeric, kind: "currency") }
        if ["小时", "Hours"].contains(unit) { return self.value(numeric, kind: "duration") }
        let precision = Int(item["precision"].double ?? 1)
        return numeric.formatted(.number.precision(.fractionLength(0...max(0, min(precision, 8))))) + (unit.isEmpty ? "" : " " + unit)
    }
}

/// Keep the plotted coordinates ascending even for inverse axes. Labels/tooltips
/// use original values, so an explicit 0…20 inverse axis places 0 at the top.
public struct ChartAxis: Sendable {
    public let inverse: Bool
    public let includesZero: Bool
    public let bounds: ClosedRange<Double>?
    public init(_ configuration: JSONValue) {
        inverse = configuration["inverse"].bool ?? false
        includesZero = configuration["scale"].bool != true
        if let minimum = configuration["min"].double, let maximum = configuration["max"].double, maximum > minimum {
            bounds = inverse ? (-maximum)...(-minimum) : minimum...maximum
        } else { bounds = nil }
    }
    public func coordinate(_ value: Double) -> Double { inverse ? -value : value }
    public func value(_ coordinate: Double) -> Double { inverse ? -coordinate : coordinate }
}
