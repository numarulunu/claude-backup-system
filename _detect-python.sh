#!/bin/bash
# _detect-python.sh — Source this to set and export PYTHON.
# Shared by backup.sh and update-memory.sh.

PYTHON=""
for cmd in python3 python /c/Python314/python /c/Python313/python /c/Python312/python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python not found. Install Python 3.10+ and add to PATH." >&2
    exit 1
fi

export PYTHON
