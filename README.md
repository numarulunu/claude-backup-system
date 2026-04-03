# Claude Backup System

Automated daily backup for Claude Code CLI users. Generates conversation digests, syncs memory files, and pushes all your git repos to GitHub — unattended.

## What it does

1. **Extracts conversations** from Claude Code's project logs into readable markdown digests (no AI needed)
2. **Syncs your Claude config** (CLAUDE.md, memory files, settings) to a backup repo
3. **Auto-discovers and pushes** every git repo on your machine that has a remote

## Requirements

- Python 3.10+
- Git + GitHub CLI (`gh`) authenticated
- Claude Code CLI (installed and used at least once)
- Windows (Task Scheduler) or cron (Linux/macOS) for automation

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/claude-backup-system.git
cd claude-backup-system

# Run manually
./backup.sh

# Or just the digest
./update-memory.sh          # last 1 day
./update-memory.sh 7        # last 7 days
./update-memory.sh --all    # everything ever

# Or just the repo sync
./backup-all-tools.sh
./backup-all-tools.sh ~/Projects ~/Code   # custom scan dirs
```

## Scheduling (Windows)

```powershell
$action = New-ScheduledTaskAction -Execute 'C:\Program Files\Git\usr\bin\bash.exe' -Argument '"PATH\TO\backup.sh"'
$trigger = New-ScheduledTaskTrigger -Daily -At '9:00PM'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName 'Claude Daily Backup' -Action $action -Trigger $trigger -Settings $settings
```

## Scheduling (Linux/macOS)

```bash
# Add to crontab
crontab -e
0 21 * * * /path/to/backup.sh >> /path/to/backup.log 2>&1
```

## How the digest works

Claude Code stores every conversation as JSONL files in `~/.claude/projects/`. The digest script:
1. Opens each JSONL file
2. Extracts user and assistant messages (full text, no truncation)
3. Strips system noise (reminders, task notifications)
4. Groups by project, outputs one markdown file per project
5. Writes a `_digest-pending` flag for Claude to detect on next session

No AI is involved. It's a structured copy-paste of raw conversation data.

## Files

| File | What it does |
|---|---|
| `backup.sh` | Main entry point — runs digest, syncs config, pushes all repos |
| `update-memory.sh` | Generates conversation digests only |
| `backup-all-tools.sh` | Auto-discovers and pushes all git repos |
| `memory-sync.py` | Python script that parses JSONL conversation logs |
| `config.json` | Optional config overrides (scan dirs, exclusions) |
