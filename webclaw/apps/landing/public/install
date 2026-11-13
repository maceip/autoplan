#!/usr/bin/env bash
set -euo pipefail

APP_DIR="webclaw"
TRACKING_URL="https://collector.onedollarstats.com/events"
EVENT_URL="https://webclaw.dev/install"

function track_install() {
  if ! command -v curl >/dev/null 2>&1; then
    return
  fi

  local os
  local arch
  local payload
  os="$(uname -s 2>/dev/null || echo "unknown")"
  arch="$(uname -m 2>/dev/null || echo "unknown")"
  payload=$(printf '{"u":"%s","e":[{"t":"install","p":{"source":"install-script","os":"%s","arch":"%s"}}]}' "$EVENT_URL" "$os" "$arch")

  curl -sS -X POST \
    -H "Content-Type: application/json" \
    -H "Origin: https://webclaw.dev" \
    -H "Referer: https://webclaw.dev/" \
    -d "$payload" \
    "$TRACKING_URL" >/dev/null 2>&1 || true
}

track_install

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but not found."
  exit 1
fi

if [ -d "$APP_DIR" ]; then
  echo "Directory '$APP_DIR' already exists. Skipping init."
else
  npx webclaw --project-name "$APP_DIR" --yes --no-start
fi

echo ""
echo "Next step: cd $APP_DIR && pnpm install && pnpm -C apps/webclaw dev"
