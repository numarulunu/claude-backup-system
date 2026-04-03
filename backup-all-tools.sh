#!/bin/bash
set -uo pipefail

# backup-all-tools.sh — Auto-discover and backup all git repos to GitHub
# Scans common directories for any folder with a .git directory and a remote,
# then commits and pushes changes. No hardcoded paths — works on any machine.
#
# Usage: ./backup-all-tools.sh [scan_dir1] [scan_dir2] ...
#        Defaults to ~/Desktop and ~/Documents if no dirs specified.

LOGFILE="$(dirname "$0")/_tools-backup.log"
exec >> "$LOGFILE" 2>&1
echo ""
echo "=== Tools Backup — $(date) ==="

# Directories to scan for git repos (override with arguments)
if [ $# -gt 0 ]; then
    SCAN_DIRS=("$@")
else
    SCAN_DIRS=(
        "$HOME/Desktop"
        "$HOME/Documents"
        "$HOME/Projects"
    )
fi

PUSHED=0
SKIPPED=0
FAILED=0
FOUND=0

for SCAN_DIR in "${SCAN_DIRS[@]}"; do
    if [ ! -d "$SCAN_DIR" ]; then
        continue
    fi

    echo "  Scanning: $SCAN_DIR"

    # Find all directories containing .git (max 3 levels deep to avoid deep nesting)
    while IFS= read -r gitdir; do
        REPO_DIR="$(dirname "$gitdir")"
        REPO_NAME="$(basename "$REPO_DIR")"
        ((FOUND++))

        # Skip if no remote configured (local-only repos)
        REMOTE=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)
        if [ -z "$REMOTE" ]; then
            echo "    SKIP: $REPO_NAME — no remote configured"
            ((SKIPPED++))
            continue
        fi

        # Check for changes
        CHANGES=$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)
        if [ -z "$CHANGES" ]; then
            echo "    OK: $REPO_NAME — no changes"
            ((SKIPPED++))
            continue
        fi

        CHANGE_COUNT=$(echo "$CHANGES" | wc -l | tr -d ' ')
        echo "    PUSH: $REPO_NAME — $CHANGE_COUNT file(s) changed"

        # Stage, commit, push
        git -C "$REPO_DIR" add -A
        git -C "$REPO_DIR" commit -m "auto-backup $(date '+%Y-%m-%d %H:%M') — $CHANGE_COUNT file(s)" 2>&1 | tail -1

        if timeout 60 git -C "$REPO_DIR" push 2>&1 | tail -1; then
            ((PUSHED++))
        else
            echo "    ERROR: $REPO_NAME — push failed"
            ((FAILED++))
        fi

    done < <(find "$SCAN_DIR" -maxdepth 4 -name ".git" -type d 2>/dev/null | sort)
done

echo ""
echo "SUMMARY: $FOUND repos found. $PUSHED pushed, $SKIPPED unchanged, $FAILED failed."
echo "=== Done $(date) ==="
