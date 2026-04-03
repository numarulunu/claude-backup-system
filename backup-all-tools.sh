#!/bin/bash
set -uo pipefail

# backup-all-tools.sh — Auto-backup all tool repos to GitHub
# Cycles through every registered tool, commits changes, pushes.
# Runs daily via Task Scheduler alongside the main backup.
#
# Usage: ./backup-all-tools.sh

LOGFILE="$HOME/Desktop/Claude/_tools-backup.log"
exec >> "$LOGFILE" 2>&1
echo ""
echo "=== Tools Backup — $(date) ==="

# All tool repos: [directory]|[repo name]
REPOS=(
  "$HOME/Desktop/Claude/Finance|vocality-accounting"
  "$HOME/Desktop/Claude/Systems/automations/11-preply-lead-messenger|preply-lead-messenger"
  "$HOME/Desktop/Claude/Systems/automations/02-lead-gen-chatbot|vocality-chat-widget"
  "$HOME/Desktop/Claude/Claude Codex|claude-codex"
  "$HOME/Desktop/Claude/Skool|vocality-skool"
  "$HOME/Desktop/Transcriptor v2|transcriptor-v2"
  "$HOME/Desktop/Claude/UsageBOT|claude-code-usage-dashboard"
)

PUSHED=0
SKIPPED=0
FAILED=0

for entry in "${REPOS[@]}"; do
  DIR="${entry%%|*}"
  NAME="${entry##*|}"

  if [ ! -d "$DIR/.git" ]; then
    echo "  SKIP: $NAME — no .git directory at $DIR"
    ((SKIPPED++))
    continue
  fi

  cd "$DIR"

  # Check for changes (staged, unstaged, or untracked)
  CHANGES=$(git status --porcelain 2>/dev/null)

  if [ -z "$CHANGES" ]; then
    echo "  OK: $NAME — no changes"
    ((SKIPPED++))
    continue
  fi

  # Count what changed
  CHANGE_COUNT=$(echo "$CHANGES" | wc -l | tr -d ' ')
  echo "  PUSH: $NAME — $CHANGE_COUNT file(s) changed"

  # Stage, commit, push
  git add -A
  git commit -m "auto-backup $(date '+%Y-%m-%d %H:%M') — $CHANGE_COUNT file(s)" 2>&1 | tail -1

  if timeout 60 git push 2>&1 | tail -1; then
    ((PUSHED++))
  else
    echo "  ERROR: $NAME — push failed"
    ((FAILED++))
  fi
done

echo ""
echo "SUMMARY: $PUSHED pushed, $SKIPPED unchanged, $FAILED failed"
echo "=== Done $(date) ==="
