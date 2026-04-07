"""
Memory Sync — Conversation Digest Generator (Portable)
Scans all Claude Code project conversations, extracts full messages,
outputs per-project digest files for memory analysis.

Auto-detects Claude projects directory on any machine.

Usage:
    python memory-sync.py [--days 1] [--output-dir digests/] [--all]
"""

import json
import os
import re
import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Pre-compiled regexes for performance
RE_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
RE_TASK_NOTIFICATION = re.compile(r"<task-notification>.*?</task-notification>", re.DOTALL)

# Secret scrubbing patterns — applied to every message before it lands in a digest.
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "sk-[REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9+/=_\-\.]{20,}"), "Bearer [REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_[REDACTED]"),
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "gho_[REDACTED]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{20,}"), "xox-[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
]


def scrub_secrets(text: str) -> str:
    """Redact common secret patterns before writing to digest."""
    for pat, repl in SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def atomic_write_text(path: Path, content: str) -> None:
    """Write text to path atomically via tmp + rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def find_claude_projects_dir() -> Path:
    """Auto-detect Claude Code projects directory on any OS."""
    home = Path.home()

    # Standard location: ~/.claude/projects/
    standard = home / ".claude" / "projects"
    if standard.exists():
        return standard

    # Windows AppData fallback
    appdata = Path(os.environ.get("APPDATA", "")) / "claude" / "projects"
    if appdata.exists():
        return appdata

    # XDG fallback (Linux)
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "claude" / "projects"
    if xdg.exists():
        return xdg

    print("ERROR: Could not find Claude Code projects directory.", file=sys.stderr)
    print("Expected at: ~/.claude/projects/", file=sys.stderr)
    print("Make sure Claude Code CLI is installed and has been used at least once.", file=sys.stderr)
    sys.exit(1)


def folder_to_project_name(folder_name: str) -> str:
    """Convert Claude's folder naming convention back to readable names.
    Works on any machine — handles multi-word usernames (e.g. 'Gaming PC')."""
    name = folder_name

    # Claude encodes paths like: C--Users-Gaming-PC-Desktop-Claude-Finance
    # The username can be multi-word (Gaming-PC, GAMING-1, John-Doe).
    # Strategy: strip up to the first known path segment after Users.
    known_segments = r"(?:Desktop|Documents|Projects|AppData|Downloads|OneDrive)"

    patterns = [
        # Windows: C--Users-<anything>-<known segment>-rest
        rf"^[A-Z]--Users-.+?-{known_segments}-",
        # Windows: C--Users-<anything> (root of user dir, no known segment)
        r"^[A-Z]--Users-.+?$",
        # Linux: home-username-rest
        rf"^home-.+?-{known_segments}-",
        r"^home-[^-]+-",
        # macOS: Users-username-rest
        rf"^Users-.+?-{known_segments}-",
        r"^Users-[^-]+-",
    ]

    for pattern in patterns:
        cleaned = re.sub(pattern, "", name)
        if cleaned != name:
            name = cleaned
            break

    # Handle drive letter prefixes that remain
    name = re.sub(r"^[A-Z]--", "", name)

    # Convert separators
    name = name.replace("--", "/").replace("-", " ")

    return name.strip() if name.strip() else folder_name


def folder_to_safe_filename(folder_name: str) -> str:
    """Convert project folder name to a safe filename."""
    name = folder_to_project_name(folder_name)
    safe = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '-').lower()
    return safe or 'unknown'


def extract_content_text(raw_content, include_tools: bool = False) -> str:
    """Extract text from a message content field (string or block list)."""
    if isinstance(raw_content, str):
        return raw_content
    if not isinstance(raw_content, list):
        return ""
    parts = []
    for block in raw_content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif include_tools and block.get("type") == "tool_use":
                parts.append(f"[Tool: {block.get('name', 'unknown')}]")
    return "\n".join(parts)


def parse_jsonl_file(filepath: Path, cutoff: datetime | None = None) -> list[dict]:
    """Parse a JSONL conversation file and extract ALL messages.

    Returns a list of message dicts. Each dict has keys:
        role, text, timestamp, input_tokens, output_tokens
    Token fields are 0 when not present in the source data.
    """
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="backslashreplace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

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
                if entry_type not in ("user", "assistant"):
                    continue

                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue

                raw_content = msg.get("content", "" if entry_type == "user" else [])
                content_text = extract_content_text(raw_content, include_tools=(entry_type == "assistant"))

                if not content_text.strip():
                    continue

                content_text = RE_SYSTEM_REMINDER.sub("", content_text)
                content_text = RE_TASK_NOTIFICATION.sub("[task notification]", content_text)
                content_text = scrub_secrets(content_text)
                content_text = content_text.strip()
                if not content_text or content_text == "[task notification]":
                    continue

                # Extract token counts from usage field on assistant messages
                input_tokens = 0
                output_tokens = 0
                usage = msg.get("usage") or entry.get("usage")
                if isinstance(usage, dict):
                    input_tokens = usage.get("input_tokens", 0) or 0
                    output_tokens = usage.get("output_tokens", 0) or 0

                messages.append({
                    "role": entry_type,
                    "text": content_text,
                    "timestamp": ts,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                })

    except (OSError, PermissionError) as e:
        print(f"  Warning: Could not read {filepath}: {e}", file=sys.stderr)

    return messages


def _format_token_count(tokens: int) -> str:
    """Format a token count as a human-readable string (e.g. '12.3k')."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


def build_project_digest(project_name: str, conversations: list[dict]) -> str:
    """Build a full digest for a single project — no truncation."""
    lines = []
    lines.append(f"# {project_name} — Full Conversation Digest")
    lines.append(f"**Conversations:** {len(conversations)}")

    earliest = min(c["earliest"] for c in conversations)
    latest = max(c["latest"] for c in conversations)
    lines.append(f"**Date range:** {earliest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')}")

    # Project-level token totals
    total_input = sum(m.get("input_tokens", 0) for c in conversations for m in c["messages"])
    total_output = sum(m.get("output_tokens", 0) for c in conversations for m in c["messages"])
    total_tokens = total_input + total_output
    if total_tokens > 0:
        lines.append(f"**Tokens:** {_format_token_count(total_tokens)} total ({_format_token_count(total_input)} in, {_format_token_count(total_output)} out)")

    lines.append("")

    conversations.sort(key=lambda c: c["earliest"])

    for i, conv in enumerate(conversations, 1):
        start = conv["earliest"].strftime("%Y-%m-%d %H:%M UTC")
        end = conv["latest"].strftime("%Y-%m-%d %H:%M UTC")
        msg_count = len(conv["messages"])

        # Per-session token counts
        session_input = sum(m.get("input_tokens", 0) for m in conv["messages"])
        session_output = sum(m.get("output_tokens", 0) for m in conv["messages"])
        session_total = session_input + session_output

        lines.append(f"---")
        lines.append(f"## Session {i} — {start}")
        if session_total > 0:
            lines.append(f"*{msg_count} messages, ended {end}, tokens: {_format_token_count(session_total)} ({_format_token_count(session_input)} in, {_format_token_count(session_output)} out)*\n")
        else:
            lines.append(f"*{msg_count} messages, ended {end}*\n")

        for msg in conv["messages"]:
            ts = msg["timestamp"].strftime("%H:%M")
            role_label = "**USER**" if msg["role"] == "user" else "**CLAUDE**"
            lines.append(f"### [{ts}] {role_label}\n")
            lines.append(msg["text"])
            lines.append("")

    return "\n".join(lines)


DEFAULT_MAX_SIZE_MB = 5


def write_manifest(output_path: Path, project_stats: list, label: str):
    """Write the digest manifest file."""
    total_msgs = sum(p["messages"] for p in project_stats)
    total_size = sum(p["size_kb"] for p in project_stats)

    lines = [
        f"# Digest Manifest",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Scope:** {label}",
        f"**Projects:** {len(project_stats)}",
        f"**Total messages:** {total_msgs}",
        f"**Total size:** {total_size:.0f}KB",
        "",
        "| Project | File | Conversations | Messages | Size |",
        "|---|---|---|---|---|",
    ]

    for p in sorted(project_stats, key=lambda x: x["size_kb"], reverse=True):
        lines.append(f"| {p['name']} | `{Path(p['file']).name}` | {p['conversations']} | {p['messages']} | {p['size_kb']:.0f}KB |")

    manifest_path = output_path / "_manifest.md"
    atomic_write_text(manifest_path, "\n".join(lines))
    return manifest_path, total_msgs, total_size


def write_pending_flag(output_path: Path):
    """Write the digest-pending flag for SessionStart hook."""
    pending_path = output_path.parent / "_digest-pending"
    atomic_write_text(
        pending_path,
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    )


def get_max_jsonl_mtime(project_dir: Path) -> float:
    """Return the latest mtime among all JSONL files in a project directory.
    Returns 0.0 if no JSONL files exist."""
    max_mtime = 0.0
    for jf in project_dir.glob("*.jsonl"):
        try:
            mt = jf.stat().st_mtime
            if mt > max_mtime:
                max_mtime = mt
        except OSError:
            continue
    return max_mtime


def extract_project(project_dir: Path, cutoff: datetime | None) -> tuple[str, str, list, float]:
    """Extract conversations from a single project directory.

    Returns (project_name, safe_name, conversations, max_mtime). The max_mtime
    is sampled once while walking the JSONL files so callers never need a
    second traversal.

    Note: No file-mtime pre-filter is applied. parse_jsonl_file already
    applies the per-message cutoff, and the file-level filter can produce
    false negatives if a file's OS mtime is stale (e.g. restored from backup).
    """
    project_name = folder_to_project_name(project_dir.name)
    safe_name = folder_to_safe_filename(project_dir.name)
    conversations = []
    max_mtime = 0.0

    for jf in project_dir.glob("*.jsonl"):
        try:
            mt = jf.stat().st_mtime
            if mt > max_mtime:
                max_mtime = mt
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

    return project_name, safe_name, conversations, max_mtime


def _last_sync_path(output_path: Path, safe_name: str) -> Path:
    """Return the path to the .last_sync timestamp file for a project."""
    return output_path / f".last_sync_{safe_name}"


def _read_last_sync(output_path: Path, safe_name: str) -> float:
    """Read the stored mtime from a .last_sync file. Returns 0.0 if missing."""
    p = _last_sync_path(output_path, safe_name)
    try:
        return float(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def _write_last_sync(output_path: Path, safe_name: str, mtime: float):
    """Write the latest JSONL mtime to the .last_sync file (atomic)."""
    p = _last_sync_path(output_path, safe_name)
    atomic_write_text(p, str(mtime))


def _should_skip_project(project_dir: Path, output_path: Path, safe_name: str, force: bool) -> tuple[bool, float]:
    """Decide whether to skip a project based on .last_sync vs current JSONL mtime.

    Returns (skip, current_mtime). Uses strict `<` so a new file with an
    mtime exactly equal to the previously stored value is NOT silently skipped.
    """
    if force:
        return (False, 0.0)
    current_mtime = get_max_jsonl_mtime(project_dir)
    last_sync_mtime = _read_last_sync(output_path, safe_name)
    # Strict `<=`: skip when the recorded mtime is at least as new as the current max.
    # Note: if a new file appears with mtime exactly equal to the stored value
    # (clock-tick collision, restored backup with preserved mtime), it will be
    # missed. Run with --force to recover.
    if current_mtime > 0 and current_mtime <= last_sync_mtime:
        return (True, current_mtime)
    return (False, current_mtime)


def _trim_to_size(project_name: str, conversations: list, max_size_bytes: int) -> tuple[list, int, str | None]:
    """Drop oldest sessions until digest fits under max_size_bytes.

    Returns (kept, dropped_count, earliest_dropped_date). Measures each
    session's serialized size exactly once — no O(n²) rebuilds.
    """
    if len(conversations) <= 1:
        return (conversations, 0, None)

    # Sort newest-first so we keep the most recent sessions.
    conversations_sorted = sorted(conversations, key=lambda c: c["latest"], reverse=True)

    # Measure each session's byte cost once.
    sizes = [
        len(build_project_digest(project_name, [c]).encode("utf-8"))
        for c in conversations_sorted
    ]

    kept = []
    running = 0
    for c, sz in zip(conversations_sorted, sizes):
        if running + sz > max_size_bytes and kept:
            break
        kept.append(c)
        running += sz

    dropped = conversations_sorted[len(kept):]
    if not dropped:
        return (conversations, 0, None)

    earliest_dropped = min(d["earliest"] for d in dropped).strftime("%Y-%m-%d")
    kept.reverse()  # Back to chronological order for the digest
    return (kept, len(dropped), earliest_dropped)


def run(days: int | None, output_dir: str, extract_all: bool,
        max_size_mb: float = DEFAULT_MAX_SIZE_MB, force: bool = False):
    """Main extraction logic."""
    claude_projects = find_claude_projects_dir()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    max_size_bytes = int(max_size_mb * 1024 * 1024)

    cutoff = None
    if not extract_all:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days or 1)
        label = f"last {days} days"
    else:
        label = "ALL TIME"

    print(f"Claude projects: {claude_projects}", file=sys.stderr)
    print(f"Scanning conversations ({label}, max {max_size_mb}MB per digest)...", file=sys.stderr)

    project_stats = []
    skipped_count = 0
    seen_safe_names: dict[str, str] = {}  # safe_name -> original folder name

    for project_dir in sorted(claude_projects.iterdir()):
        if not project_dir.is_dir():
            continue

        safe_name_check = folder_to_safe_filename(project_dir.name)

        # Deduplication: skip projects whose JSONL files haven't changed.
        skip, _ = _should_skip_project(project_dir, output_path, safe_name_check, force)
        if skip:
            skipped_count += 1
            continue

        project_name, safe_name, conversations, max_mtime = extract_project(project_dir, cutoff)

        if not conversations:
            continue

        # Filename collision detection — two distinct source folders producing
        # the same safe_name would silently overwrite each other.
        if safe_name in seen_safe_names and seen_safe_names[safe_name] != project_dir.name:
            import hashlib
            suffix = hashlib.sha1(project_dir.name.encode()).hexdigest()[:6]
            safe_name = f"{safe_name}-{suffix}"
            print(f"  Collision: {project_dir.name} -> {safe_name}.md (suffixed)", file=sys.stderr)
        seen_safe_names[safe_name] = project_dir.name

        # Size cap — single final build, O(n) measurement
        kept, dropped_count, earliest_dropped = _trim_to_size(
            project_name, conversations, max_size_bytes
        )
        digest = build_project_digest(project_name, kept)
        if dropped_count:
            note = (
                f"\n\n> **Note:** {dropped_count} older session(s) trimmed "
                f"(earliest dropped: {earliest_dropped}) to stay under {max_size_mb}MB limit.\n"
            )
            digest = digest + note
            print(f"  {project_name}: trimmed {dropped_count} old session(s) (before {earliest_dropped})", file=sys.stderr)

        digest_bytes = len(digest.encode("utf-8"))
        digest_file = output_path / f"{safe_name}.md"

        # Skip write if content is byte-identical to existing digest.
        if digest_file.exists():
            try:
                if digest_file.read_text(encoding="utf-8") == digest:
                    # Still record mtime so next run can skip the project.
                    if max_mtime > 0:
                        _write_last_sync(output_path, safe_name, max_mtime)
                    continue
            except OSError:
                pass

        atomic_write_text(digest_file, digest)

        # Record the latest JSONL mtime (sampled during extract_project — no re-traversal).
        if max_mtime > 0:
            _write_last_sync(output_path, safe_name, max_mtime)

        conversations = kept
        total_messages = sum(len(c["messages"]) for c in conversations)
        file_size_kb = digest_bytes / 1024

        project_stats.append({
            "name": project_name,
            "file": str(digest_file),
            "conversations": len(conversations),
            "messages": total_messages,
            "size_kb": file_size_kb,
        })

        print(f"  {project_name}: {len(conversations)} conversations, {total_messages} messages, {file_size_kb:.0f}KB", file=sys.stderr)

    if skipped_count > 0:
        print(f"  Skipped {skipped_count} unchanged project(s)", file=sys.stderr)

    if not project_stats:
        if skipped_count == 0:
            print(f"No conversations found ({label}).", file=sys.stderr)
        return

    manifest_path, total_msgs, total_size = write_manifest(output_path, project_stats, label)
    write_pending_flag(output_path)

    print(f"\n  TOTAL: {len(project_stats)} projects, {total_msgs} messages, {total_size:.0f}KB", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    print(f"  Pending flag written.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Generate conversation digests for memory sync")
    parser.add_argument("--days", type=int, default=1, help="Look back N days (default: 1)")
    parser.add_argument("--all", action="store_true", help="Extract ALL conversations")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory")
    parser.add_argument("--max-size", type=float, default=DEFAULT_MAX_SIZE_MB,
                       help=f"Max digest file size in MB (default: {DEFAULT_MAX_SIZE_MB})")
    parser.add_argument("--force", action="store_true",
                       help="Ignore deduplication timestamps and rebuild all digests")
    args = parser.parse_args()

    default_dir = Path(__file__).parent / "_digests"
    output_dir = args.output_dir or str(default_dir)

    run(days=args.days, output_dir=output_dir, extract_all=args.all,
        max_size_mb=args.max_size, force=args.force)


if __name__ == "__main__":
    main()
