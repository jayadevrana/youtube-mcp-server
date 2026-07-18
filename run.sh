#!/usr/bin/env bash
# Launch the YouTube MCP server (stdio), or run one-off subcommands.
#   ./run.sh              -> start the MCP server
#   ./run.sh authorize    -> one-time browser OAuth consent (mint refresh token)
#   ./run.sh rotate <id>  -> advance a pseudo-A/B thumbnail test one step
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# The `mcp` + google client packages need Python >= 3.10; system python3 is 3.9.
PYBIN="${YOUTUBE_MCP_PYTHON:-}"
if [ -z "$PYBIN" ]; then
  for c in python3.13 python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null 2>&1 && { PYBIN="$c"; break; }
  done
fi
if [ -z "$PYBIN" ]; then
  echo "Need Python >= 3.10. Try: brew install python@3.12" >&2
  exit 1
fi

# This project lives on an exFAT volume (/Volumes/NO NAME) where macOS creates
# AppleDouble "._*.pth" files that crash Python's site.py at venv startup.
# So build the venv on the INTERNAL disk; the code stays on the drive.
VENV="${YOUTUBE_MCP_VENV:-$HOME/.local/share/youtube-mcp/venv}"
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$(dirname "$VENV")"
  "$PYBIN" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"
fi

cd "$HERE"
case "${1:-serve}" in
  authorize) exec "$VENV/bin/python" authorize.py ;;
  rotate)    exec "$VENV/bin/python" ab_rotate.py "${2:?usage: ./run.sh rotate <video_id>}" ;;
  serve|"")  exec "$VENV/bin/python" server.py ;;
  *) echo "Unknown command: $1 (use: authorize | rotate <id> | serve)" >&2; exit 1 ;;
esac
