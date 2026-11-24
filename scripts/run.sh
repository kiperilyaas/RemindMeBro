#!/usr/bin/env bash
# =============================================================================
#  Remind Me Bro - Run & Go (macOS / Linux)
#
#  Installs everything that is missing, starts the app and opens the browser.
#  Nothing is installed system-wide on macOS: uv, Python, the virtualenv and
#  (if needed) Ollama all live in the project's ".runtime" folder.
#  The AI model is stored by Ollama in ~/.ollama (about 2 GB).
#
#  Options (environment variables):
#    RMB_MODEL=llama3.2     Ollama model to use (default: llama3.2)
#    RMB_NO_AI=1            skip Ollama completely (app works, AI features off)
#    RMB_NO_BROWSER=1       do not open the browser
#    RMB_SHARE=1            also open a public ngrok link to the hub + QR code
#                           (run-share-* set it; NGROK_AUTHTOKEN=... skips the question)
# =============================================================================
set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RT="$APP_DIR/.runtime"
VENV="$RT/venv"
LOGS="$RT/logs"
MODEL="${RMB_MODEL:-llama3.2}"
PY_VERSION="3.12"
OLLAMA_URL="http://127.0.0.1:11434"
OS="$(uname -s)"
ARCH="$(uname -m)"

BACKEND_PID=""
UNISIS_PID=""
UNILEARN_PID=""
OLLAMA_PID=""
NGROK_PID=""

# ---------- output helpers ----------
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=""; G=""; Y=""; R=""; C=""; N=""; fi
step() { printf "\n%s==>%s %s%s%s\n" "$C" "$N" "$B" "$*" "$N"; }
ok()   { printf "    %s✓%s %s\n" "$G" "$N" "$*"; }
warn() { printf "    %s!%s %s\n" "$Y" "$N" "$*"; }
die()  {
  printf "\n%s✗ %s%s\n" "$R" "$*" "$N"
  printf "  Logs: %s\n" "$LOGS"
  printf "\nPress Enter to close this window..."; read -r _ || true
  exit 1
}

cleanup() {
  trap - EXIT INT TERM HUP
  echo
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Stopping the app..."; kill "$BACKEND_PID" 2>/dev/null; wait "$BACKEND_PID" 2>/dev/null
  fi
  if [ -n "$UNILEARN_PID" ] && kill -0 "$UNILEARN_PID" 2>/dev/null; then
    echo "Stopping UniLearn..."; kill "$UNILEARN_PID" 2>/dev/null; wait "$UNILEARN_PID" 2>/dev/null
  fi
  if [ -n "$UNISIS_PID" ] && kill -0 "$UNISIS_PID" 2>/dev/null; then
    echo "Stopping UniSIS..."; kill "$UNISIS_PID" 2>/dev/null; wait "$UNISIS_PID" 2>/dev/null
  fi
  if [ -n "$NGROK_PID" ] && kill -0 "$NGROK_PID" 2>/dev/null; then
    echo "Closing the public link..."; kill "$NGROK_PID" 2>/dev/null
  fi
  if [ -n "$OLLAMA_PID" ] && kill -0 "$OLLAMA_PID" 2>/dev/null; then
    echo "Stopping Ollama..."; kill "$OLLAMA_PID" 2>/dev/null
  fi
  echo "Bye!"
}

http_ok() { curl -fsS --max-time 3 "$1" >/dev/null 2>&1; }

download() { # url dest
  curl -fL --retry 3 --connect-timeout 15 --progress-bar -o "$2" "$1" || die "Download failed: $1 (check the internet connection)"
}

open_browser() {
  [ "${RMB_NO_BROWSER:-0}" = "1" ] && return 0
  if [ "$OS" = "Darwin" ]; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 &
  else warn "Open $1 in your browser"; fi
}

# ---------- share with friends: ngrok tunnel to the hub + QR code ----------
start_share() {
  step "Link for friends (ngrok)"
  local NGROK="" PKG="" TOKEN="" CFG=""
  if [ -x "$RT/ngrok/ngrok" ]; then NGROK="$RT/ngrok/ngrok"
  elif command -v ngrok >/dev/null 2>&1; then NGROK="$(command -v ngrok)"
  else
    case "$OS-$ARCH" in
      Darwin-arm64)              PKG="darwin-arm64.zip" ;;
      Darwin-x86_64)             PKG="darwin-amd64.zip" ;;
      Linux-x86_64)              PKG="linux-amd64.tgz" ;;
      Linux-aarch64|Linux-arm64) PKG="linux-arm64.tgz" ;;
    esac
    echo "    Downloading ngrok (first time only)..."
    mkdir -p "$RT/ngrok"
    curl -fL --retry 3 --connect-timeout 15 --progress-bar -o "$RT/ngrok/$PKG" \
      "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-$PKG" \
      || { warn "Could not download ngrok: the app works only on this computer"; return 1; }
    case "$PKG" in
      *.zip) unzip -oq "$RT/ngrok/$PKG" -d "$RT/ngrok" ;;
      *)     tar -xzf "$RT/ngrok/$PKG" -C "$RT/ngrok" ;;
    esac
    rm -f "$RT/ngrok/$PKG"; chmod +x "$RT/ngrok/ngrok" 2>/dev/null
    [ "$OS" = "Darwin" ] && xattr -d com.apple.quarantine "$RT/ngrok/ngrok" 2>/dev/null
    NGROK="$RT/ngrok/ngrok"
  fi
  [ -x "$NGROK" ] || { warn "ngrok not found: the app works only on this computer"; return 1; }
  ok "ngrok $("$NGROK" version 2>/dev/null | awk '{print $3}')"

  # ngrok needs a free account token, asked once and kept in ngrok's own settings
  if [ -n "${NGROK_AUTHTOKEN:-}" ]; then "$NGROK" config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null 2>&1; fi
  CFG="$("$NGROK" config check 2>/dev/null | sed -n 's/.*configuration file at //p')"
  if [ -z "$CFG" ] || ! grep -q "authtoken" "$CFG" 2>/dev/null; then
    echo
    echo "    ngrok needs your (free) authtoken, only the first time:"
    echo "      1. sign up / log in at https://dashboard.ngrok.com"
    echo "      2. copy the token from https://dashboard.ngrok.com/get-started/your-authtoken"
    printf "    Paste it here and press Enter (empty = skip): "
    read -r TOKEN || TOKEN=""
    TOKEN="$(printf "%s" "$TOKEN" | tr -d '[:space:]')"
    [ -n "$TOKEN" ] || { warn "No token: the app works only on this computer"; return 1; }
    "$NGROK" config add-authtoken "$TOKEN" >/dev/null 2>&1 || { warn "ngrok did not accept the token"; return 1; }
    ok "Token saved"
  fi

  "$NGROK" http "$PORT" --log=stdout --log-format=logfmt > "$LOGS/ngrok.log" 2>&1 &
  NGROK_PID=$!
  if ! PYTHONIOENCODING=utf-8 "$VENV/bin/python" "$APP_DIR/scripts/share.py" --out "$RT/share" --log "$LOGS/ngrok.log"; then
    kill "$NGROK_PID" 2>/dev/null; NGROK_PID=""
    warn "No public link: the app works only on this computer (log: $LOGS/ngrok.log)"
    return 1
  fi
  open_browser "$RT/share/qr.html"
  printf "\n    %sFriends open the link or scan the QR code.%s It works while this window stays open.\n" "$B" "$N"
  printf "    The ngrok page \"You are about to visit\" may appear first: press \"Visit Site\".\n"
}

# ---------- 0. preliminary checks ----------
printf "%s\n" "${B}Remind Me Bro · Run & Go${N}  (Academic Unified Hub & AI Assistant)"
printf "First start: 5–15 minutes (downloads ~2.5 GB). Next starts: a few seconds.\n"
cd "$APP_DIR" || die "Cannot open $APP_DIR"
mkdir -p "$RT/bin" "$LOGS"
command -v curl >/dev/null 2>&1 || die "curl is required. Install it (e.g. sudo apt install curl) and run again."
command -v tar  >/dev/null 2>&1 || die "tar is required."

if [ "$OS" = "Darwin" ]; then
  # Files received via AirDrop/zip are "quarantined": unlock our own folder (no admin needed)
  find "$APP_DIR" -path "$RT" -prune -o -print0 2>/dev/null | xargs -0 xattr -d com.apple.quarantine 2>/dev/null || true
  MACOS_MAJOR="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"
  if [ -n "$MACOS_MAJOR" ] && [ "$MACOS_MAJOR" -lt 14 ] 2>/dev/null; then
    warn "macOS $(sw_vers -productVersion): Ollama needs macOS 14 Sonoma or newer. The app will start, the AI may not."
  fi
fi

# Already running? Then just open it.
for p in 8000 8001 8002 8003 8004 8005; do
  if curl -fsS --max-time 2 "http://127.0.0.1:$p/api/health" 2>/dev/null | grep -q "Academic Unified Hub"; then
    ok "The app is already running on port $p"
    open_browser "http://127.0.0.1:$p/"
    exit 0
  fi
done

trap cleanup EXIT INT TERM HUP

# ---------- 1. uv (Python manager, single binary) ----------
step "1/5  Python tools"
case "$OS-$ARCH" in
  Darwin-arm64)            UV_TARGET="aarch64-apple-darwin" ;;
  Darwin-x86_64)           UV_TARGET="x86_64-apple-darwin" ;;
  Linux-x86_64)            UV_TARGET="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64|Linux-arm64) UV_TARGET="aarch64-unknown-linux-gnu" ;;
  *) die "Unsupported system: $OS $ARCH" ;;
esac
if [ -x "$RT/bin/uv" ]; then UV="$RT/bin/uv"
elif command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"
else
  echo "    Downloading uv..."
  download "https://github.com/astral-sh/uv/releases/latest/download/uv-$UV_TARGET.tar.gz" "$RT/uv.tar.gz"
  tar -xzf "$RT/uv.tar.gz" -C "$RT" || die "Cannot extract uv"
  mv "$RT/uv-$UV_TARGET/uv" "$RT/bin/uv" && rm -rf "$RT/uv-$UV_TARGET" "$RT/uv.tar.gz"
  UV="$RT/bin/uv"
fi
export UV_PYTHON_INSTALL_DIR="$RT/python"   # Python lives inside the project folder
export UV_PYTHON_PREFERENCE=only-managed     # ignore system/Homebrew Pythons: same setup everywhere
ok "uv $("$UV" --version 2>/dev/null | awk '{print $2}')"

# ---------- 2. Python + dependencies ----------
step "2/5  Python $PY_VERSION and app dependencies"
REQ_STAMP="$(cksum < requirements.txt | awk '{print $1}')"
# The environment stores absolute paths: if the folder was moved, renamed or copied
# (e.g. "RemindMeBro 4"), its python no longer works and it must be rebuilt.
if ! "$VENV/bin/python" -c "import sys" >/dev/null 2>&1; then
  rm -rf "$VENV" "$RT/.req_stamp"
  "$UV" venv "$VENV" --python "$PY_VERSION" --quiet || die "Cannot create the Python environment"
fi
# Reinstall when requirements.txt changed or a package is missing (the stamp alone can lie)
if [ "$(cat "$RT/.req_stamp" 2>/dev/null)" != "$REQ_STAMP" ] \
   || ! "$VENV/bin/python" -c "import uvicorn, fastapi, sqlalchemy, chromadb, ollama, jose, passlib, jinja2, httpx" >/dev/null 2>&1; then
  echo "    Installing packages (first time only, ~1-3 min)..."
  "$UV" pip install --python "$VENV/bin/python" -r requirements.txt > "$LOGS/pip.log" 2>&1 \
    || { tail -n 20 "$LOGS/pip.log"; die "Package installation failed"; }
  echo "$REQ_STAMP" > "$RT/.req_stamp"
fi
ok "$("$VENV/bin/python" --version)"

# ---------- 3. Ollama ----------
step "3/5  Local AI (Ollama + $MODEL)"
OLLAMA=""
if [ "${RMB_NO_AI:-0}" = "1" ]; then
  warn "RMB_NO_AI=1: skipping Ollama (AI features will show as unavailable)"
else
  if command -v ollama >/dev/null 2>&1; then OLLAMA="$(command -v ollama)"
  elif [ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]; then OLLAMA="/Applications/Ollama.app/Contents/Resources/ollama"
  elif [ -x "$HOME/Applications/Ollama.app/Contents/Resources/ollama" ]; then OLLAMA="$HOME/Applications/Ollama.app/Contents/Resources/ollama"
  elif [ -x "$RT/ollama/ollama" ]; then OLLAMA="$RT/ollama/ollama"
  fi

  if [ -z "$OLLAMA" ]; then
    if [ "$OS" = "Darwin" ]; then
      echo "    Downloading Ollama (~175 MB, stays inside this folder)..."
      mkdir -p "$RT/ollama"
      download "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz" "$RT/ollama.tgz"
      tar -xzf "$RT/ollama.tgz" -C "$RT/ollama" || die "Cannot extract Ollama"
      rm -f "$RT/ollama.tgz"
      xattr -dr com.apple.quarantine "$RT/ollama" 2>/dev/null || true
      OLLAMA="$RT/ollama/ollama"
    else
      echo "    Ollama is not installed. The official installer needs your password (sudo)."
      printf "    Install Ollama now? [Y/n] "; read -r answer || answer="y"
      case "$answer" in n|N|no|NO) die "Ollama is required for the AI. Run again with RMB_NO_AI=1 to start without it." ;; esac
      curl -fsSL https://ollama.com/install.sh | sh || die "Ollama installation failed"
      OLLAMA="$(command -v ollama)"
    fi
  fi
  [ -x "$OLLAMA" ] || die "Ollama not found after installation"
  ok "Ollama: $OLLAMA"

  if http_ok "$OLLAMA_URL/api/version"; then
    ok "Ollama server already running"
  else
    "$OLLAMA" serve > "$LOGS/ollama.log" 2>&1 &
    OLLAMA_PID=$!
    for _ in $(seq 1 40); do http_ok "$OLLAMA_URL/api/version" && break; sleep 0.5; done
    http_ok "$OLLAMA_URL/api/version" || { tail -n 15 "$LOGS/ollama.log"; die "Ollama did not start"; }
    ok "Ollama server started"
  fi

  case "$MODEL" in *:*) MODEL_TAG="$MODEL" ;; *) MODEL_TAG="$MODEL:latest" ;; esac
  if curl -fsS "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "\"name\":\"$MODEL_TAG\""; then
    ok "Model $MODEL_TAG already downloaded"
  else
    echo "    Downloading the AI model $MODEL (~2 GB, first time only)..."
    "$OLLAMA" pull "$MODEL" || die "Model download failed"
    ok "Model $MODEL ready"
  fi
fi
export OLLAMA_MODEL="$MODEL"
export OLLAMA_HOST="$OLLAMA_URL"

# ---------- 4. Semantic search model (ChromaDB embeddings, ~80 MB, once) ----------
step "4/5  Semantic search"
export ANONYMIZED_TELEMETRY=False
if [ ! -f "$RT/.embeddings_ready" ]; then
  echo "    Preparing the search model (first time only)..."
  if "$VENV/bin/python" -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm up'])" > "$LOGS/embeddings.log" 2>&1; then
    touch "$RT/.embeddings_ready"; ok "Ready"
  else
    warn "Could not prepare it now: it will be downloaded on the first Sync"
  fi
else
  ok "Ready"
fi

# ---------- 5. Start the app ----------
step "5/5  Starting UniSIS, UniLearn and Remind Me Bro"
free_port() { # first free port in [$1, $2]
  for p in $(seq "$1" "$2"); do
    if "$VENV/bin/python" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', $p)); s.close()" 2>/dev/null; then echo "$p"; return 0; fi
  done
  return 1
}

# UniSIS: our student information system (separate service, real OAuth 2.0 API)
# The hub's port is chosen first so UniSIS and UniLearn can link back to it ("open the student hub")
PORT="$(free_port 8000 8010)" || die "No free port between 8000 and 8010"
export RMB_HUB_URL="http://127.0.0.1:$PORT/"
UPORT="$(free_port 8100 8110)" || die "No free port between 8100 and 8110 for UniSIS"
UNISIS_URL="http://127.0.0.1:$UPORT"
UNISIS_PUBLIC_URL="$UNISIS_URL" "$VENV/bin/python" -m uvicorn unisis.main:app --host 127.0.0.1 --port "$UPORT" > "$LOGS/unisis.log" 2>&1 &
UNISIS_PID=$!
for _ in $(seq 1 60); do
  http_ok "$UNISIS_URL/.well-known/oauth-authorization-server" && break
  kill -0 "$UNISIS_PID" 2>/dev/null || break
  sleep 0.5
done
http_ok "$UNISIS_URL/.well-known/oauth-authorization-server" || { tail -n 25 "$LOGS/unisis.log"; die "UniSIS did not start"; }
ok "UniSIS running at $UNISIS_URL"
export UNISIS_URL

# UniLearn: our Moodle-compatible LMS (separate service, Moodle web-service API)
LPORT="$(free_port 8200 8210)" || die "No free port between 8200 and 8210 for UniLearn"
UNILEARN_URL="http://127.0.0.1:$LPORT"
UNILEARN_PUBLIC_URL="$UNILEARN_URL" "$VENV/bin/python" -m uvicorn unilearn.main:app --host 127.0.0.1 --port "$LPORT" > "$LOGS/unilearn.log" 2>&1 &
UNILEARN_PID=$!
for _ in $(seq 1 60); do
  http_ok "$UNILEARN_URL/login" && break
  kill -0 "$UNILEARN_PID" 2>/dev/null || break
  sleep 0.5
done
http_ok "$UNILEARN_URL/login" || { tail -n 25 "$LOGS/unilearn.log"; die "UniLearn did not start"; }
ok "UniLearn running at $UNILEARN_URL"
export UNILEARN_URL


"$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > "$LOGS/backend.log" 2>&1 &
BACKEND_PID=$!
for _ in $(seq 1 90); do
  http_ok "http://127.0.0.1:$PORT/api/health" && break
  kill -0 "$BACKEND_PID" 2>/dev/null || break
  sleep 0.5
done
http_ok "http://127.0.0.1:$PORT/api/health" || { tail -n 25 "$LOGS/backend.log"; die "The app did not start"; }

URL="http://127.0.0.1:$PORT/"
ok "Running at $URL"
# every staff password in one file (the services write their own part at start-up)
STAFF_FILE="$APP_DIR/data/STAFF-PASSWORDS.txt"
{ echo "# Staff passwords of the demo. Only on this computer: never share this file or show it on screen."; echo
  for f in "$APP_DIR/data/STAFF-PASSWORDS-hub.txt" "$APP_DIR/data/unisis/STAFF-PASSWORDS.txt" "$APP_DIR/data/unilearn/STAFF-PASSWORDS.txt"; do
    [ -f "$f" ] && { cat "$f"; echo; }
  done; } > "$STAFF_FILE" 2>/dev/null && chmod 600 "$STAFF_FILE" 2>/dev/null
open_browser "$URL"

cat <<EOF

${G}${B}Remind Me Bro is running${N}  →  $URL   (previous interface: ${URL}classic)

  Students create their own account on the sign-in page ("Create account"). Demo student: student@demo.it
  Lecturers and staff sign in ONLY on this computer. Their passwords: ${B}data/STAFF-PASSWORDS.txt${N}

  UniSIS (student information system)  →  $UNISIS_URL
    Student Office  registrar                    →  $UNISIS_URL/staff  (courses, timetable, exams, apps & keys)

  UniLearn (Moodle-compatible LMS)     →  $UNILEARN_URL
    Teaching        marco.rossi, laura.bianchi, ...  →  $UNILEARN_URL/staff  (create courses)
    Admin           admin                        (also Web services: live API call log and tokens)

  Everything starts empty and today's date is used. Create courses in UniLearn /staff and UniSIS /staff
  (same code in both), then as Giulia: Connect → UniLearn and UniSIS, and Sync. Your data is kept.

${Y}Keep this window open.${N} Close it (or press Ctrl+C) to stop the app.
EOF

[ "${RMB_SHARE:-0}" = "1" ] && start_share

wait "$BACKEND_PID"
