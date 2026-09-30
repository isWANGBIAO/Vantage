import Foundation
import Darwin
import CFNetwork

public enum APIError: LocalizedError, Equatable {
    case invalidURL, insecureRedirect, http(Int, String), incompatibleVersion(String), malformedStream, oversizedRecord, incompleteStream, disconnected
    public var errorDescription: String? {
        switch self {
        case .invalidURL: return "Backend address must be a loopback HTTP(S) URL without credentials, query, or fragment."
        case .insecureRedirect: return "Backend redirects are refused."
        case .http(let code, let message): return "HTTP \(code): \(message)"
        case .incompatibleVersion(let version): return "Unsupported Vantage API: \(version)"
        case .malformedStream: return "The backend returned an invalid stream record."
        case .oversizedRecord: return "The backend stream record exceeded the safety limit."
        case .incompleteStream: return "Connection ended before completion. The saved result has not been replaced."
        case .disconnected: return "Backend is unavailable. Start the local backend or reconnect."
        }
    }
}
public struct BackendAddress: Sendable {
    public let url: URL
    public init(_ input: String) throws {
        guard !input.contains("\\"), !input.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
              var c = URLComponents(string: input.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(c.scheme?.lowercased() ?? ""),
              let rawHost = c.host, c.user == nil, c.password == nil, c.query == nil, c.fragment == nil,
              c.port != 0, (c.port ?? 80) <= 65535 else { throw APIError.invalidURL }
        let host = rawHost.trimmingCharacters(in: CharacterSet(charactersIn: "[]")).lowercased()
        var ipv4 = in_addr(); var ipv6 = in6_addr()
        let v4 = host.withCString { inet_pton(AF_INET, $0, &ipv4) } == 1
        let v6 = host.withCString { inet_pton(AF_INET6, $0, &ipv6) } == 1
        let loopback4 = v4 && (UInt32(bigEndian: ipv4.s_addr) >> 24) == 127
        let bytes = withUnsafeBytes(of: &ipv6) { Array($0) }
        let loopback6 = v6 && bytes.prefix(15).allSatisfy { $0 == 0 } && bytes.last == 1
        guard host == "localhost" || loopback4 || loopback6 else { throw APIError.invalidURL }
        while c.path.hasSuffix("/") { c.path.removeLast() }
        guard let url = c.url else { throw APIError.invalidURL }; self.url = url
    }
    public static func resolve(explicit: String? = nil, environment: [String: String] = ProcessInfo.processInfo.environment) throws -> BackendAddress {
        var host = environment["VANTAGE_BACKEND_HOST"] ?? "127.0.0.1"
        if host.contains(":"), !host.hasPrefix("[") { host = "[\(host)]" }
        return try BackendAddress(explicit ?? environment["VANTAGE_BACKEND_URL"] ?? "http://\(host):\(environment["VANTAGE_BACKEND_PORT"] ?? "8000")")
    }
    public var canLaunch: Bool { url.scheme == "http" && (url.path.isEmpty || url.path == "/") }
    public func endpoint(_ path: String, query: [String: String] = [:]) throws -> URL {
        guard path.hasPrefix("/"), !path.hasPrefix("//"), !path.contains("?"), !path.contains("#"), !path.contains("\\"),
              !path.split(separator: "/").contains("..") else { throw APIError.invalidURL }
        guard var c = URLComponents(url: url, resolvingAgainstBaseURL: false) else { throw APIError.invalidURL }
        c.percentEncodedPath += path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path
        if !query.isEmpty { c.queryItems = query.sorted(by: { $0.key < $1.key }).map { URLQueryItem(name: $0.key, value: $0.value) } }
        guard let result = c.url else { throw APIError.invalidURL }; return result
    }
}

private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
public final class APIClient: @unchecked Sendable {
    public let address: BackendAddress
    private let session: URLSession
    private let redirectDelegate = NoRedirectDelegate()
    public init(address: BackendAddress, configuration: URLSessionConfiguration = .ephemeral) {
        self.address = address
        configuration.urlCache = nil; configuration.httpCookieStorage = nil; configuration.urlCredentialStorage = nil
        // Local IPC must not inherit a system HTTP/SOCKS/PAC proxy: settings
        // requests can carry write-only provider credentials.
        configuration.connectionProxyDictionary = [
            kCFNetworkProxiesHTTPEnable as String: 0,
            kCFNetworkProxiesHTTPSEnable as String: 0,
            kCFNetworkProxiesSOCKSEnable as String: 0,
            kCFNetworkProxiesProxyAutoConfigEnable as String: 0,
            kCFNetworkProxiesProxyAutoDiscoveryEnable as String: 0
        ]
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = min(configuration.timeoutIntervalForRequest, 45)
        configuration.timeoutIntervalForResource = min(configuration.timeoutIntervalForResource, 3600)
        session = URLSession(configuration: configuration, delegate: redirectDelegate, delegateQueue: nil)
    }
    public func url(path: String, query: [String: String] = [:]) throws -> URL { try address.endpoint(path, query: query) }
    private func request(path: String, method: String, query: [String: String], body: JSONValue?) throws -> URLRequest {
        var request = URLRequest(url: try url(path: path, query: query))
        request.httpMethod = method; request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body { request.httpBody = try JSONEncoder().encode(body); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        return request
    }
    private func validate(_ response: URLResponse, data: Data? = nil) throws {
        guard let response = response as? HTTPURLResponse else { throw APIError.disconnected }
        if (300..<400).contains(response.statusCode) { throw APIError.insecureRedirect }
        guard (200..<300).contains(response.statusCode) else {
            let value = data.flatMap { try? JSONDecoder().decode(JSONValue.self, from: $0) }
            let detail = value?["detail"].string ?? ""
            let error = value?["error"].string ?? ""
            throw APIError.http(response.statusCode, SensitiveText.redact(!detail.isEmpty ? detail : !error.isEmpty ? error : HTTPURLResponse.localizedString(forStatusCode: response.statusCode)))
        }
    }
    public func request<T: Decodable>(path: String, method: String = "GET", query: [String: String] = [:], body: JSONValue? = nil) async throws -> T {
        let (data, response) = try await session.data(for: request(path: path, method: method, query: query, body: body))
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }
    public func data(path: String, query: [String: String] = [:]) async throws -> Data {
        let (data, response) = try await session.data(for: request(path: path, method: "GET", query: query, body: nil))
        try validate(response, data: data); return data
    }
    public func stream(path: String, method: String = "GET", query: [String: String] = [:], body: JSONValue? = nil,
                       receive: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        var request = try request(path: path, method: method, query: query, body: body)
        request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        let streamSession = URLSession(configuration: session.configuration, delegate: redirectDelegate, delegateQueue: nil)
        defer { streamSession.invalidateAndCancel() }
        try await withTaskCancellationHandler {
            let (bytes, response) = try await streamSession.bytes(for: request)
            try validate(response)
            var parser = NDJSONParser()
            for try await byte in bytes {
                try Task.checkCancellation()
                if let event = try parser.append(byte) { try await receive(event) }
            }
            try Task.checkCancellation()
            if let event = try parser.finish() { try await receive(event) }
        } onCancel: { streamSession.invalidateAndCancel() }
    }
    public func transcribe(file: URL) async throws -> String {
        let boundary = UUID().uuidString
        var request = try request(path: "/api/v1/media/transcribe", method: "POST", query: [:], body: nil)
        request.timeoutInterval = 300
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"recording.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n".utf8)
        body.append(try Data(contentsOf: file)); body.append(Data("\r\n--\(boundary)--\r\n".utf8)); request.httpBody = body
        let (data, response) = try await session.data(for: request); try validate(response, data: data)
        return try JSONDecoder().decode(JSONValue.self, from: data)["transcription"].string
    }
    public func mediaData(reference: String) async throws -> Data {
        guard let parts = URLComponents(string: reference), parts.scheme == nil, parts.host == nil, parts.fragment == nil else { throw APIError.invalidURL }
        let query = Dictionary((parts.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { _, last in last })
        return try await data(path: parts.path, query: query)
    }
    public func openMediaFolder(_ kind: String) async throws {
        guard ["photo", "screenshot"].contains(kind) else { throw APIError.invalidURL }
        var request = try request(path: "/api/v1/media/open-folder", method: "POST", query: [:], body: .object(["type": .string(kind)]))
        request.setValue("open-folder", forHTTPHeaderField: "X-Vantage-Intent")
        let (data, response) = try await session.data(for: request); try validate(response, data: data)
    }
    public func sendCameraFrame(_ data: Data) async throws {
        var request = try request(path: "/api/v1/camera/frame", method: "POST", query: [:], body: nil)
        request.httpBody = data
        request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        request.setValue("renderer-camera-frame", forHTTPHeaderField: "X-Vantage-Intent")
        let (body, response) = try await session.data(for: request); try validate(response, data: body)
    }
    public func jpegFrames(receive: @escaping @Sendable (Data) async -> Void) async throws {
        let request = try request(path: "/api/v1/camera/stream", method: "GET", query: [:], body: nil)
        let streamSession = URLSession(configuration: session.configuration, delegate: redirectDelegate, delegateQueue: nil)
        defer { streamSession.invalidateAndCancel() }
        try await withTaskCancellationHandler {
            let (bytes, response) = try await streamSession.bytes(for: request); try validate(response)
            var parser = JPEGFrameParser()
            for try await byte in bytes {
                try Task.checkCancellation()
                if let image = try parser.append(byte) { await receive(image) }
            }
            try Task.checkCancellation()
        } onCancel: { streamSession.invalidateAndCancel() }
    }
}
public struct NDJSONParser {
    public static let maximumRecordBytes = 1_048_576
    private var buffer = Data()
    public init() {}
    public mutating func append(_ byte: UInt8) throws -> StreamEvent? {
        if byte == 10 { return try decode() }
        guard buffer.count < Self.maximumRecordBytes else { throw APIError.oversizedRecord }
        buffer.append(byte); return nil
    }
    public mutating func finish() throws -> StreamEvent? { try decode() }
    private mutating func decode() throws -> StreamEvent? {
        defer { buffer.removeAll(keepingCapacity: true) }
        if buffer.allSatisfy({ $0 == 13 || $0 == 32 || $0 == 9 }) { return nil }
        do { return try JSONDecoder().decode(StreamEvent.self, from: buffer) } catch { throw APIError.malformedStream }
    }
}
public struct JPEGFrameParser {
    private var buffer = Data()
    private var previous: UInt8 = 0
    private var inImage = false
    public init() {}
    public mutating func append(_ byte: UInt8) throws -> Data? {
        defer { previous = byte }
        if !inImage, previous == 0xff, byte == 0xd8 { inImage = true; buffer = Data([0xff, 0xd8]); return nil }
        guard inImage else { return nil }
        guard buffer.count < 8_388_608 else { throw APIError.oversizedRecord }
        buffer.append(byte)
        if previous == 0xff, byte == 0xd9 { inImage = false; let result = buffer; buffer = Data(); return result }
        return nil
    }
}
public enum SensitiveText {
    public static func redact(_ text: String) -> String {
        var result = text
        for pattern in ["(?i)Bearer\\s+[A-Za-z0-9._~+/=-]+", "(?i)(api[_-]?key|authorization|token|password)([\\s\"':=]+)([^\\s,;\"']+)", "sk-[A-Za-z0-9_-]{8,}"] {
            result = result.replacingOccurrences(of: pattern, with: "[redacted]", options: .regularExpression)
        }
        return result
    }
}
