"""Incremental conversation sync — only copies new/modified JSONL files.

Append-only: files deleted from source are NOT removed from destination
(backup/archive semantics). Use a separate prune step if needed.
"""
import sys, shutil
from pathlib import Path

ALLOWED_SUFFIXES = {".jsonl", ".json"}


def sync(source, dest):
    """Copy only files that are new or modified since last sync.

    Directory-level early-exit: if a project subdir's mtime is older than the
    destination subdir's mtime, the entire subtree is skipped.
    """
    source = Path(source)
    dest = Path(dest)
    copied = 0
    skipped = 0
    errors = 0
    pruned_dirs = 0

    # Top-level project dirs first — allows subtree-level skipping.
    for project_dir in source.iterdir():
        if project_dir.is_file():
            if project_dir.suffix not in ALLOWED_SUFFIXES:
                continue
            c, s, e = _copy_one(project_dir, dest / project_dir.name)
            copied += c; skipped += s; errors += e
            continue
        if not project_dir.is_dir():
            continue

        rel_dir = project_dir.relative_to(source)
        dst_dir = dest / rel_dir

        # Directory-level early-exit
        if dst_dir.exists():
            try:
                if project_dir.stat().st_mtime <= dst_dir.stat().st_mtime:
                    pruned_dirs += 1
                    continue
            except OSError:
                pass

        for src_file in project_dir.rglob("*"):
            if not src_file.is_file():
                continue
            if src_file.suffix not in ALLOWED_SUFFIXES:
                continue
            rel = src_file.relative_to(source)
            dst_file = dest / rel
            c, s, e = _copy_one(src_file, dst_file)
            copied += c; skipped += s; errors += e

        # Touch destination subdir mtime so next run's early-exit works.
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            import os
            os.utime(dst_dir, None)
        except OSError:
            pass

    print(f"  Sync: {copied} copied, {skipped} unchanged, {errors} errors, {pruned_dirs} subtrees pruned", file=sys.stderr)
    return errors == 0


def _copy_one(src_file: Path, dst_file: Path):
    """Copy a single file if it's new or modified. Returns (copied, skipped, errors)."""
    if dst_file.exists():
        try:
            src_stat = src_file.stat()
            dst_stat = dst_file.stat()
            if dst_stat.st_size == src_stat.st_size and dst_stat.st_mtime >= src_stat.st_mtime:
                return (0, 1, 0)
        except OSError:
            pass
    try:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp then rename for atomicity
        tmp = dst_file.with_suffix(dst_file.suffix + ".tmp")
        shutil.copy2(str(src_file), str(tmp))
        tmp.replace(dst_file)
        return (1, 0, 0)
    except (OSError, PermissionError) as e:
        print(f"  ERROR copying {src_file.name}: {e}", file=sys.stderr)
        return (0, 0, 1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python sync-conversations.py <source> <dest>", file=sys.stderr)
        sys.exit(1)
    ok = sync(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
