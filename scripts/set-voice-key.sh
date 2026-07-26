#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Mood AI — set the voice provider key (OPENAI_API_KEY) and self-check voice.
#
# Voice (Whisper STT + TTS, read-aloud, realtime voice WS, video voiceovers) is
# the one feature gated behind OPENAI_API_KEY — backend/app/services/voice.py
# raises VoiceNotConfigured and the routes answer 503 until it is set.
#
# What this script does:
#   1. writes OPENAI_API_KEY (and optional OPENAI_BASE_URL) into ./.env
#      (creating it from .env.example first, exactly like provision-env.sh),
#   2. self-checks the key against the provider: auth → TTS → Whisper STT,
#      i.e. it speaks a sentence and transcribes its own audio back,
#   3. optionally probes a DEPLOYED backend's /voice/tts with your token.
#
# The key is never echoed in full and never leaves .env (which is gitignored).
#
# Usage:
#   scripts/set-voice-key.sh                      # prompt (hidden input), then check
#   scripts/set-voice-key.sh sk-proj-...          # set from argument, then check
#   OPENAI_API_KEY=sk-... scripts/set-voice-key.sh --from-env
#   scripts/set-voice-key.sh --check              # check only, never touch .env
#   scripts/set-voice-key.sh --check --api https://api.example.com --token <jwt>
#
# Options:
#   --check              only run the self-check (uses .env / environment key)
#   --from-env           take the key from $OPENAI_API_KEY, no prompt
#   --base-url URL       OpenAI-compatible endpoint (default https://api.openai.com/v1)
#   --env-file PATH      target env file (default ./.env)
#   --api BASE           also probe a deployed Mood AI API (https://host)
#   --token JWT          bearer token for --api (from POST /api/v1/auth/login)
#   --no-check           write the key, skip the live self-check
#   -h | --help          this help
#
# Exit code: 0 = every enabled check passed · 1 = something needs attention.
# ─────────────────────────────────────────────────────────────────────────────
set -u
cd "$(dirname "$0")/.."

CHECK_ONLY=0
FROM_ENV=0
DO_CHECK=1
ENV_FILE=".env"
BASE_URL=""
API_BASE=""
API_TOKEN=""
KEY_ARG=""
FAILED=0

pass() { printf '\033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m  %s — %s\n' "$1" "$2"; FAILED=$((FAILED + 1)); }
skip() { printf '\033[33mSKIP\033[0m  %s\n' "$1"; }
info() { printf '\033[36m·\033[0m     %s\n' "$1"; }

usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check)     CHECK_ONLY=1; shift ;;
    --from-env)  FROM_ENV=1; shift ;;
    --no-check)  DO_CHECK=0; shift ;;
    --base-url)  BASE_URL="${2:-}"; shift 2 ;;
    --env-file)  ENV_FILE="${2:-}"; shift 2 ;;
    --api)       API_BASE="${2:-}"; shift 2 ;;
    --token)     API_TOKEN="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    -*)          echo "unknown option: $1" >&2; exit 2 ;;
    *)           KEY_ARG="$1"; shift ;;
  esac
done

mask() { # mask KEY → sk-proj…AbCd (never prints the middle)
  python3 - "$1" << 'PY'
import sys
k = sys.argv[1]
print(k[:7] + "…" + k[-4:] if len(k) > 14 else "…" + k[-3:])
PY
}

envget() { # envget KEY [FILE] — read a value out of an env file
  [ -f "${2:-$ENV_FILE}" ] || return 0
  grep -m1 "^$1=" "${2:-$ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '\r'
}

setkv() { # setkv KEY VALUE — replace or append (same contract as provision-env.sh)
  if grep -q "^$1=" "$ENV_FILE" 2>/dev/null; then
    python3 - "$1" "$2" "$ENV_FILE" << 'PY'
import re, sys
k, v, p = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p).read()
s = re.sub(rf"^{re.escape(k)}=.*$", f"{k}={v}", s, count=1, flags=re.M)
open(p, "w").write(s)
PY
  else
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  fi
}

echo "Mood AI — voice key (OPENAI_API_KEY)"
echo "────────────────────────────────────────────"

# ── 1. resolve the key ───────────────────────────────────────────────────────
KEY=""
if [ -n "$KEY_ARG" ]; then
  KEY="$KEY_ARG"
elif [ "$FROM_ENV" = "1" ] || [ "$CHECK_ONLY" = "1" ]; then
  KEY="${OPENAI_API_KEY:-}"
  [ -z "$KEY" ] && KEY="$(envget OPENAI_API_KEY)"
else
  KEY="${OPENAI_API_KEY:-}"
  if [ -z "$KEY" ]; then
    if [ -t 0 ] || [ -e /dev/tty ]; then
      printf '🔑 Paste your OpenAI API key (input hidden, Enter to abort): ' > /dev/tty
      stty -echo < /dev/tty 2>/dev/null
      read -r KEY < /dev/tty || true
      stty echo < /dev/tty 2>/dev/null
      printf '\n' > /dev/tty
    fi
  else
    info "key taken from the environment"
  fi
fi

KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"

if [ -z "$KEY" ]; then
  echo ""
  echo "No key supplied. Create one first:"
  echo "  1. https://platform.openai.com/api-keys → Create new secret key"
  echo "  2. Add credit at https://platform.openai.com/settings/organization/billing"
  echo "     (voice is pay-as-you-go: whisper-1 ≈ \$0.006/min, tts-1 ≈ \$15/1M chars)"
  echo "  3. Re-run: scripts/set-voice-key.sh sk-..."
  exit 1
fi

case "$KEY" in
  sk-*) : ;;
  *) info "heads-up: key does not start with 'sk-' (fine for a non-OpenAI compatible gateway)" ;;
esac

# ── 2. write it into the env file ────────────────────────────────────────────
if [ "$CHECK_ONLY" = "1" ]; then
  info "check-only mode — $ENV_FILE untouched (key $(mask "$KEY"))"
else
  if [ ! -f "$ENV_FILE" ]; then
    if [ -f .env.example ] && [ "$ENV_FILE" = ".env" ]; then
      cp .env.example "$ENV_FILE"
      info "$ENV_FILE created from .env.example"
    else
      : > "$ENV_FILE"
      info "$ENV_FILE created (empty)"
    fi
  fi

  # never let a secret land in a tracked file by accident
  if git ls-files --error-unmatch "$ENV_FILE" > /dev/null 2>&1; then
    fail "$ENV_FILE is tracked by git" "refusing to write a secret into a committed file"
    exit 1
  fi

  setkv OPENAI_API_KEY "$KEY"
  [ -n "$BASE_URL" ] && setkv OPENAI_BASE_URL "$BASE_URL"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  pass "OPENAI_API_KEY=$(mask "$KEY") written to $ENV_FILE"
fi

EP="${BASE_URL:-$(envget OPENAI_BASE_URL)}"
EP="${EP:-https://api.openai.com/v1}"
EP="${EP%/}"
WHISPER="$(envget WHISPER_MODEL)"; WHISPER="${WHISPER:-whisper-1}"
TTSM="$(envget TTS_MODEL)"; TTSM="${TTSM:-tts-1}"
TTSV="$(envget TTS_VOICE)"; TTSV="${TTSV:-alloy}"

if [ "$DO_CHECK" = "0" ]; then
  echo ""
  info "self-check skipped (--no-check). Restart the backend to pick the key up."
  exit 0
fi

echo ""
echo "Self-check → $EP  (stt=$WHISPER · tts=$TTSM/$TTSV)"
echo "────────────────────────────────────────────"

command -v curl > /dev/null 2>&1 || { fail "curl" "not installed — cannot self-check"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BODY="$TMP/body"
MP3="$TMP/probe.mp3"
PHRASE="Mood AI voice check one two three."
: > "$BODY"; : > "$MP3"          # curl writes nothing on a connection failure
bytes() { [ -f "$1" ] && wc -c < "$1" | tr -d ' ' || echo 0; }

# ── 3a. auth: can the key list models? ───────────────────────────────────────
code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 20 "$EP/models" -H "Authorization: Bearer $KEY")
case "$code" in
  200) pass "auth — GET /models accepted the key" ;;
  401|403) fail "auth — GET /models" "HTTP $code (invalid/revoked key, or wrong project) — $(head -c 160 "$BODY")" ;;
  000) fail "auth — GET /models" "no response from $EP (network/proxy/base-url wrong)" ;;
  *) fail "auth — GET /models" "HTTP $code — $(head -c 160 "$BODY")" ;;
esac

# ── 3b. TTS: synthesize a sentence ───────────────────────────────────────────
code=$(curl -s -o "$MP3" -w '%{http_code}' --max-time 60 "$EP/audio/speech" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"model\": \"$TTSM\", \"voice\": \"$TTSV\", \"input\": \"$PHRASE\"}")
BYTES=$(bytes "$MP3")
if [ "$code" = "200" ] && [ "${BYTES:-0}" -gt 1000 ]; then
  pass "TTS — POST /audio/speech → ${BYTES} bytes of audio ($TTSM/$TTSV)"
elif [ "$code" = "429" ]; then
  fail "TTS — POST /audio/speech" "HTTP 429: quota/rate limit — add billing credit at platform.openai.com"
else
  fail "TTS — POST /audio/speech" "HTTP $code — $(head -c 200 "$MP3" 2>/dev/null)"
fi

# ── 3c. STT: transcribe that same audio back (closes the voice loop) ─────────
if [ "${BYTES:-0}" -gt 1000 ]; then
  code=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 90 "$EP/audio/transcriptions" \
    -H "Authorization: Bearer $KEY" \
    -F "model=$WHISPER" -F "file=@$MP3;type=audio/mpeg")
  TEXT=$(python3 -c 'import json,sys
try: print((json.load(open(sys.argv[1])).get("text") or "").strip())
except Exception: print("")' "$BODY")
  if [ "$code" = "200" ] && [ -n "$TEXT" ]; then
    pass "STT — POST /audio/transcriptions → \"$TEXT\" ($WHISPER)"
  elif [ "$code" = "429" ]; then
    fail "STT — POST /audio/transcriptions" "HTTP 429: quota/rate limit"
  else
    fail "STT — POST /audio/transcriptions" "HTTP $code — $(head -c 200 "$BODY")"
  fi
else
  skip "STT — no audio from the TTS step to transcribe"
fi

# ── 4. optional: probe a deployed backend ────────────────────────────────────
if [ -n "$API_BASE" ]; then
  API="${API_BASE%/}"
  case "$API" in */api/v1) : ;; *) API="$API/api/v1" ;; esac
  if [ -z "$API_TOKEN" ]; then
    skip "deployed API — pass --token <jwt> (POST $API/auth/login) to probe /voice/tts"
  else
    : > "$TMP/api.mp3"
    code=$(curl -s -o "$TMP/api.mp3" -w '%{http_code}' --max-time 60 -X POST "$API/voice/tts" \
      -H "Authorization: Bearer $API_TOKEN" -H 'Content-Type: application/json' \
      -d '{"text": "Mood AI deployed voice check."}' 2>/dev/null)
    case "$code" in
      200) pass "deployed API — POST $API/voice/tts → audio ($(bytes "$TMP/api.mp3") bytes)" ;;
      503) fail "deployed API — POST /voice/tts" "HTTP 503: the SERVER has no OPENAI_API_KEY yet (set it in your host's variables + redeploy)" ;;
      401) fail "deployed API — POST /voice/tts" "HTTP 401: token expired/invalid" ;;
      *)   fail "deployed API — POST /voice/tts" "HTTP $code — $(head -c 200 "$TMP/api.mp3" 2>/dev/null)" ;;
    esac
  fi
fi

echo "────────────────────────────────────────────"
if [ "$FAILED" -eq 0 ]; then
  echo "✅ Voice provider ready."
  [ "$CHECK_ONLY" = "1" ] || cat << 'NEXT'

Next:
  • local dev     : restart the backend (docker compose up -d --build backend,
                    or re-run uvicorn) — settings are read at process start.
  • Railway/Render: add OPENAI_API_KEY in the service Variables → redeploy.
  • Fly.io        : fly secrets set OPENAI_API_KEY=sk-...
  • Vercel        : vercel env add OPENAI_API_KEY production → redeploy.
  Then verify the live server:
    scripts/set-voice-key.sh --check --api https://YOUR-API --token <jwt>
NEXT
  exit 0
fi
echo "❌ $FAILED check(s) failed — voice will 503 until they pass."
exit 1
