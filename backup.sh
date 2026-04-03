#!/bin/bash
set -euo pipefail

# backup.sh — Sync latest files from .claude/ and push to GitHub
# Runs update-memory.sh first to ensure digest is fresh, then backs up everything.
#
# Usage: ./backup.sh [commit message]

CLAUDE_DIR="$HOME/Desktop/Claude"
CONFIG_DIR="$CLAUDE_DIR/_claude-config"
CONV_DIR="$CLAUDE_DIR/_conversations"
MEMORY_SRC="$HOME/.claude/projects/C--Users-Gaming-PC-Desktop-Claude-Personal-Context/memory"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$CLAUDE_DIR/_backup.log"

exec >> "$LOGFILE" 2>&1
echo "=== Backup — $(date) ==="

# Step 0: Run digest generation first (ensures no race condition)
echo "  Running digest generation..."
bash "$SCRIPT_DIR/update-memory.sh" 2>&1 || echo "  WARN: Digest generation had issues, continuing backup..."

# Step 1: Sync files
echo "  Syncing CLAUDE.md..."
cp "$HOME/.claude/CLAUDE.md" "$CONFIG_DIR/CLAUDE.md" || echo "  WARN: CLAUDE.md sync failed"

echo "  Syncing memory files..."
cp "$MEMORY_SRC/"*.md "$CONFIG_DIR/memory/" 2>/dev/null || echo "  WARN: Memory sync failed"

echo "  Syncing conversations..."
cp -ru "$HOME/.claude/projects/" "$CONV_DIR/" 2>/dev/null || echo "  WARN: Conversation sync failed"

# Step 2: Git commit and push
cd "$CLAUDE_DIR"
MSG="${1:-backup $(date '+%Y-%m-%d %H:%M')}"
git add -A
CHANGES=$(git diff --cached --stat)
if [ -z "$CHANGES" ]; then
    echo "  No changes to commit."
    echo "=== Done $(date) ==="
    exit 0
fi
git commit -m "$MSG"
timeout 60 git push || echo "  ERROR: git push failed or timed out"

# Step 3: Backup all individual tool repos
echo "  Backing up all tool repos..."
bash "$SCRIPT_DIR/backup-all-tools.sh" 2>&1 || echo "  WARN: Tool backup had issues"

echo "=== Done $(date) ==="
