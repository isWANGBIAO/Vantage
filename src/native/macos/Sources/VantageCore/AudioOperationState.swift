import Foundation

/// Each asynchronous microphone/file operation owns a distinct ticket. A late
/// completion may clean up only its own temporary file, never a newer operation.
public struct AudioOperationTicket: Sendable {
    public let id: UUID
    public let file: URL?
    public let ownsTemporaryFile: Bool
    public func removeOwnedTemporaryFile() throws {
        guard ownsTemporaryFile, let file, FileManager.default.fileExists(atPath: file.path) else { return }
        try FileManager.default.removeItem(at: file)
    }
}
public struct AudioOperationState: Sendable {
    public private(set) var activeID: UUID?
    public private(set) var transcribing = false
    public var isBusy: Bool { activeID != nil }
    public init() {}
    public mutating func begin(file: URL? = nil, ownsTemporaryFile: Bool = false, transcribing: Bool = false) -> AudioOperationTicket {
        let ticket = AudioOperationTicket(id: UUID(), file: file, ownsTemporaryFile: ownsTemporaryFile)
        activeID = ticket.id; self.transcribing = transcribing; return ticket
    }
    public func isCurrent(_ ticket: AudioOperationTicket) -> Bool { activeID == ticket.id }
    @discardableResult public mutating func finish(_ ticket: AudioOperationTicket) -> Bool {
        guard isCurrent(ticket) else { return false }
        activeID = nil; transcribing = false; return true
    }
    public mutating func cancel() { activeID = nil; transcribing = false }
}
