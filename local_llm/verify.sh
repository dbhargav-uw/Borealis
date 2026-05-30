#!/usr/bin/env bash
#
# verify.sh — smoke-test the local DFlash server, then shut it down.
#
# Every run:
#   1. clears anything listening on the port,
#   2. starts the server fresh (loads the model, thinking off),
#   3. waits for it to come up,
#   4. sends one chat completion and prints the reply,
#   5. STOPS the server (this is a test, not the always-on launcher — use
#      serve.sh for that).
#
# Usage:
#   ./verify.sh
#   MODEL="Qwen3.6-27B-4bit" ./verify.sh
#   PORT=8001 ./verify.sh
#   STARTUP_TIMEOUT=400 ./verify.sh        # seconds to wait for model load (default 300)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-300}"
BASE="http://$HOST:$PORT/v1"
LOG="$HERE/server.log"

SERVER_PID=""
stop_server() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "→ stopping server (pid $SERVER_PID)"
    # serve.sh runs a restart loop; kill the whole process group so the
    # supervisor and the dflash child both go down.
    kill -- -"$SERVER_PID" 2>/dev/null || kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap stop_server EXIT

fail() {
  echo "✗ FAIL: $*" >&2
  echo "--- server log (tail) ---" >&2
  tail -n 40 "$LOG" >&2 2>/dev/null || true
  exit 1
}

# --- 1. clear the port --------------------------------------------------------
PIDS="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  echo "→ clearing port $PORT (killing: $PIDS)"
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  for ((i=0; i<10; i++)); do
    lsof -ti "tcp:$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
  # shellcheck disable=SC2086
  kill -9 $PIDS 2>/dev/null || true
  sleep 1
fi

# --- 2. start the server fresh ------------------------------------------------
echo "→ starting DFlash server on $BASE (log: $LOG)"
set -m   # job control: put the server in its own process group so we can kill the whole tree
HOST="$HOST" PORT="$PORT" "$HERE/serve.sh" >"$LOG" 2>&1 &
SERVER_PID=$!
set +m

# --- 3. wait until it answers -------------------------------------------------
echo "→ waiting up to ${STARTUP_TIMEOUT}s for the model to load…"
ready=0
for ((i=0; i<STARTUP_TIMEOUT; i++)); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    fail "server process exited during startup"
  fi
  if curl -sf "$BASE/models" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || fail "endpoint did not become ready within ${STARTUP_TIMEOUT}s"
echo "✓ endpoint is up"

# --- 4. run one inference (thinking off) --------------------------------------
echo "→ sending a test chat completion…"
RESP="$(curl -sf "$BASE/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local",
    "messages": [{"role": "user", "content": "Reply with exactly the word: BOREALIS"}],
    "max_tokens": 64,
    "temperature": 0,
    "chat_template_args": {"enable_thinking": false}
  }')" || fail "chat completion request errored"

read -r SERVED_MODEL CONTENT < <(printf '%s' "$RESP" | python3 -c '
import sys, json
d = json.load(sys.stdin)
m = d["choices"][0]["message"]
text = (m.get("content") or m.get("reasoning_content") or "").strip().replace("\n", " ")
print(d.get("model", "?"), text)
' 2>/dev/null) || fail "could not parse response JSON:\n$RESP"

[[ -n "$CONTENT" ]] || fail "model returned an empty reply:\n$RESP"

echo
echo "✓ PASS"
echo "  model:    $SERVED_MODEL"
echo "  response: $CONTENT"
echo
echo "Verification done. Stopping the server (run ./serve.sh for the always-on instance)."
