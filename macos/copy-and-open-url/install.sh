#!/bin/bash
# Build, ad-hoc sign, and install Copy & Open URL.app into ~/Applications/.
# Registers as an http/https handler so Velja lists it as a browser option;
# opening a URL with it copies the URL to the macOS clipboard, opens it in the
# default browser (bypassing Velja to avoid loops), and exits.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="$HOME/Applications/Copy & Open URL.app"
stage="$HOME/Applications/.Copy & Open URL.app.new.$$"

mkdir -p "$HOME/Applications"
rm -rf "$stage"
mkdir -p "$stage/Contents/MacOS" "$stage/Contents/Resources"
cp "$here/Info.plist" "$stage/Contents/Info.plist"

# ~/.bashrc may export DEVELOPER_DIR at a removed Xcode; CLT is enough here.
dev=/Library/Developer/CommandLineTools
[ -d "${DEVELOPER_DIR:-/nonexistent}" ] && dev="$DEVELOPER_DIR"
DEVELOPER_DIR="$dev" swiftc -O "$here/CopyAndOpenURL.swift" -o "$stage/Contents/MacOS/CopyAndOpenURL"

iconset="$stage/AppIcon.iconset"
DEVELOPER_DIR="$dev" swift "$here/make-icon.swift" "$iconset"
iconutil -c icns "$iconset" -o "$stage/Contents/Resources/AppIcon.icns"
rm -rf "$iconset"

codesign --force --deep --sign - "$stage"

rm -rf "$app"
mv "$stage" "$app"

lsreg="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "$lsreg" ]; then
  "$lsreg" -f "$app"
fi

echo "installed: $app"
