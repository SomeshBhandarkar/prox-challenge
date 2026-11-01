#!/usr/bin/env bash
# Run a browser check against the demo site (canned answers, no API key, no cost). Needs Node 22+ and Chrome or Chromium.
#   scripts/browser/run.sh page_flows       (about 70 checks of the chat page)
#   scripts/browser/run.sh voice_check      (the voice buttons, with a simulated microphone and speaker)
#   scripts/browser/run.sh guard_flow       (the manual-only guardrails on the real page; starts the demo server with --guard)
#   scripts/browser/run.sh new_features     (tap-to-answer questions and the clickable front panel)
# Screenshots and the server log go to ./browser-check-output/<name>/ (git-ignored). Each run uses its own free port and its own
# Chrome, and shuts both down hard at the end, so runs can never see each other's leftovers.
set -u
cd "$(dirname "$0")/../.."
name="${1:?usage: scripts/browser/run.sh page_flows|voice_check|guard_flow|new_features}"
out="browser-check-output/$name"
port="${PORT:-$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')}"
rm -rf "$out"; mkdir -p "$out"
extra=""; [ "$name" = "guard_flow" ] && extra="--guard"
.venv/bin/python -m scripts.dev_server --port "$port" $extra > "$out/server.log" 2>&1 &
server=$!
cleanup() { kill "$server" 2>/dev/null; sleep 0.3; kill -9 "$server" 2>/dev/null; }
trap cleanup EXIT
for _ in $(seq 1 60); do curl -sf "http://localhost:$port/api/health" > /dev/null && break; sleep 0.5; done
curl -sf "http://localhost:$port/api/health" > /dev/null || { echo "the demo server did not start; see $out/server.log"; exit 2; }
SITE="http://localhost:$port/" node "scripts/browser/$name.mjs" "$out" | tee "$out/result.txt"
exit "${PIPESTATUS[0]}"
