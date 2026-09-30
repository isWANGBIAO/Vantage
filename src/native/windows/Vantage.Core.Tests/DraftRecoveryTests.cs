using Vantage.Core;
using Xunit;
namespace Vantage.Core.Tests;
public class DraftRecoveryTests
{
    [Fact] public void RestoresOnlyUnchangedAuthoritativeContextAndUntouchedDraft() => Assert.True(DraftRecovery.ShouldRestore(true, "v1", "v1", "", 2, 2));
    [Fact] public void NeverRestoresAfterResetOrSuccessfulPersistence() => Assert.False(DraftRecovery.ShouldRestore(true, "v1", "v2", "", 2, 2));
    [Fact] public void NeverOverwritesANewDraft() => Assert.False(DraftRecovery.ShouldRestore(true, "v1", "v1", "new text", 2, 3));
    [Fact] public void RespectsANewDraftThatWasThenCleared() => Assert.False(DraftRecovery.ShouldRestore(true, "v1", "v1", "", 2, 4));
    [Fact] public void UnknownContextCannotAuthorizeRecovery() => Assert.False(DraftRecovery.ShouldRestore(true, null, null, "", 2, 2));
    [Fact] public void SuccessfulSendNeverRestoresDraft() => Assert.False(DraftRecovery.ShouldRestore(false, "v1", "v1", "", 2, 2));
}
