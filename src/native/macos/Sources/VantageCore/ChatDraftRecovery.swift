import Foundation

public struct ChatDraftRecovery: Sendable, Equatable {
    public let draft: String
    public let retainedCopy: String?
    /// Only an unchanged authoritative context proves this send was not saved.
    /// Unknown/changed state keeps a separate reviewable copy, never a retry.
    public static func recover(submitted: String, currentDraft: String, beforeVersion: String?, afterVersion: String?) -> ChatDraftRecovery {
        if let beforeVersion, !beforeVersion.isEmpty, beforeVersion == afterVersion, currentDraft.isEmpty {
            return ChatDraftRecovery(draft: submitted, retainedCopy: nil)
        }
        return ChatDraftRecovery(draft: currentDraft, retainedCopy: submitted)
    }
}
