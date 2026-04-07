#!/bin/bash
# _log-rotate.sh — Rotate a log file if it exceeds 5MB.
# Usage: rotate_log /path/to/file.log

rotate_log() {
    local f="$1"
    local max=5242880
    if [ -f "$f" ]; then
        local sz
        sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
        if [ "$sz" -gt "$max" ]; then
            mv "$f" "${f}.1"
        fi
    fi
}
