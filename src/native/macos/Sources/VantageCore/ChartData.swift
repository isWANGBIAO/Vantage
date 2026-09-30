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
