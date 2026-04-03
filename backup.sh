#!/bin/bash
set -euo pipefail

# backup.sh — Portable daily backup for Claude Code users
# Auto-detects Claude config, generates digest, syncs to git, backs up all tool repos.
# Works on any machine with Claude Code CLI, git, and Python installed.
#
# Usage: ./backup.sh [commit message]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$SCRIPT_DIR/_backup.log"

exec >> "$LOGFILE" 2>&1
echo "=== Backup — $(date) ==="

# --- Auto-detect paths ---
CLAUDE_DIR="$HOME/.claude"
PROJECTS_DIR="$CLAUDE_DIR/projects"

if [ ! -d "$CLAUDE_DIR" ]; then
    echo "ERROR: Claude Code config not found at $CLAUDE_DIR"
    echo "Make sure Claude Code CLI is installed."
    exit 1
fi

# Find the backup repo (look for _claude-config directory or .git in parent)
BACKUP_REPO=""
# Check if there's a _claude-config dir in common locations
for candidate in "$HOME/Desktop/Claude" "$HOME/Documents/Claude" "$HOME/Projects/Claude" "$(dirname "$SCRIPT_DIR")"; do
    if [ -d "$candidate/_claude-config" ] && [ -d "$candidate/.git" ]; then
        BACKUP_REPO="$candidate"
        break
    fi
done

if [ -z "$BACKUP_REPO" ]; then
    echo "WARN: No backup repo found (looking for _claude-config/ in a git repo)."
    echo "Skipping main repo backup. Tool repos will still be backed up."
else
    echo "  Backup repo: $BACKUP_REPO"

    CONFIG_DIR="$BACKUP_REPO/_claude-config"
    CONV_DIR="$BACKUP_REPO/_conversations"
    mkdir -p "$CONFIG_DIR/memory" "$CONV_DIR"

    # Step 0: Generate digest
    echo "  Running digest generation..."
    bash "$SCRIPT_DIR/update-memory.sh" 2>&1 || echo "  WARN: Digest generation had issues"

    # Step 1: Sync Claude config
    echo "  Syncing CLAUDE.md..."
    cp "$CLAUDE_DIR/CLAUDE.md" "$CONFIG_DIR/CLAUDE.md" 2>/dev/null || echo "  WARN: CLAUDE.md not found"

    echo "  Syncing settings..."
    cp "$CLAUDE_DIR/settings.json" "$CONFIG_DIR/settings.json" 2>/dev/null || true

    # Sync memory files (find the project with a memory/ dir)
    echo "  Syncing memory files..."
    for memdir in "$PROJECTS_DIR"/*/memory/; do
        if [ -d "$memdir" ]; then
            cp "$memdir"*.md "$CONFIG_DIR/memory/" 2>/dev/null || true
            echo "    Found memory at: $memdir"
            break
        fi
    done

    # Sync conversations
    echo "  Syncing conversations..."
    cp -ru "$PROJECTS_DIR/" "$CONV_DIR/" 2>/dev/null || echo "  WARN: Conversation sync failed"

    # Step 2: Commit and push
    cd "$BACKUP_REPO"
    MSG="${1:-backup $(date '+%Y-%m-%d %H:%M')}"
    git add -A
    CHANGES=$(git diff --cached --stat 2>/dev/null)
    if [ -z "$CHANGES" ]; then
        echo "  No changes to commit."
    else
        git commit -m "$MSG" 2>&1 | tail -1
        timeout 60 git push 2>&1 | tail -1 || echo "  ERROR: push failed"
    fi
fi

# Step 3: Backup all tool repos (auto-discovers git repos)
echo "  Backing up all tool repos..."
bash "$SCRIPT_DIR/backup-all-tools.sh" 2>&1 || echo "  WARN: Tool backup had issues"

echo "=== Done $(date) ==="
