import Foundation

public enum BootstrapStage: Sendable, Equatable { case connecting, onboarding, ready }
public enum BootstrapGate {
    public static func stage(settingsReady: Bool, onboardingCompleted: Bool?) -> BootstrapStage {
        guard settingsReady, let onboardingCompleted else { return .connecting }
        return onboardingCompleted ? .ready : .onboarding
    }
}
