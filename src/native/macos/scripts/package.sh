#!/bin/bash
# Build a real native .app. No Electron, web assets, or remote dependency fetch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
PACKAGE="$ROOT/src/native/macos"
OUTPUT="$ROOT/build/native/macos"
RUNTIME=""
CONFIGURATION=release
while (($#)); do
  case "$1" in
    --backend-runtime) RUNTIME="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --configuration) CONFIGURATION="$2"; shift 2 ;;
    *) echo "Usage: $0 --backend-runtime DIR [--output DIR] [--configuration release|debug]" >&2; exit 2 ;;
  esac
done
[[ "$(uname -s)" == Darwin ]] || { echo "Packaging requires macOS 15+ and Xcode Command Line Tools." >&2; exit 1; }
[[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 15 ]] || { echo "The complete backend/app bundle is built and validated for macOS 15+." >&2; exit 1; }
[[ "$CONFIGURATION" == release || "$CONFIGURATION" == debug ]] || { echo "Invalid build configuration" >&2; exit 2; }
[[ -n "$RUNTIME" && -x "$RUNTIME/VantageBackend" ]] || { echo "A complete backend runtime directory containing executable VantageBackend is required." >&2; exit 1; }
OUTPUT="$(python3 "$PACKAGE/scripts/validate_output.py" --runtime "$RUNTIME" --output "$OUTPUT" --repository "$ROOT")"
RUNTIME="$(cd "$RUNTIME" && pwd -P)"
python3 "$ROOT/scripts/validate_native_runtime.py" --runtime "$RUNTIME" --platform darwin --architecture "$(uname -m)"
swift build --package-path "$PACKAGE" -c "$CONFIGURATION"
BIN="$(swift build --package-path "$PACKAGE" -c "$CONFIGURATION" --show-bin-path)"
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
STAGE="$(mktemp -d "$OUTPUT/.vantage-package.XXXXXX")"
# Staging belongs only to this invocation. Previous bundles are never placed
# here, so a failed build cannot delete an existing output through this trap.
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/Vantage.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/backend-runtime"
cp "$BIN/VantageMac" "$APP/Contents/MacOS/Vantage"
cp "$PACKAGE/Resources/Info.plist" "$APP/Contents/Info.plist"
printf '%s\n' '{"format":"vantage-native-macos-bundle","version":1}' > "$APP/Contents/Resources/vantage-native-package.json"
# Preserve the complete PyInstaller onedir layout; never copy only its launcher.
ditto "$RUNTIME" "$APP/Contents/Resources/backend-runtime/VantageBackend"
ICONSET="$STAGE/Vantage.iconset"
mkdir "$ICONSET"
for SIZE in 16 32 128 256 512; do
  sips -z "$SIZE" "$SIZE" "$ROOT/icon.png" --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
  DOUBLE=$((SIZE * 2))
  sips -z "$DOUBLE" "$DOUBLE" "$ROOT/icon.png" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Vantage.icns"
plutil -lint "$APP/Contents/Info.plist"
# Local ad-hoc signing only. No identity, notarization account, or secret access.
codesign --force --sign - "$APP/Contents/MacOS/Vantage"
codesign --force --sign - "$APP"
codesign --verify "$APP"
# Revalidate after the build in case another process changed the destination.
python3 "$PACKAGE/scripts/validate_output.py" --runtime "$RUNTIME" --output "$OUTPUT" --repository "$ROOT" >/dev/null
BACKUP="$(python3 "$PACKAGE/scripts/publish_bundle.py" --app "$APP" --target "$OUTPUT/Vantage.app")"
echo "Packaged $OUTPUT/Vantage.app"
if [[ -n "$BACKUP" ]]; then echo "Previous generated bundle retained at $BACKUP"; fi
