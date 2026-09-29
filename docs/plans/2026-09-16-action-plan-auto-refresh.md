# Action Plan automatic refresh

**Goal:** Check the configured Excel inputs at a user-selected interval, default 60 minutes; 0 disables checking. Persist the interval in the existing settings JSON.

**Architecture:** A read-only backend endpoint fingerprints the actual workbook inputs. The mounted Action Plan scheduler establishes a baseline and checks for changes without overlapping generation. Automatic generation consumes the complete response in the background and replaces the displayed plan only after successful completion. Failed attempts retain the previous revision so a later check retries.

## Implementation

1. Add `action_plan_check_interval_minutes` to Python and Electron settings normalization and the renderer mapping `actionPlanCheckIntervalMinutes`. Test default, zero, custom values, reload, and partial-save preservation.
2. Add `/api/action_plan/source_revision` using configured Action Plan workbook paths and stable content hashing. Test unchanged bytes, changed bytes, missing input, and read failures.
3. Add an interval input beside the Action Plan heading and a scheduler that checks while the app is running. Prevent overlap with manual generation; retain old content during background generation and errors.
4. Test scheduler success, unchanged sources, failure/retry, zero, and incomplete response. Run targeted Python tests and frontend check; review the combined diff.

Scope: automatic checking runs while Vantage is open. No external OS scheduled job is created. Existing manual generation behavior remains available.
