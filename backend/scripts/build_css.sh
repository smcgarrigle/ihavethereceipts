#!/usr/bin/env bash
# Build the precompiled Tailwind stylesheet (replaces the old browser Play runtime).
# Downloads the standalone CLI on first run — no Node required.
set -euo pipefail
cd "$(dirname "$0")/.."

CLI="tools/tailwindcss"
VERSION="v3.4.17"

if [ ! -x "$CLI" ]; then
  mkdir -p tools
  ARCH=$(uname -m); [ "$ARCH" = "aarch64" ] && ARCH="arm64" || ARCH="x64"
  OS=$(uname -s | tr '[:upper:]' '[:lower:]'); [ "$OS" = "darwin" ] && OS="macos"
  echo "Downloading tailwindcss $VERSION ($OS-$ARCH)..."
  curl -sL -o "$CLI" "https://github.com/tailwindlabs/tailwindcss/releases/download/$VERSION/tailwindcss-$OS-$ARCH"
  chmod +x "$CLI"
fi

"$CLI" -c tailwind.config.js -i static/css/tailwind.input.css -o static/css/tailwind.css --minify "$@"
echo "Built static/css/tailwind.css"
