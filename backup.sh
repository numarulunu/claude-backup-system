#!/bin/bash
set -euo pipefail

# backup.sh — Daily backup for Claude Code config, conversations, and memory.
# Generates conversation digests, syncs config files, commits and pushes.
#
# Usage: ./backup.sh [commit message]
#
# Note: Tool repo syncing is handled separately by Git Sync.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$SCRIPT_DIR/_backup.log"

STEPS_OK=0
STEPS_WARN=0
STEPS_FAIL=0

log_ok()   { echo "  OK: $1"; ((STEPS_OK++)); }
log_warn() { echo "  WARN: $1"; ((STEPS_WARN++)); }
log_fail() { echo "  FAIL: $1"; ((STEPS_FAIL++)); }

exec >> "$LOGFILE" 2>&1
echo "=== Backup — $(date) ==="

# --- Auto-detect paths ---
CLAUDE_DIR="$HOME/.claude"
PROJECTS_DIR="$CLAUDE_DIR/projects"

if [ ! -d "$CLAUDE_DIR" ]; then
    log_fail "Claude Code config not found at $CLAUDE_DIR"
    exit 1
fi

# Find the backup repo
BACKUP_REPO=""
for candidate in "$HOME/Desktop/Claude" "$HOME/Documents/Claude" "$HOME/Projects/Claude" "$(dirname "$SCRIPT_DIR")"; do
    if [ -d "$candidate/_claude-config" ] && [ -d "$candidate/.git" ]; then
        BACKUP_REPO="$candidate"
        break
    fi
done

if [ -z "$BACKUP_REPO" ]; then
    log_fail "No backup repo found (looking for _claude-config/ in a git repo)."
    exit 1
fi

echo "  Backup repo: $BACKUP_REPO"

CONFIG_DIR="$BACKUP_REPO/_claude-config"
CONV_DIR="$BACKUP_REPO/_conversations"
mkdir -p "$CONFIG_DIR/memory" "$CONV_DIR"

# Step 1: Generate digest
echo "  Running digest generation..."
if bash "$SCRIPT_DIR/update-memory.sh" 2>&1; then
    log_ok "Digest generation"
else
    log_warn "Digest generation had issues"
fi

# Step 2: Sync Claude config
if cp "$CLAUDE_DIR/CLAUDE.md" "$CONFIG_DIR/CLAUDE.md" 2>/dev/null; then
    log_ok "CLAUDE.md synced"
else
    log_warn "CLAUDE.md not found"
fi

cp "$CLAUDE_DIR/settings.json" "$CONFIG_DIR/settings.json" 2>/dev/null || true

# Sync memory files (all projects that have a memory/ dir)
MEMORY_FOUND=0
for memdir in "$PROJECTS_DIR"/*/memory/; do
    if [ -d "$memdir" ]; then
        cp "$memdir"*.md "$CONFIG_DIR/memory/" 2>/dev/null || true
        ((MEMORY_FOUND++))
    fi
done
if [ "$MEMORY_FOUND" -gt 0 ]; then
    log_ok "Memory synced from $MEMORY_FOUND project(s)"
else
    log_warn "No memory directories found"
fi

# Sync conversations
if cp -ru "$PROJECTS_DIR/" "$CONV_DIR/" 2>/dev/null; then
    log_ok "Conversations synced"
else
    log_warn "Conversation sync failed"
fi

# Step 3: Commit and push
cd "$BACKUP_REPO"
MSG="${1:-backup $(date '+%Y-%m-%d %H:%M')}"
git add -A
CHANGES=$(git diff --cached --stat 2>/dev/null)
if [ -z "$CHANGES" ]; then
    log_ok "No changes to commit"
else
    git commit -m "$MSG" 2>&1 | tail -1
    if timeout 60 git push 2>&1 | tail -1; then
        log_ok "Pushed to remote"
    else
        log_fail "Push failed"
    fi
fi

# Summary
echo ""
echo "SUMMARY: $STEPS_OK ok, $STEPS_WARN warnings, $STEPS_FAIL failures."

if [ "$STEPS_FAIL" -gt 0 ]; then
    # Write failure flag for SessionStart hook to detect
    echo "$(date '+%Y-%m-%d %H:%M') — $STEPS_FAIL failure(s)" > "$SCRIPT_DIR/_backup-failed"
    echo "=== Done with FAILURES $(date) ==="
    exit 1
else
    rm -f "$SCRIPT_DIR/_backup-failed"
    echo "=== Done $(date) ==="
fi
