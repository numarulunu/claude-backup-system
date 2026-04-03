#!/bin/bash
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

# Auto-detect Python
PYTHON=""
for cmd in python3 python /c/Python314/python /c/Python312/python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python not found. Install Python 3.10+ and add to PATH." >&2
    exit 1
fi

exec >> "$LOGFILE" 2>&1
echo "=== Memory Digest Generator — $(date) ==="
echo "  Python: $PYTHON ($($PYTHON --version 2>&1))"

if [ "${1:-}" = "--all" ] 2>/dev/null; then
    echo "  Running FULL historical extraction..."
    if ! $PYTHON "$SCRIPT_DIR/memory-sync.py" --all --output-dir "$DIGEST_DIR"; then
        echo "ERROR: Digest generation failed."
        exit 1
    fi
else
    DAYS=${1:-1}
    echo "  Scanning last $DAYS day(s)..."
    if ! $PYTHON "$SCRIPT_DIR/memory-sync.py" --days "$DAYS" --output-dir "$DIGEST_DIR"; then
        echo "ERROR: Digest generation failed."
        exit 1
    fi
fi

echo "=== Done $(date) ==="
