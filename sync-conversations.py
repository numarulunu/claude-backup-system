"""Incremental conversation sync — only copies new/modified JSONL files."""
import os, sys, shutil
from pathlib import Path


def sync(source, dest):
    """Copy only files that are new or modified since last sync."""
    source = Path(source)
    dest = Path(dest)
    copied = 0
    skipped = 0
    errors = 0

    for src_file in source.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(source)
        dst_file = dest / rel

        # Skip if destination exists and is same size + same or newer mtime
        if dst_file.exists():
            src_stat = src_file.stat()
            dst_stat = dst_file.stat()
            if dst_stat.st_size == src_stat.st_size and dst_stat.st_mtime >= src_stat.st_mtime:
                skipped += 1
                continue

        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dst_file))
            copied += 1
        except (OSError, PermissionError) as e:
            print(f"  ERROR copying {rel}: {e}", file=sys.stderr)
            errors += 1

    print(f"  Sync: {copied} copied, {skipped} unchanged, {errors} errors", file=sys.stderr)
    return errors == 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python sync-conversations.py <source> <dest>", file=sys.stderr)
        sys.exit(1)
    ok = sync(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
