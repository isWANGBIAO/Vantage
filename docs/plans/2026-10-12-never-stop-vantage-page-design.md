# Never Stop as a Vantage page

## Decision

Vantage owns one window, one tray, and one Electron process lifecycle. Never Stop becomes a lazy-loaded page at `#never-stop`. Its project sidebar remains inside that page. The runner, resources, notifications, and project file operations live in the Vantage main process and continue when the page is hidden or the window is closed to the tray.

The existing Never Stop React view renders inside a Shadow DOM host. This confines its current CSS to the page without changing Vantage's global styles. The page stays mounted after first visit so unsaved drafts survive navigation; its polling pauses while hidden. The preload exposes only the existing Never Stop operation contract, and the main process accepts calls only from the trusted Vantage main frame.

## Data and lifecycle

New data is stored in `<Vantage data directory>/never-stop`. On first use, if that directory is absent, Vantage copies the existing standalone `VantageNeverStop` user data into a staging directory, checks the copy, and atomically moves it into place. The original directory remains intact. Migration refuses to run while the legacy runner owns its lock, and an existing destination is never overwritten. Project folders and their goals/progress are never moved.

Vantage starts the runner once at application startup. App exit shuts it down with running intent preserved for the next launch; an explicit project pause still clears intent. A Never Stop initialization error appears inside the page and does not block Vantage's other pages. The old standalone login startup entry is disabled after a verified migration, while Vantage's existing startup preference remains authoritative.

## Delivery

The main Vantage package includes Never Stop core modules and the default execution principles. The separate Never Stop entry point, preload, Vite build, installer configuration, batch launcher, and release scripts are removed from active packaging. Keep core behavior tests and replace standalone shell tests with integrated navigation, IPC origin, migration, lifecycle, and package contract checks.

The old feature branch also contains unrelated Action Plan and prompt changes. This integration ports only the Never Stop business changes needed for the unified page; those unrelated commits remain separate.
