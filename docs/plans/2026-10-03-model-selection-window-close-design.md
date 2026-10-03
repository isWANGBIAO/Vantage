# Persistent model selection and window close

The user confirmed that the selected model must survive restarts and upgrades, and Ctrl+W must close only the window, not quit Vantage.

Use the existing provider JSON as the source of truth. Selecting a model persists its provider route and model through a narrow backend operation that preserves credentials and unrelated provider fields. Initial model selection uses the backend default rather than an origin-specific browser cache. Manual and automatic generation use the same selected option. A failed save must not publish a successful new selection.

Ctrl+W (Command+W on macOS) invokes the existing window-close behavior, which hides the window while keeping the tray and backend alive. Do not add a global shortcut or change the tray Quit action.

Alternatives rejected: retaining independent browser-only preference would preserve the existing split state; rewriting complete provider configuration from the frontend would risk stale updates and credential loss.

Verification covers preference persistence, validation and preservation of other configuration, stale browser cache versus canonical default, save failure, and close without quit. Release the main app with a fresh patch version and execute the full build/install chain. Never Stop remains independent.
