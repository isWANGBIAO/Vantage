namespace Vantage.Core;

public static class DraftRecovery
{
    // Recovery is only a local draft change. It must never retry the POST or resurrect a reset conversation.
    public static bool ShouldRestore(bool failed, string? sentContextVersion, string? latestContextVersion,
        string currentDraft, long draftRevisionAtSend, long currentDraftRevision) =>
        failed && !string.IsNullOrEmpty(sentContextVersion) && sentContextVersion == latestContextVersion &&
        currentDraft.Length == 0 && draftRevisionAtSend == currentDraftRevision;
}
