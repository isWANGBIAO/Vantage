import Foundation

/// Additive domain records (workbook cells / chart options) remain lossless.
public enum JSONValue: Codable, Equatable, Hashable, Sendable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    public subscript(_ key: String) -> JSONValue { object[key] ?? .null }
    public var object: [String: JSONValue] { if case .object(let v) = self { return v }; return [:] }
    public var array: [JSONValue] { if case .array(let v) = self { return v }; return [] }
    public var string: String {
        switch self { case .string(let v): return v; case .number(let v): return v.rounded() == v && abs(v) < 9_007_199_254_740_992 ? String(Int64(v)) : String(v); case .bool(let v): return String(v); default: return "" }
    }
    public var double: Double? { if case .number(let v) = self { return v }; return nil }
    public var bool: Bool? { if case .bool(let v) = self { return v }; return nil }
    public var pretty: String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return (try? String(data: encoder.encode(self), encoding: .utf8)) ?? ""
    }
    public static func encode<T: Encodable>(_ value: T) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
    }
}

public struct Capabilities: Decodable, Sendable {
    public let api_version: String
    public let service: String
    public let capabilities: [String]
    public func validate() throws {
        guard service == "vantage", api_version.split(separator: ".").first == "1",
              capabilities.contains("action-plan-jobs") else { throw APIError.incompatibleVersion(api_version) }
    }
}
public struct SettingsState: Codable, Sendable {
    public var settings: SettingsValues
    public var provider: ProviderState
    public var migration: JSONValue
    public var runtime_paths: [String: String]
}
public struct SettingsValues: Codable, Sendable {
    public var version: Int
    public var onboarding_completed: Bool
    public var launch_at_login: Bool
    public var display_language: String
    public var theme: String
    public var theme_mode: String
    public var action_plan_auto_generate: Bool
    public var action_plan_check_interval_minutes: Int
    public var voice_provider_mode: String
    public var voice_base_url: String
    public var voice_api_key: String
    public var voice_has_api_key: Bool
    public var voice_model: String
    public var voice_models: [String]
    public var voice_last_refreshed_at: String?
    public var image_provider_mode: String
    public var image_base_url: String
    public var image_api_key: String
    public var image_has_api_key: Bool
    public var image_model: String
    public var image_models: [String]
    public var image_last_refreshed_at: String?
}
public struct ProviderState: Codable, Sendable {
    public var version: Int
    public var selected_provider: String?
    public var sampling_defaults: [String: JSONValue]
    public var model_profiles: [String: JSONValue]
    public var providers: [String: Provider]
}
public struct Provider: Codable, Sendable {
    public var route: String
    public var name: String
    public var type: String
    public var enabled: Bool
    public var api_key: String
    public var base_url: String
    public var model: String
    public var models: [String]
    public var last_refreshed_at: String?
    public var context_window_tokens: Int?
    public var max_output_tokens: Int?
    public init(route: String) {
        self.route = route; name = route; type = "openai-compatible"; enabled = true
        api_key = ""; base_url = ""; model = ""; models = []
    }
}
public struct OnboardingState: Decodable, Sendable {
    public let completed: Bool
    public let launchAtLogin: Bool
    public let displayLanguage: String
    public let providerConfigured: Bool
    public let migrationCompleted: Bool
    public let legacyRoot: String?
}
public struct ModelOption: Codable, Identifiable, Sendable {
    public let id: String
    public let model: String
    public let provider_route: String
    public let label: String
    public let reasoning_tiers: [String]
    public let default_reasoning_effort: String?
    public let is_default: Bool?
}
public struct ModelCatalog: Decodable, Sendable {
    public let models: [String]
    public let model_options: [ModelOption]?
    public let default_model: String?
    public let default_provider_route: String?
}
public struct ActionPlanRequest: Codable, Sendable, Equatable {
    public var reasoning_effort: String?
    public var service_tier: String?
    public var model: String?
    public var provider_route: String?
    public var replace_today = false
    public var wait_for_provider_ready = false
    public init() {}
}
public struct PlanSection: Codable, Sendable { public let body: String }
public struct PlanResult: Codable, Sendable {
    public let exists: Bool
    public let analysis: PlanSection?
    public let plan: PlanSection?
    public let meta: JSONValue?
    public let date: String?
    public let filename: String?
    public let error: String?
    public var isComplete: Bool { (error == nil || error == "") && exists && !(analysis?.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true) && !(plan?.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true) }
}
public enum JobStatus: String, Codable, Sendable {
    case queued, running, cancelling, succeeded, failed, cancelled
    public var terminal: Bool { self == .succeeded || self == .failed || self == .cancelled }
}
public struct JobError: Codable, Sendable { public let code: String; public let message: String }
public struct JobProgress: Codable, Sendable { public let phase: String; public let events_received: Int }
public struct ActionPlanJob: Codable, Identifiable, Sendable {
    public let id: String
    public let status: JobStatus
    public let trigger: String
    public let request: ActionPlanRequest
    public let progress: JobProgress
    public let result: PlanResult?
    public let error: JobError?
    public let event_cursor: Int
    public let reused: Bool
}
public struct JobList: Decodable, Sendable { public let jobs: [ActionPlanJob]; public let active: ActionPlanJob? }
public struct StreamEvent: Decodable, Sendable {
    public let sequence: Int?
    public let log: String?
    public let error: String?
    public let error_code: String?
    public let done: Bool?
    public let job_status: JobStatus?
    public let truncated: Bool?
    public let event_truncated: Bool?
    public let cursor: Int?
}
public struct ChatMessage: Codable, Sendable, Equatable {
    public let role: String
    public let content: String
    public init(role: String, content: String) { self.role = role; self.content = content }
}
public struct ChatContext: Decodable, Sendable {
    public let context_version: String
    public let base_context_version: String?
    public let display_messages: [ChatMessage]?
    public let has_action_plan_context: Bool
    public let messages: [ChatMessage]
    public let stats: JSONValue?
    public let preferred_model_option_id: String?
}
public struct ChatRequest: Encodable, Sendable {
    public var message: String
    public var model: String?
    public var provider_route: String?
    public var reasoning_effort: String?
    public var service_tier: String?
    public var client_sent_at: String
    public init(message: String, option: ModelOption?, reasoning: String?, tier: String?) {
        self.message = message; model = option?.model; provider_route = option?.provider_route
        reasoning_effort = reasoning; service_tier = tier; client_sent_at = ISO8601DateFormatter().string(from: Date())
    }
}
