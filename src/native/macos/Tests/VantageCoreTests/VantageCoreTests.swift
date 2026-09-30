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
    func testAggregateStreamBuffersStayBounded() throws {
        let chunk = String(repeating: "x", count: 1024)
        let json = try JSONEncoder().encode(JSONValue.object(["log": .string("STREAM_PLAN_CONTENT:" + chunk)]))
        let item = try JSONDecoder().decode(StreamEvent.self, from: json)
        var plan = PlanStreamState()
        for _ in 0..<4200 { plan.apply(item) }
        XCTAssertTrue(plan.needsSnapshot); XCTAssertEqual(plan.plan, "")
        let chatData = try JSONEncoder().encode(JSONValue.object(["log": .string("STREAM_CONTENT:" + chunk)]))
        let chatItem = try JSONDecoder().decode(StreamEvent.self, from: chatData)
        var chat = ChatStreamState()
        for _ in 0..<4200 { chat.apply(chatItem) }
        XCTAssertNotNil(chat.failure); XCTAssertLessThanOrEqual(chat.content.utf8.count, ChatStreamState.maximumTextBytes)
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
    func testExplicitInverseAxisPreservesBoundsAndLabels() {
        let axis = ChartAxis(.object(["min": .number(0), "max": .number(20), "inverse": .bool(true), "scale": .bool(true)]))
        XCTAssertEqual(axis.bounds, -20.0...0.0)
        XCTAssertEqual(axis.coordinate(5), -5)
        XCTAssertEqual(axis.value(-5), 5)
        XCTAssertFalse(axis.includesZero)
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
    func testLocalSessionDisablesProxyCookiesAndCredentialCache() throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.connectionProxyDictionary = ["HTTPEnable": 1, "HTTPProxy": "proxy.example", "HTTPPort": 8080]
        _ = APIClient(address: try BackendAddress("http://localhost"), configuration: configuration)
        XCTAssertEqual(configuration.connectionProxyDictionary?["HTTPEnable"] as? Int, 0)
        XCTAssertEqual(configuration.connectionProxyDictionary?["HTTPSEnable"] as? Int, 0)
        XCTAssertEqual(configuration.connectionProxyDictionary?["SOCKSEnable"] as? Int, 0)
        XCTAssertNil(configuration.httpCookieStorage)
        XCTAssertNil(configuration.urlCredentialStorage)
    }
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
    func testAudioFileTranscriptionPreservesFormatAndReadsCanonicalField() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("private-name-\(UUID().uuidString).wav")
        try Data([0x52, 0x49, 0x46, 0x46]).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/prefix/api/v1/media/transcribe")
            XCTAssertEqual(request.httpMethod, "POST")
            var data = request.httpBody ?? Data()
            if let input = request.httpBodyStream {
                input.open(); defer { input.close() }
                var buffer = [UInt8](repeating: 0, count: 1024)
                while input.hasBytesAvailable {
                    let count = input.read(&buffer, maxLength: buffer.count)
                    if count <= 0 { break }; data.append(contentsOf: buffer.prefix(count))
                }
            }
            let multipart = String(decoding: data, as: UTF8.self)
            XCTAssertTrue(multipart.contains("filename=\"audio.wav\""))
            XCTAssertTrue(multipart.contains("Content-Type: audio/wav"))
            XCTAssertFalse(multipart.contains("private-name"))
            return (200, Data(#"{"transcription":"synthetic transcript"}"#.utf8))
        }
        let transcript = try await client().transcribe(file: file)
        XCTAssertEqual(transcript, "synthetic transcript")
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

final class MarkdownTests: XCTestCase {
    func testCodeBlocksPreserveLiteralMarkdownAndIncompleteFence() {
        XCTAssertEqual(MarkdownBlocks.parse("```swift\nlet x = 1\n# literal\n```"), [.code("swift", "let x = 1\n# literal")])
        XCTAssertEqual(MarkdownBlocks.parse("```\nincomplete"), [.code("", "incomplete")])
    }
    func testTablesQuotesAndEscapedPipes() {
        let result = MarkdownBlocks.parse("# Heading\n| Item | Value |\n| --- | ---: |\n| a\\|b | 3 |\n> note")
        XCTAssertEqual(result, [.heading("Heading", 1), .table(["Item", "Value"], [["a|b", "3"]]), .quote("note")])
    }
    func testClockPaceAndCurrencyHaveDomainUnits() {
        XCTAssertEqual(ChartFormatting.value(25.5, kind: "clock"), "01:30")
        XCTAssertEqual(ChartFormatting.value(5.5, kind: "pace"), "5:30 /km")
        XCTAssertEqual(JSONValue.number(1234).string, "1234")
    }
}

private final class HangingProtocol: URLProtocol {
    static var started: (() -> Void)?
    static var stopped: (() -> Void)?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/x-ndjson"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data("{\"log\":\"waiting\"}\n".utf8))
        Self.started?()
        // Deliberately keep transport open until the caller cancels.
    }
    override func stopLoading() { Self.stopped?() }
}
final class StreamCancellationTests: XCTestCase {
    func testCancellingObservationClosesUnderlyingTransport() async throws {
        let started = expectation(description: "URL loading started")
        let stopped = expectation(description: "URL loading stopped")
        stopped.assertForOverFulfill = false
        HangingProtocol.started = { started.fulfill() }
        HangingProtocol.stopped = { stopped.fulfill() }
        defer { HangingProtocol.stopped = nil; HangingProtocol.started = nil }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [HangingProtocol.self]
        let client = APIClient(address: try BackendAddress("http://127.0.0.1"), configuration: configuration)
        let task = Task { try await client.stream(path: "/api/v1/action-plan/jobs/test/events") { _ in } }
        await fulfillment(of: [started], timeout: 3)
        task.cancel()
        await fulfillment(of: [stopped], timeout: 3)
        do { try await task.value; XCTFail("Cancelled observation must not complete successfully") } catch { }
    }
}

final class PlotLayoutTests: XCTestCase {
    private func series(_ json: String) throws -> [NativeChartSeries] {
        ChartData.series(try JSONDecoder().decode(JSONValue.self, from: Data(json.utf8)))
    }
    func testStackedBarsUseCumulativeDomainAndSeparateGroups() throws {
        let values = try series(#"{"series":[{"name":"A","type":"bar","stack":"total","data":[8]},{"name":"B","type":"bar","stack":"total","data":[16]},{"name":"C","type":"bar","data":[3]}]}"#)
        let layout = PlotLayout(points: values.flatMap(\.points), configuration: .null)
        XCTAssertEqual(layout.bars["0-0"], PlotBar(start: 0, end: 8, group: "total"))
        XCTAssertEqual(layout.bars["1-0"], PlotBar(start: 8, end: 24, group: "total"))
        XCTAssertEqual(layout.bars["2-0"], PlotBar(start: 0, end: 3, group: "C"))
        XCTAssertGreaterThan(layout.yBounds.upperBound, 24)
        XCTAssertEqual(layout.barGroups, ["total", "C"])
    }
    func testInverseExplicitBoundsAndZoomStayOrdered() throws {
        let values = try series(#"{"series":[{"type":"line","data":[2,6,14]}]}"#)
        let layout = PlotLayout(points: values.flatMap(\.points), configuration: .object(["min": .number(0), "max": .number(20), "inverse": .bool(true)]))
        XCTAssertEqual(layout.yBounds, -20.0...0.0)
        let visible = layout.visibleX(zoom: 0.5, pan: 1)
        XCTAssertEqual(visible.upperBound, layout.xBounds.upperBound, accuracy: 0.0001)
        XCTAssertEqual(visible.upperBound - visible.lowerBound, (layout.xBounds.upperBound - layout.xBounds.lowerBound) / 2, accuracy: 0.0001)
    }
    func testCategoryTicksUseActualCentersWithoutDuplicatingNearestLabels() throws {
        let values = try series(#"{"xAxis":{"type":"category","data":["Mon","Tue","Wed","Thu"]},"series":[{"type":"bar","data":[20,45,null,60]},{"type":"bar","data":[15,20,40,30]}]}"#)
        let ticks = PlotLayout.categoryTicks(points: values.flatMap(\.points))
        XCTAssertEqual(ticks.map(\.x), [0, 1, 2, 3])
        XCTAssertEqual(ticks.map(\.label), ["Mon", "Tue", "Wed", "Thu"])
        let sampled = PlotLayout.categoryTicks(points: values.flatMap(\.points), maximumCount: 3)
        XCTAssertEqual(Set(sampled.map(\.x)).count, 3)
        XCTAssertEqual(sampled.first?.x, 0); XCTAssertEqual(sampled.last?.x, 3)
    }
    func testNullGapKeepsBothIsolatedSamplesVisible() throws {
        let values = try series(#"{"series":[{"type":"line","data":[65,null,64]}]}"#)
        XCTAssertEqual(values[0].isolatedPoints.map(\.y), [65, 64])
        XCTAssertEqual(values[0].isolatedPoints.map(\.segment), [0, 1])
    }
    func testPositiveAndNegativeStacksDoNotCancelEachOther() throws {
        let values = try series(#"{"series":[{"name":"A","type":"bar","stack":"s","data":[5]},{"name":"B","type":"bar","stack":"s","data":[-3]},{"name":"C","type":"bar","stack":"s","data":[2]}]}"#)
        let layout = PlotLayout(points: values.flatMap(\.points), configuration: .null)
        XCTAssertEqual(layout.bars["1-0"]?.start, 0)
        XCTAssertEqual(layout.bars["1-0"]?.end, -3)
        XCTAssertEqual(layout.bars["2-0"]?.end, 7)
    }
}

final class AudioOperationStateTests: XCTestCase {
    func testLateCompletionCannotClearNewTranscriptionOrDeleteItsFile() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let oldFile = directory.appendingPathComponent("old.m4a"); let newFile = directory.appendingPathComponent("new.m4a")
        try Data([1]).write(to: oldFile); try Data([2]).write(to: newFile)
        var state = AudioOperationState()
        let old = state.begin(file: oldFile, ownsTemporaryFile: true, transcribing: true)
        state.cancel()
        let newer = state.begin(file: newFile, ownsTemporaryFile: true, transcribing: true)
        try old.removeOwnedTemporaryFile()
        XCTAssertFalse(state.finish(old))
        XCTAssertTrue(state.isCurrent(newer)); XCTAssertTrue(state.transcribing); XCTAssertTrue(state.isBusy)
        XCTAssertFalse(FileManager.default.fileExists(atPath: oldFile.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: newFile.path))
        try newer.removeOwnedTemporaryFile(); XCTAssertTrue(state.finish(newer)); XCTAssertFalse(state.isBusy)
    }
    func testPickedAudioIsNeverOwnedOrRemoved() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        try Data([1]).write(to: file); defer { try? FileManager.default.removeItem(at: file) }
        var state = AudioOperationState(); let ticket = state.begin(file: file, transcribing: true)
        state.cancel(); try ticket.removeOwnedTemporaryFile()
        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path)); XCTAssertFalse(state.finish(ticket))
    }
    func testLatePermissionTaskCannotFinishNewOperation() {
        var state = AudioOperationState(); let permission = state.begin()
        state.cancel(); let next = state.begin(transcribing: true)
        XCTAssertFalse(state.isCurrent(permission)); XCTAssertFalse(state.finish(permission))
        XCTAssertTrue(state.isCurrent(next)); XCTAssertTrue(state.transcribing)
    }
}

final class ChatDraftRecoveryTests: XCTestCase {
    func testConfirmedUnchangedContextRestoresOnlySubmittedDraft() {
        let result = ChatDraftRecovery.recover(submitted: "  original message\n", currentDraft: "", beforeVersion: "v1", afterVersion: "v1")
        XCTAssertEqual(result.draft, "  original message\n"); XCTAssertNil(result.retainedCopy)
    }
    func testNewDraftIsNeverOverwritten() {
        let result = ChatDraftRecovery.recover(submitted: "old", currentDraft: "new draft", beforeVersion: "v1", afterVersion: "v1")
        XCTAssertEqual(result.draft, "new draft"); XCTAssertEqual(result.retainedCopy, "old")
    }
    func testUnknownOrChangedContextDoesNotQueueDuplicateSend() {
        for version in [nil, "v2"] as [String?] {
            let result = ChatDraftRecovery.recover(submitted: "old", currentDraft: "", beforeVersion: "v1", afterVersion: version)
            XCTAssertEqual(result.draft, ""); XCTAssertEqual(result.retainedCopy, "old")
        }
        XCTAssertEqual(ChatDraftRecovery.recover(submitted: "old", currentDraft: "", beforeVersion: nil, afterVersion: nil).draft, "")
    }
}
