"""
Memory Sync — Conversation Digest Generator
Scans all Claude Code project conversations, extracts FULL user and assistant messages,
outputs per-project digest files for comprehensive memory analysis.

Usage:
    python memory-sync.py [--days 7] [--output-dir digests/] [--all]

Modes:
    --days N        Extract conversations from last N days (default: 7, for daily runs)
    --all           Extract ALL conversations ever (full historical pass)
    --output-dir    Directory for per-project digest files (default: _digests/)
"""

import json
import os
import re
import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects"

# Pre-compiled regexes for performance
RE_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
RE_TASK_NOTIFICATION = re.compile(r"<task-notification>.*?</task-notification>", re.DOTALL)


def folder_to_project_name(folder_name: str) -> str:
    """Convert Claude's folder naming convention back to readable names."""
    name = folder_name.replace("C--Users-Gaming-PC-Desktop-Claude-", "")
    name = name.replace("C--Users-Gaming-PC-Desktop-", "")
    name = name.replace("C--Users-Gaming-PC-Downloads-", "Downloads/")
    name = name.replace("C--Users-Gaming-PC", "Home")
    name = name.replace("C--Users-GAMING-1-AppData-Local-Temp", "Temp")
    name = name.replace("D--OneDrive---Universitatea--OVIDIUS--", "Uni/")
    name = name.replace("--", "/").replace("-", " ")
    return name if name else folder_name


def folder_to_safe_filename(folder_name: str) -> str:
    """Convert project folder name to a safe filename for the digest."""
    name = folder_to_project_name(folder_name)
    safe = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '-').lower()
    return safe or 'unknown'


def parse_jsonl_file(filepath: Path, cutoff: datetime | None = None) -> list[dict]:
    """Parse a JSONL conversation file and extract ALL messages (optionally after cutoff)."""
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Get timestamp
                timestamp_str = entry.get("timestamp")
                if not timestamp_str:
                    msg = entry.get("message", {})
                    if isinstance(msg, dict):
                        timestamp_str = msg.get("timestamp")
                if not timestamp_str:
                    continue

                try:
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                if cutoff and ts < cutoff:
                    continue

                entry_type = entry.get("type")
                role = None
                content_text = ""

                if entry_type == "user":
                    role = "user"
                    msg = entry.get("message", {})
                    if isinstance(msg, dict):
                        raw_content = msg.get("content", "")
                        if isinstance(raw_content, str):
                            content_text = raw_content
                        elif isinstance(raw_content, list):
                            parts = []
                            for block in raw_content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    parts.append(block.get("text", ""))
                            content_text = "\n".join(parts)

                elif entry_type == "assistant":
                    role = "assistant"
                    msg = entry.get("message", {})
                    if isinstance(msg, dict):
                        raw_content = msg.get("content", [])
                        if isinstance(raw_content, str):
                            content_text = raw_content
                        elif isinstance(raw_content, list):
                            parts = []
                            for block in raw_content:
                                if isinstance(block, dict):
                                    if block.get("type") == "text":
                                        parts.append(block.get("text", ""))
                                    elif block.get("type") == "tool_use":
                                        tool_name = block.get("name", "unknown")
                                        parts.append(f"[Tool: {tool_name}]")
                            content_text = "\n".join(parts)

                if not role or not content_text.strip():
                    continue

                # Strip system reminders and task notifications (noise, not content)
                content_text = RE_SYSTEM_REMINDER.sub("", content_text)
                content_text = RE_TASK_NOTIFICATION.sub("[task notification]", content_text)
                content_text = content_text.strip()
                if not content_text or content_text == "[task notification]":
                    continue

                messages.append({
                    "role": role,
                    "text": content_text,
                    "timestamp": ts,
                })

    except (OSError, PermissionError) as e:
        print(f"  Warning: Could not read {filepath}: {e}", file=sys.stderr)

    return messages


def get_conversation_timestamp(messages: list[dict]) -> datetime | None:
    """Get the most recent timestamp from a conversation."""
    if not messages:
        return None
    return max(m["timestamp"] for m in messages)


def build_project_digest(project_name: str, conversations: list[dict]) -> str:
    """Build a full digest for a single project — no truncation."""
    lines = []
    lines.append(f"# {project_name} — Full Conversation Digest")
    lines.append(f"**Conversations:** {len(conversations)}")

    earliest = min(c["earliest"] for c in conversations)
    latest = max(c["latest"] for c in conversations)
    lines.append(f"**Date range:** {earliest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')}")
    lines.append("")

    # Sort conversations chronologically (oldest first for narrative flow)
    conversations.sort(key=lambda c: c["earliest"])

    for i, conv in enumerate(conversations, 1):
        start = conv["earliest"].strftime("%Y-%m-%d %H:%M UTC")
        end = conv["latest"].strftime("%Y-%m-%d %H:%M UTC")
        msg_count = len(conv["messages"])

        lines.append(f"---")
        lines.append(f"## Session {i} — {start}")
        lines.append(f"*{msg_count} messages, ended {end}*\n")

        for msg in conv["messages"]:
            ts = msg["timestamp"].strftime("%H:%M")
            role_label = "**USER**" if msg["role"] == "user" else "**CLAUDE**"
            lines.append(f"### [{ts}] {role_label}\n")
            lines.append(msg["text"])
            lines.append("")

    return "\n".join(lines)


def run(days: int | None, output_dir: str, extract_all: bool):
    """Main extraction logic."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cutoff = None
    if not extract_all:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days or 7)
        label = f"last {days} days"
    else:
        label = "ALL TIME"

    print(f"Scanning conversations ({label})...", file=sys.stderr)

    if not CLAUDE_PROJECTS_DIR.exists():
        print(f"ERROR: Claude projects directory not found at {CLAUDE_PROJECTS_DIR}", file=sys.stderr)
        sys.exit(1)

    project_stats = []

    for project_dir in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
        if not project_dir.is_dir():
            continue

        project_name = folder_to_project_name(project_dir.name)
        safe_name = folder_to_safe_filename(project_dir.name)
        jsonl_files = list(project_dir.glob("*.jsonl"))

        # Also check subdirectories for conversation files (subagents, etc.)
        # but skip them — subagent conversations are internal, not user-facing

        conversations = []

        for jf in jsonl_files:
            # If filtering by days, skip old files
            if cutoff:
                try:
                    mtime = datetime.fromtimestamp(jf.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        continue
                except OSError:
                    continue

            messages = parse_jsonl_file(jf, cutoff)
            if not messages:
                continue

            messages.sort(key=lambda m: m["timestamp"])
            conversations.append({
                "file": jf.name,
                "messages": messages,
                "earliest": min(m["timestamp"] for m in messages),
                "latest": max(m["timestamp"] for m in messages),
            })

        if not conversations:
            continue

        # Build full digest for this project
        digest = build_project_digest(project_name, conversations)

        digest_file = output_path / f"{safe_name}.md"
        digest_file.write_text(digest, encoding="utf-8")

        total_messages = sum(len(c["messages"]) for c in conversations)
        file_size_kb = len(digest.encode("utf-8")) / 1024

        project_stats.append({
            "name": project_name,
            "file": str(digest_file),
            "conversations": len(conversations),
            "messages": total_messages,
            "size_kb": file_size_kb,
        })

        print(f"  {project_name}: {len(conversations)} conversations, {total_messages} messages, {file_size_kb:.0f}KB", file=sys.stderr)

    # Write manifest
    manifest_lines = []
    manifest_lines.append(f"# Digest Manifest")
    manifest_lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    manifest_lines.append(f"**Scope:** {label}")
    manifest_lines.append(f"**Projects:** {len(project_stats)}")
    total_msgs = sum(p["messages"] for p in project_stats)
    total_size = sum(p["size_kb"] for p in project_stats)
    manifest_lines.append(f"**Total messages:** {total_msgs}")
    manifest_lines.append(f"**Total size:** {total_size:.0f}KB")
    manifest_lines.append("")
    manifest_lines.append("| Project | File | Conversations | Messages | Size |")
    manifest_lines.append("|---|---|---|---|---|")

    for p in sorted(project_stats, key=lambda x: x["size_kb"], reverse=True):
        manifest_lines.append(f"| {p['name']} | `{Path(p['file']).name}` | {p['conversations']} | {p['messages']} | {p['size_kb']:.0f}KB |")

    manifest_path = output_path / "_manifest.md"
    manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")

    # Write pending flag
    pending_path = output_path.parent / "_digest-pending"
    pending_path.write_text(datetime.now().strftime('%Y-%m-%d %H:%M'), encoding="utf-8")

    print(f"\n  TOTAL: {len(project_stats)} projects, {total_msgs} messages, {total_size:.0f}KB", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    print(f"  Pending flag written.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Generate conversation digests for memory sync")
    parser.add_argument("--days", type=int, default=1, help="Look back N days (default: 1, for daily runs)")
    parser.add_argument("--all", action="store_true", help="Extract ALL conversations (full historical pass)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for digest files")
    args = parser.parse_args()

    default_dir = Path(__file__).parent / "_digests"
    output_dir = args.output_dir or str(default_dir)

    run(days=args.days, output_dir=output_dir, extract_all=args.all)


if __name__ == "__main__":
    main()
