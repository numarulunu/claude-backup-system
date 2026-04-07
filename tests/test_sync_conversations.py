"""Tests for sync-conversations.py — incremental file sync logic."""
import tempfile
import time
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib
sync_mod = importlib.import_module("sync-conversations")


class TestSync:
    def test_copies_new_files(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.jsonl").write_text("line1\n")

        result = sync_mod.sync(str(src), str(dst))

        assert result is True
        assert (dst / "a.jsonl").read_text() == "line1\n"

    def test_skips_unchanged_files(self, tmp_path, capsys):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.jsonl").write_text("line1\n")
        # Pre-populate destination with same content
        (dst / "a.jsonl").write_text("line1\n")
        # Make dst mtime >= src mtime
        src_mtime = (src / "a.jsonl").stat().st_mtime
        import os
        os.utime(str(dst / "a.jsonl"), (src_mtime + 1, src_mtime + 1))

        sync_mod.sync(str(src), str(dst))

        captured = capsys.readouterr()
        assert "0 copied" in captured.err
        assert "1 unchanged" in captured.err

    def test_copies_modified_files(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (dst / "a.jsonl").write_text("old\n")
        time.sleep(0.05)
        (src / "a.jsonl").write_text("new content\n")

        sync_mod.sync(str(src), str(dst))

        assert (dst / "a.jsonl").read_text() == "new content\n"

    def test_creates_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        (src / "sub" / "deep").mkdir(parents=True)
        dst.mkdir()
        (src / "sub" / "deep" / "file.jsonl").write_text("data\n")

        sync_mod.sync(str(src), str(dst))

        assert (dst / "sub" / "deep" / "file.jsonl").read_text() == "data\n"

    def test_reports_errors_and_returns_false(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.jsonl").write_text("data\n")

        # Make copy2 always fail
        import shutil
        def bad_copy(s, d):
            raise PermissionError("access denied")
        monkeypatch.setattr(shutil, "copy2", bad_copy)

        result = sync_mod.sync(str(src), str(dst))

        assert result is False

    def test_skips_non_jsonl_files(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        (src / "proj").mkdir(parents=True)
        dst.mkdir()
        (src / "proj" / "conv.jsonl").write_text("data\n")
        (src / "proj" / "secrets.env").write_text("API_KEY=abc\n")
        (src / "proj" / "cache.db").write_text("binary\n")

        sync_mod.sync(str(src), str(dst))

        assert (dst / "proj" / "conv.jsonl").exists()
        assert not (dst / "proj" / "secrets.env").exists()
        assert not (dst / "proj" / "cache.db").exists()

    def test_empty_source(self, tmp_path, capsys):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()

        result = sync_mod.sync(str(src), str(dst))

        assert result is True
        captured = capsys.readouterr()
        assert "0 copied" in captured.err
