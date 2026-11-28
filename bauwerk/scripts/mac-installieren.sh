#!/bin/bash
# Bauwerk auf dem Mac bauen und installieren.
#   ./scripts/mac-installieren.sh            → /Applications/Bauwerk.app + Kommandozeile ~/.local/bin/bauwerk
# Voraussetzung: Xcode-Befehlszeilenwerkzeuge (xcode-select --install). Rust wird bei Bedarf installiert.
set -euo pipefail
cd "$(dirname "$0")/.."
WURZEL="$(pwd)"

if ! command -v cargo >/dev/null 2>&1; then
  [ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "▶ Rust wird installiert …"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
  source "$HOME/.cargo/env"
fi

echo "▶ Teste den Kern …"
cargo test --release -q -p bauwerk-kern

echo "▶ Baue Kommandozeile (bauwerk, mit echten STEP-Flächen aus Mesh2STEP) …"
# immer den neuesten Mesh2STEP-Kern aus dem privaten Repo holen
(cd crates/echt && cargo update -q -p mesh2step-core && cargo test --release -q && cargo build --release)
mkdir -p "$HOME/.local/bin"
cp crates/echt/target/release/bauwerk "$HOME/.local/bin/bauwerk"

echo "▶ Baue Mac-App …"
(cd app && cargo update -q -p mesh2step-core && cargo build --release)

echo "▶ Packe Bauwerk.app …"
APP="$WURZEL/target/Bauwerk.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp app/target/release/Bauwerk "$APP/Contents/MacOS/Bauwerk"
# Symbol
SET="$(mktemp -d)/Bauwerk.iconset"; mkdir -p "$SET"
for g in 16 32 128 256 512; do
  sips -z $g $g app/resources/icon-1024.png --out "$SET/icon_${g}x${g}.png" >/dev/null
  sips -z $((g*2)) $((g*2)) app/resources/icon-1024.png --out "$SET/icon_${g}x${g}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$APP/Contents/Resources/Bauwerk.icns"
VERSION=$(grep -m1 '^version' app/Cargo.toml | cut -d'"' -f2)
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Bauwerk</string>
  <key>CFBundleDisplayName</key><string>Bauwerk</string>
  <key>CFBundleIdentifier</key><string>de.mitkiprogrammieren.bauwerk</string>
  <key>CFBundleExecutable</key><string>Bauwerk</string>
  <key>CFBundleIconFile</key><string>Bauwerk</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true

ZIEL="/Applications/Bauwerk.app"
[ -w /Applications ] || ZIEL="$HOME/Applications/Bauwerk.app"
mkdir -p "$(dirname "$ZIEL")"
rm -rf "$ZIEL"
cp -R "$APP" "$ZIEL"
echo
echo "✅ Fertig: $ZIEL (Version $VERSION)"
echo "   Projekte liegen in ~/Bauwerk"
echo "   Kommandozeile: ~/.local/bin/bauwerk  (bauwerk app | server | mcp | run teil.json --out teil.step)"
echo
echo "MCP für Claude:"
echo "   Claude Code:     claude mcp add bauwerk -- $HOME/.local/bin/bauwerk mcp"
echo "   Laufende App:    http://127.0.0.1:8765/mcp"
open "$ZIEL"
