import XCTest
@testable import VantageCore

final class AddressTests: XCTestCase {
    func testLoopbackAndPrecedence() throws {
        for value in ["http://127.0.0.1:8000", "http://127.3.4.5", "https://localhost/prefix", "http://[::1]:9000"] { XCTAssertNoThrow(try BackendAddress(value)) }
        let address = try BackendAddress.resolve(explicit: "http://localhost:1234", environment: ["VANTAGE_BACKEND_URL": "http://127.0.0.1:9999"])
        XCTAssertEqual(address.url.port, 1234)
        let v6 = try BackendAddress.resolve(environment: ["VANTAGE_BACKEND_HOST": "::1", "VANTAGE_BACKEND_PORT": "4321"])
        XCTAssertEqual(v6.url.port, 4321)
    }
    func testRejectsUnsafeDestinations() {
        for value in ["https://example.com", "http://192.168.1.2", "file:///tmp/test", "http://localhost@evil.test", "http://user:pass@localhost", "http://localhost?secret=1", "http://localhost#part", "http://localhost:0", "http://localhost:99999", "http://127.0.0.1\\@evil.test", "http://localhost\n", "http://[::ffff:127.0.0.1]", "http://127.1", "http://2130706433", "http://localhost.evil.test"] {
            XCTAssertThrowsError(try BackendAddress(value), value)
        }
    }
    func testPrefixAndEncodedQuery() throws {
        let address = try BackendAddress("https://localhost/proxy/")
        let endpoint = try address.endpoint("/api/v1/media/image", query: ["path": "/some place/a+b.png"])
        XCTAssertEqual(endpoint.path, "/proxy/api/v1/media/image")
        XCTAssertEqual(URLComponents(url: endpoint, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "/some place/a+b.png")
        XCTAssertFalse(address.canLaunch)
        XCTAssertThrowsError(try address.endpoint("//evil.test/path"))
        XCTAssertThrowsError(try address.endpoint("/../elsewhere"))
    }
}
final class StreamTests: XCTestCase {
    private func event(_ json: String) throws -> StreamEvent { try JSONDecoder().decode(StreamEvent.self, from: Data(json.utf8)) }
    func testUTF8FragmentedNDJSONAndFinalRecord() throws {
        var parser = NDJSONParser(); var logs: [String] = []
        for byte in Data("\r\n{\"log\":\"你好🌍\"}\n{\"done\":true}".utf8) { if let item = try parser.append(byte), let log = item.log { logs.append(log) } }
        XCTAssertEqual(logs, ["你好🌍"])
        XCTAssertEqual(try parser.finish()?.done, true)
    }
    func testInvalidAndOversizedRecordsFailClosed() throws {
        var parser = NDJSONParser()
        for byte in Data("not-json".utf8) { _ = try parser.append(byte) }
        XCTAssertThrowsError(try parser.finish())
        var large = NDJSONParser()
        for _ in 0..<NDJSONParser.maximumRecordBytes { _ = try large.append(32) }
        XCTAssertThrowsError(try large.append(32))
    }
    func testDeduplicationAndTruncation() throws {
        var state = PlanStreamState()
        let content = try event(#"{"sequence":1,"log":"STREAM_PLAN_CONTENT:\"first\""}"#)
        state.apply(content); state.apply(content)
        XCTAssertEqual(state.plan, "first"); XCTAssertEqual(state.cursor, 1)
        state.apply(try event(#"{"truncated":true,"cursor":9}"#))
        XCTAssertTrue(state.needsSnapshot); XCTAssertEqual(state.plan, ""); XCTAssertEqual(state.cursor, 9)
        state.apply(try event(#"{"sequence":10,"log":"STREAM_PLAN_CONTENT:\"incomplete tail\""}"#))
        XCTAssertEqual(state.plan, ""); XCTAssertFalse(state.completionObserved)
        state.apply(try event(#"{"sequence":11,"done":true,"job_status":"succeeded"}"#))
        XCTAssertTrue(state.completionObserved)
    }
    func testChatRequiresDoneAndParsesActualPrefix() throws {
        var state = ChatStreamState()
        state.apply(try event(#"{"log":"STREAM_CONTENT:\"answer\""}"#))
        XCTAssertEqual(state.content, "answer"); XCTAssertFalse(state.done)
        state.apply(try event(#"{"error":"failed"}"#)); state.apply(try event(#"{"done":true}"#))
        XCTAssertNotNil(state.failure); XCTAssertTrue(state.done)
    }
    func testJPEGFramesAcrossBoundaries() throws {
        var parser = JPEGFrameParser(); var images: [Data] = []
        for byte in [UInt8](arrayLiteral: 10, 13, 0xff, 0xd8, 1, 2, 0xff, 0xd9, 10, 0xff, 0xd8, 3, 0xff, 0xd9) {
            if let data = try parser.append(byte) { images.append(data) }
        }
        XCTAssertEqual(images, [Data([0xff, 0xd8, 1, 2, 0xff, 0xd9]), Data([0xff, 0xd8, 3, 0xff, 0xd9])])
    }
    func testPlanCompletenessAndAdditiveFields() throws {
        let valid = #"{"exists":true,"analysis":{"body":"analysis"},"plan":{"body":"plan"},"unknown_field":123}"#
        XCTAssertTrue(try JSONDecoder().decode(PlanResult.self, from: Data(valid.utf8)).isComplete)
        let failed = #"{"exists":true,"analysis":{"body":"analysis"},"plan":{"body":"plan"},"error":"failed"}"#
        XCTAssertFalse(try JSONDecoder().decode(PlanResult.self, from: Data(failed.utf8)).isComplete)
        let blank = #"{"exists":true,"analysis":{"body":" "},"plan":{"body":"plan"}}"#
        XCTAssertFalse(try JSONDecoder().decode(PlanResult.self, from: Data(blank.utf8)).isComplete)
    }
    func testSecretsAreRedacted() { XCTAssertFalse(SensitiveText.redact("Bearer abc.def and sk-123456789abcdef").contains("123456789")) }
}
final class ChartTests: XCTestCase {
    func testCategoryNullGapsObjectValuesAndUnits() throws {
        let value = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"xAxis":{"type":"category","data":["A","B","C","D"]},"series":[{"name":"weight","type":"line","yAxisIndex":1,"data":[2,null,{"value":5},7]}]}"#.utf8))
        let series = ChartData.series(value)
        XCTAssertEqual(series.count, 1); XCTAssertEqual(series[0].axis, 1)
        XCTAssertEqual(series[0].points.map(\.label), ["A", "C", "D"])
        XCTAssertEqual(series[0].points.map(\.segment), [0, 1, 1])
        XCTAssertEqual(series[0].points.map(\.y), [2, 5, 7])
    }
    func testTimePairsAndStackPreserved() throws {
        let value = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"xAxis":{"type":"time"},"series":[{"name":"hours","type":"bar","stack":"time","data":[["2026-01-01",8],["2026-01-02",7]]}]}"#.utf8))
        let series = ChartData.series(value)
        XCTAssertEqual(series[0].stack, "time")
        XCTAssertEqual(series[0].points[1].x - series[0].points[0].x, 86400)
    }
    func testPieNamesPreserved() throws {
        let value = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"series":[{"type":"pie","data":[{"name":"Sleep","value":8},{"name":"Awake","value":16}]}]}"#.utf8))
        XCTAssertEqual(ChartData.series(value)[0].points.map(\.label), ["Sleep", "Awake"])
    }
}

private final class StubProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, data) = try Self.handler!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
final class HTTPTests: XCTestCase {
    private func client() throws -> APIClient {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [StubProtocol.self]
        return APIClient(address: try BackendAddress("http://127.0.0.1:8000/prefix"), configuration: config)
    }
    override func tearDown() { StubProtocol.handler = nil; super.tearDown() }
    func testTypedRequestPreservesPrefixAndDoesNotRetryWrites() async throws {
        var count = 0
        StubProtocol.handler = { request in
            count += 1; XCTAssertEqual(request.url?.path, "/prefix/api/v1/settings"); XCTAssertEqual(request.httpMethod, "PUT")
            return (503, Data(#"{"error":"temporary failure"}"#.utf8))
        }
        do { let _: JSONValue = try await client().request(path: "/api/v1/settings", method: "PUT", body: .object(["theme": .string("dark")])); XCTFail("Expected HTTP failure") }
        catch { XCTAssertEqual(count, 1) }
    }
    func testRefusesRedirectResponse() async throws {
        StubProtocol.handler = { _ in (302, Data()) }
        do { let _: JSONValue = try await client().request(path: "/api/v1/settings"); XCTFail("Expected refusal") }
        catch { XCTAssertEqual(error as? APIError, .insecureRedirect) }
    }
    func testOpenFolderUsesExplicitIntent() async throws {
        StubProtocol.handler = { request in XCTAssertEqual(request.value(forHTTPHeaderField: "X-Vantage-Intent"), "open-folder"); return (200, Data("{}".utf8)) }
        try await client().openMediaFolder("photo")
    }
    func testMediaQueryIsDecodedExactlyOnceAndCannotEscapeBackend() async throws {
        StubProtocol.handler = { request in
            let components = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)
            XCTAssertEqual(components?.path, "/prefix/api/v1/media/image")
            XCTAssertEqual(components?.queryItems?.first?.value, "/photos/a b.png")
            return (200, Data([1, 2]))
        }
        let result = try await client().mediaData(reference: "/api/v1/media/image?path=%2Fphotos%2Fa%20b.png")
        XCTAssertEqual(result, Data([1, 2]))
        do { _ = try await client().mediaData(reference: "https://evil.test/private"); XCTFail("Unsafe image URL") } catch { XCTAssertEqual(error as? APIError, .invalidURL) }
    }
}
