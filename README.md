# Claude Backup System

Daily backup for Claude Code CLI users. Generates conversation digests, syncs memory files and config, commits and pushes to GitHub.

## What it does

1. **Extracts conversations** from Claude Code's project logs into readable markdown digests
2. **Caps digest size** at 5MB per project (configurable) -- drops oldest sessions first
3. **Syncs your Claude config** (CLAUDE.md, memory files, settings) to a backup repo
4. **Commits and pushes** the backup repo

Tool repo syncing is handled separately by [Git Sync](../Git%20Sync/).

## Requirements

- Python 3.10+
- Git
- Claude Code CLI (installed and used at least once)

## Usage

```bash
# Full backup (digest + sync + push)
./backup.sh

# Just the digest
./update-memory.sh              # last 1 day
./update-memory.sh 7            # last 7 days
./update-memory.sh --all        # everything ever

# Python script directly (more options)
python memory-sync.py --days 7 --max-size 10    # 10MB cap per digest
```

## Tests

```bash
python -m pytest tests/ -v
```

## Scheduling

### Windows
```powershell
$action = New-ScheduledTaskAction -Execute 'C:\Program Files\Git\usr\bin\bash.exe' -Argument '"C:\path\to\backup.sh"'
$trigger = New-ScheduledTaskTrigger -Daily -At '9:00PM'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName 'Claude Daily Backup' -Action $action -Trigger $trigger -Settings $settings
```

### Linux/macOS
```bash
0 21 * * * /path/to/backup.sh >> /path/to/backup.log 2>&1
```

## Files

| File | What it does |
|---|---|
| `backup.sh` | Main entry point -- digest, sync config, commit, push |
| `update-memory.sh` | Generates conversation digests only |
| `memory-sync.py` | Python script that parses JSONL conversation logs |
| `tests/` | pytest tests for the digest logic |
