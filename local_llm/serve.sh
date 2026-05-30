#!/usr/bin/env bash
#
# serve.sh — start the DFlash-MLX OpenAI-compatible server.
#
# DFlash (z-lab) is block-diffusion *speculative decoding*: a lightweight draft
# model proposes a block of tokens that the target model verifies in parallel.
# Output is bit-for-bit identical to plain target decoding — pure speedup, no
# quality loss. This runs the Apple-Silicon (MLX) port `dflash-mlx`.
#
# Usage:
#   ./serve.sh                       # auto-discover the target model in ~/Downloads/Models
#   MODEL="Qwen3.6-27B-4bit" ./serve.sh
#   MODEL=/abs/path/to/model ./serve.sh
#   PORT=8001 ./serve.sh
#   DRAFT=/abs/path/to/draft ./serve.sh   # optional; omit to auto-resolve from the z-lab registry
#
# Then call it like any OpenAI endpoint at http://$HOST:$PORT/v1
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"
DFLASH="$HERE/.venv/bin/dflash"

MODELS_DIR="${MODELS_DIR:-$HOME/Downloads/Models}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# Default target when none is set and nothing is found locally: pull this
# 4-bit MLX build from HuggingFace. Its DFlash draft (z-lab/Qwen3.6-35B-A3B-DFlash)
# auto-resolves from the z-lab registry.
DEFAULT_MODEL="${DEFAULT_MODEL:-mlx-community/Qwen3.6-35B-A3B-4bit}"

if [[ ! -x "$DFLASH" ]]; then
  echo "error: dflash CLI not found at $DFLASH" >&2
  echo "       create the venv and install:  python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

# --- Resolve the target model -------------------------------------------------
# A "model" directory is one containing config.json. Anything whose name
# contains "DFlash" is treated as a draft, not a target.
resolve_model() {
  # explicit override wins (local path or HuggingFace repo id)
  if [[ -n "${MODEL:-}" ]]; then
    if [[ -d "$MODELS_DIR/$MODEL" ]]; then echo "$MODELS_DIR/$MODEL"; else echo "$MODEL"; fi
    return
  fi
  if [[ ! -d "$MODELS_DIR" ]]; then
    echo "$DEFAULT_MODEL"   # nothing local; fall back to the HuggingFace default
    return
  fi
  local candidates=()
  while IFS= read -r cfg; do
    local d; d="$(dirname "$cfg")"
    [[ "$(basename "$d")" == *DFlash* ]] && continue   # skip drafts
    candidates+=("$d")
  done < <(find "$MODELS_DIR" -maxdepth 2 -name config.json 2>/dev/null)

  if [[ ${#candidates[@]} -eq 0 ]]; then
    echo "$DEFAULT_MODEL"   # nothing local; fall back to the HuggingFace default
    return
  elif [[ ${#candidates[@]} -gt 1 ]]; then
    echo "error: multiple models found under $MODELS_DIR — set MODEL to choose one:" >&2
    printf '         - %s\n' "${candidates[@]}" >&2
    exit 1
  fi
  echo "${candidates[0]}"
}

# --- Resolve the draft (optional) --------------------------------------------
# If DRAFT is set, use it. Otherwise look for a local *DFlash* dir next to the
# target; if none, omit --draft so dflash pulls the matching drafter from the
# z-lab registry on HuggingFace.
resolve_draft() {
  if [[ -n "${DRAFT:-}" ]]; then
    if [[ -d "$MODELS_DIR/$DRAFT" ]]; then echo "$MODELS_DIR/$DRAFT"; else echo "$DRAFT"; fi
    return
  fi
  local d
  d="$(find "$MODELS_DIR" -maxdepth 2 -name config.json 2>/dev/null \
        | xargs -I{} dirname {} 2>/dev/null \
        | grep -i DFlash | head -n1 || true)"
  echo "$d"
}

MODEL_PATH="$(resolve_model)"
DRAFT_PATH="$(resolve_draft)"

echo "DFlash server starting"
echo "  target model : $MODEL_PATH"
if [[ -n "$DRAFT_PATH" ]]; then
  echo "  draft model  : $DRAFT_PATH (local)"
else
  echo "  draft model  : (auto-resolved from z-lab registry)"
fi
echo "  endpoint     : http://$HOST:$PORT/v1"
# Thinking is OFF by default — this model's chat template enables it otherwise.
# Re-enable with THINKING=1 ./serve.sh if you ever want reasoning traces.
if [[ "${THINKING:-0}" == "1" ]]; then
  echo "  thinking     : on"
else
  echo "  thinking     : off"
fi
echo

ARGS=(serve --model "$MODEL_PATH" --host "$HOST" --port "$PORT")
[[ -n "$DRAFT_PATH" ]] && ARGS+=(--draft "$DRAFT_PATH")
if [[ "${THINKING:-0}" == "1" ]]; then
  ARGS+=(--enable-thinking)
else
  ARGS+=(--chat-template-args '{"enable_thinking": false}')
fi

# Run forever: keep the server up, restarting it if it ever exits/crashes.
# Set RESTART=0 to run a single instance in the foreground instead.
if [[ "${RESTART:-1}" == "0" ]]; then
  exec "$DFLASH" "${ARGS[@]}" "$@"
fi

trap 'echo; echo "serve.sh: shutting down"; exit 0' INT TERM
while true; do
  "$DFLASH" "${ARGS[@]}" "$@" || true
  echo "serve.sh: server exited (code $?). Restarting in 3s… (Ctrl-C to stop)" >&2
  sleep 3
done
