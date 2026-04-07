#!/bin/bash
export PATH="/usr/bin:/bin:/c/Program Files/Git/usr/bin:/c/Program Files/Git/bin:/c/Program Files/Git/mingw64/bin:/mingw64/bin:${PATH:-}"
set -euo pipefail

# update-memory.sh — Conversation Digest Generator (portable)
# Auto-detects Python. Works on any machine with Claude Code installed.
#
# Usage:
#   ./update-memory.sh              # Default: last 1 day
#   ./update-memory.sh 7            # Last 7 days
#   ./update-memory.sh --all        # Full historical pass

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIGEST_DIR="$SCRIPT_DIR/_digests"
LOGFILE="$SCRIPT_DIR/_memory-sync.log"

# shellcheck source=_detect-python.sh
source "$SCRIPT_DIR/_detect-python.sh"
# shellcheck source=_log-rotate.sh
source "$SCRIPT_DIR/_log-rotate.sh"

rotate_log "$LOGFILE"

exec >> "$LOGFILE" 2>&1
echo "=== Memory Digest Generator — $(date) ==="
echo "  Python: $PYTHON ($($PYTHON --version 2>&1))"

if [ "${1:-}" = "--all" ]; then
    echo "  Running FULL historical extraction..."
    if ! $PYTHON "$SCRIPT_DIR/memory-sync.py" --all --output-dir "$DIGEST_DIR"; then
        echo "ERROR: Digest generation failed."
        exit 1
    fi
else
    DAYS="${1:-1}"
    # Validate DAYS is a positive integer
    if ! [[ "$DAYS" =~ ^[0-9]+$ ]]; then
        echo "ERROR: DAYS must be a positive integer, got: $DAYS" >&2
        exit 1
    fi
    echo "  Scanning last $DAYS day(s)..."
    if ! $PYTHON "$SCRIPT_DIR/memory-sync.py" --days "$DAYS" --output-dir "$DIGEST_DIR"; then
        echo "ERROR: Digest generation failed."
        exit 1
    fi
fi

echo "=== Done $(date) ==="
