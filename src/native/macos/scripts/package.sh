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
[[ "$(uname -s)" == Darwin ]] || { echo "Packaging requires macOS 14+ and Xcode Command Line Tools." >&2; exit 1; }
[[ "$CONFIGURATION" == release || "$CONFIGURATION" == debug ]] || { echo "Invalid build configuration" >&2; exit 2; }
[[ -n "$RUNTIME" && -x "$RUNTIME/VantageBackend" ]] || { echo "A complete backend runtime directory containing executable VantageBackend is required." >&2; exit 1; }
RUNTIME="$(cd "$RUNTIME" && pwd)"
swift build --package-path "$PACKAGE" -c "$CONFIGURATION"
BIN="$(swift build --package-path "$PACKAGE" -c "$CONFIGURATION" --show-bin-path)"
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
STAGE="$(mktemp -d "$OUTPUT/.vantage-package.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/Vantage.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/backend-runtime"
cp "$BIN/VantageMac" "$APP/Contents/MacOS/Vantage"
cp "$PACKAGE/Resources/Info.plist" "$APP/Contents/Info.plist"
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
if [[ -e "$OUTPUT/Vantage.app" ]]; then mv "$OUTPUT/Vantage.app" "$STAGE/previous.app"; fi
mv "$APP" "$OUTPUT/Vantage.app"
echo "Packaged $OUTPUT/Vantage.app"
