#!/bin/bash

# Ensure core utils are on PATH BEFORE set -e (Windows Task Scheduler may invoke with empty PATH)
export PATH="/usr/bin:/bin:/c/Program Files/Git/usr/bin:/c/Program Files/Git/bin:/c/Program Files/Git/mingw64/bin:/mingw64/bin:${PATH:-}"

set -euo pipefail

# backup.sh — Daily backup for Claude Code config, conversations, and memory.
# Generates conversation digests, syncs config files, commits and pushes.
#
# Usage: ./backup.sh [commit message]
#
# Note: Tool repo syncing is handled separately by Git Sync.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$SCRIPT_DIR/_backup.log"
LOCKFILE="$SCRIPT_DIR/.backup.lock"

# Concurrency guard — abort if another run is in progress
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    echo "backup.sh: another run is in progress, exiting" >&2
    exit 0
fi

# Shared helpers
# shellcheck source=_detect-python.sh
source "$SCRIPT_DIR/_detect-python.sh"
# shellcheck source=_log-rotate.sh
source "$SCRIPT_DIR/_log-rotate.sh"

rotate_log "$LOGFILE"

STEPS_OK=0
STEPS_WARN=0
STEPS_FAIL=0

log_ok()   { echo "  OK: $1";   STEPS_OK=$((STEPS_OK + 1));   }
log_warn() { echo "  WARN: $1"; STEPS_WARN=$((STEPS_WARN + 1)); }
log_fail() { echo "  FAIL: $1"; STEPS_FAIL=$((STEPS_FAIL + 1)); }

# Atomic write to a file (truncate via tmp + rename).
atomic_write() {
    local path="$1"
    local content="$2"
    local tmp="${path}.tmp.$$"
    printf '%s' "$content" > "$tmp"
    mv -f "$tmp" "$path"
}

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

echo "  Backup repo: ${BACKUP_REPO/#$HOME/~}"

CONFIG_DIR="$BACKUP_REPO/_claude-config"
CONV_DIR="$BACKUP_REPO/_conversations"
mkdir -p "$CONFIG_DIR/memory" "$CONV_DIR"

# Step 1: Generate digest
echo "  Running digest generation..."
if bash "$SCRIPT_DIR/update-memory.sh"; then
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

# Sync memory files (all projects that have a memory/ dir).
# Single find call instead of per-project cp subprocess.
MEMORY_COUNT=$(find "$PROJECTS_DIR" -mindepth 3 -maxdepth 3 -type f -name '*.md' -path '*/memory/*' \
    -exec cp {} "$CONFIG_DIR/memory/" \; -print 2>/dev/null | wc -l)
if [ "$MEMORY_COUNT" -gt 0 ]; then
    log_ok "Memory synced ($MEMORY_COUNT file(s))"
else
    log_warn "No memory files found"
fi

# Sync Kontext database (SQLite online backup API — WAL-safe)
KONTEXT_DB="${KONTEXT_DB:-$HOME/Desktop/Claude/Kontext/kontext.db}"
if [ -f "$KONTEXT_DB" ]; then
    if command -v sqlite3 &>/dev/null; then
        if sqlite3 "$KONTEXT_DB" ".backup '$CONFIG_DIR/kontext.db.tmp'" 2>/dev/null \
            && mv -f "$CONFIG_DIR/kontext.db.tmp" "$CONFIG_DIR/kontext.db"; then
            log_ok "kontext.db backed up (online backup API)"
        else
            rm -f "$CONFIG_DIR/kontext.db.tmp"
            log_warn "sqlite3 .backup failed for kontext.db"
        fi
    else
        # Fallback: plain cp. WAL may be inconsistent but better than nothing.
        cp "$KONTEXT_DB" "$CONFIG_DIR/kontext.db"
        log_warn "kontext.db copied via cp (sqlite3 CLI not found — WAL may be inconsistent)"
    fi
else
    log_warn "kontext.db not found at ${KONTEXT_DB/#$HOME/~}"
fi

# Sync conversations (incremental — only new/modified files)
if $PYTHON "$SCRIPT_DIR/sync-conversations.py" "$PROJECTS_DIR" "$CONV_DIR"; then
    log_ok "Conversations synced"
else
    log_warn "Conversation sync had errors (see log)"
fi

# Step 3: Commit and push
cd "$BACKUP_REPO"
# Sanitize commit message: strip shell metacharacters.
RAW_MSG="${1:-backup $(date '+%Y-%m-%d %H:%M')}"
MSG="${RAW_MSG//[\`\$\\]/}"

# Explicit allow-list add — prevents blast-radius from future new file types.
git add -- _claude-config _conversations 2>/dev/null || true

CHANGES=$(git diff --cached --stat 2>/dev/null)
if [ -z "$CHANGES" ]; then
    log_ok "No changes to commit"
else
    COMMIT_OUT=$(git commit -m "$MSG" 2>&1) || COMMIT_RC=$?
    COMMIT_RC=${COMMIT_RC:-0}
    echo "$COMMIT_OUT" | tail -1
    if [ "$COMMIT_RC" -ne 0 ]; then
        log_fail "git commit failed (rc=$COMMIT_RC)"
    else
        PUSH_OUT=$(timeout 60 git push 2>&1) || PUSH_RC=$?
        PUSH_RC=${PUSH_RC:-0}
        echo "$PUSH_OUT" | tail -1
        if [ "$PUSH_RC" -eq 0 ]; then
            log_ok "Pushed to remote"
        else
            log_fail "Push failed (rc=$PUSH_RC)"
        fi
    fi
fi

# Summary
echo ""
echo "SUMMARY: $STEPS_OK ok, $STEPS_WARN warnings, $STEPS_FAIL failures."

# Warnings over threshold → soft-fail (exit 2).
# Hard failures → exit 1.
WARN_THRESHOLD=2
FAIL_FLAG="$SCRIPT_DIR/_backup-failed"

if [ "$STEPS_FAIL" -gt 0 ]; then
    atomic_write "$FAIL_FLAG" "$(date '+%Y-%m-%d %H:%M') — $STEPS_FAIL failure(s)"
    echo "=== Done with FAILURES $(date) ==="
    exit 1
elif [ "$STEPS_WARN" -gt "$WARN_THRESHOLD" ]; then
    atomic_write "$FAIL_FLAG" "$(date '+%Y-%m-%d %H:%M') — $STEPS_WARN warning(s) exceeded threshold"
    echo "=== Done with WARNINGS $(date) ==="
    exit 2
else
    rm -f "$FAIL_FLAG"
    echo "=== Done $(date) ==="
fi
