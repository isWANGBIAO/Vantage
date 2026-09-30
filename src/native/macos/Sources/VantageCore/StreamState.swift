import Foundation

/// Observation state is not job ownership. EOF never marks a job successful.
public struct PlanStreamState: Sendable {
    public private(set) var cursor = 0
    public private(set) var analysis = ""
    public private(set) var plan = ""
    public private(set) var thinking = ""
    public private(set) var lastLog = ""
    public private(set) var needsSnapshot = false
    public private(set) var completionObserved = false
    public private(set) var failure: String?
    private var receivedBytes = 0
    public static let maximumTextBytes = 4_194_304
    public init() {}
    public mutating func apply(_ event: StreamEvent) {
        if event.truncated == true || event.event_truncated == true {
            analysis = ""; plan = ""; thinking = ""; needsSnapshot = true
            cursor = max(cursor, event.cursor ?? event.sequence ?? cursor); return
        }
        if let sequence = event.sequence { guard sequence > cursor else { return }; cursor = sequence }
        if let error = event.error { failure = SensitiveText.redact(error) }
        if event.done == true && event.job_status == .succeeded { completionObserved = true }
        guard let log = event.log else { return }
        for (prefix, section) in [("STREAM_ANALYSIS_CONTENT:", "analysis"), ("STREAM_PLAN_CONTENT:", "plan"), ("STREAM_ANALYSIS_THINKING:", "thinking"), ("STREAM_PLAN_THINKING:", "thinking")] where log.hasPrefix(prefix) {
            guard !needsSnapshot else { return }
            let text = decodeStreamPayload(String(log.dropFirst(prefix.count)))
            receivedBytes += text.utf8.count
            if receivedBytes > Self.maximumTextBytes {
                analysis = ""; plan = ""; thinking = ""; needsSnapshot = true
                lastLog = "Progress display limit reached; waiting for the complete saved result."; return
            }
            if section == "analysis" { analysis += text } else if section == "plan" { plan += text } else { thinking += text }
            return
        }
        if log.hasPrefix("STREAM_ERROR:") || log.hasPrefix("STREAM_ANALYSIS_ERROR:") || log.hasPrefix("STREAM_PLAN_ERROR:") { failure = SensitiveText.redact(log) }
        // Do not expose backend SYSTEM/PROMPT records in a progress label.
        if !log.hasPrefix("STREAM_") { lastLog = String(SensitiveText.redact(log).prefix(4096)) }
    }
}
public func decodeStreamPayload(_ raw: String) -> String {
    if let data = raw.data(using: .utf8), let decoded = try? JSONDecoder().decode(String.self, from: data) { return SensitiveText.redact(decoded) }
    return SensitiveText.redact(raw)
}
public struct ChatStreamState: Sendable {
    public private(set) var content = ""
    public private(set) var thinking = ""
    public private(set) var stats: JSONValue?
    public private(set) var done = false
    public private(set) var failure: String?
    private var receivedBytes = 0
    public static let maximumTextBytes = 4_194_304
    public init() {}
    public mutating func apply(_ event: StreamEvent) {
        if let error = event.error { failure = SensitiveText.redact(error) }
        if event.done == true { done = true }
        guard let log = event.log else { return }
        for prefix in ["STREAM_CONTENT:", "STREAM_THINKING:", "STREAM_ERROR:", "STATS_JSON:"] where log.hasPrefix(prefix) {
            let raw = String(log.dropFirst(prefix.count))
            if prefix == "STREAM_CONTENT:" || prefix == "STREAM_THINKING:" {
                guard failure == nil else { return }
                receivedBytes += raw.utf8.count
                guard receivedBytes <= Self.maximumTextBytes else { failure = "Reply exceeded the display limit. Reload the saved conversation."; return }
            }
            switch prefix {
            case "STREAM_CONTENT:": content += decodeStreamPayload(raw)
            case "STREAM_THINKING:": thinking += decodeStreamPayload(raw)
            case "STREAM_ERROR:": failure = decodeStreamPayload(raw)
            default: stats = raw.data(using: .utf8).flatMap { try? JSONDecoder().decode(JSONValue.self, from: $0) }
            }
        }
    }
}
