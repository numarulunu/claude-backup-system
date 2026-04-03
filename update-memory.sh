#!/bin/bash
set -euo pipefail

# update-memory.sh — Conversation Digest Generator (runs unattended via Task Scheduler)
#
# Usage:
#   ./update-memory.sh              # Default: last 1 day
#   ./update-memory.sh 7            # Last 7 days
#   ./update-memory.sh --all        # Full historical pass

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIGEST_DIR="$SCRIPT_DIR/_digests"
PYTHON="/c/Python314/python"
LOGFILE="$SCRIPT_DIR/_memory-sync.log"

exec >> "$LOGFILE" 2>&1
echo "=== Memory Digest Generator — $(date) ==="

if [ "$1" = "--all" ] 2>/dev/null; then
    echo "Running FULL historical extraction..."
    if ! $PYTHON "$SCRIPT_DIR/memory-sync.py" --all --output-dir "$DIGEST_DIR"; then
        echo "ERROR: Digest generation failed."
        exit 1
    fi
else
    DAYS=${1:-1}
    echo "Scanning last $DAYS day(s)..."
    if ! $PYTHON "$SCRIPT_DIR/memory-sync.py" --days "$DAYS" --output-dir "$DIGEST_DIR"; then
        echo "ERROR: Digest generation failed."
        exit 1
    fi
fi

echo "=== Done $(date) ==="
