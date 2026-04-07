"""Tests for memory-sync.py — digest generation logic."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add parent to path so we can import memory-sync
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import with hyphen in name
import importlib
memory_sync = importlib.import_module("memory-sync")


# ---------------------------------------------------------------------------
# folder_to_project_name
# ---------------------------------------------------------------------------

class TestFolderToProjectName:
    def test_windows_single_word_username(self):
        result = memory_sync.folder_to_project_name("C--Users-JohnDoe-Desktop-MyProject")
        assert result == "MyProject"

    def test_windows_multi_word_username(self):
        result = memory_sync.folder_to_project_name("C--Users-Gaming-PC-Desktop-Claude-Finance")
        assert result == "Claude Finance"

    def test_windows_short_username(self):
        result = memory_sync.folder_to_project_name("C--Users-GAMING-1-AppData-Local-Temp")
        assert result == "Local Temp"

    def test_windows_documents_path(self):
        result = memory_sync.folder_to_project_name("C--Users-JohnDoe-Documents-Work")
        assert result == "Work"

    def test_linux_path(self):
        result = memory_sync.folder_to_project_name("home-john-MyProject")
        assert result == "MyProject"

    def test_macos_path(self):
        result = memory_sync.folder_to_project_name("Users-jane-Documents-work")
        assert result == "work"

    def test_nested_path(self):
        result = memory_sync.folder_to_project_name("C--Users-JohnDoe-Desktop-Claude-Finance")
        assert result == "Claude Finance"

    def test_drive_letter_prefix(self):
        result = memory_sync.folder_to_project_name("D--SomeFolder")
        assert result == "SomeFolder"

    def test_unrecognized_format_returned_as_is(self):
        result = memory_sync.folder_to_project_name("random-folder-name")
        assert result == "random folder name"

    def test_empty_after_strip_returns_original(self):
        result = memory_sync.folder_to_project_name("")
        assert result == ""

    def test_user_root_dir_no_match(self):
        """A bare user dir with no known segment should return as-is."""
        result = memory_sync.folder_to_project_name("C--Users-Gaming-PC")
        assert result == "C--Users-Gaming-PC"


class TestFolderToSafeFilename:
    def test_basic_conversion(self):
        result = memory_sync.folder_to_safe_filename("C--Users-JohnDoe-Desktop-My-Project")
        assert result == "my-project"

    def test_nested_path(self):
        result = memory_sync.folder_to_safe_filename("C--Users-Gaming-PC-Desktop-Claude-Finance")
        assert result == "claude-finance"

    def test_special_chars_stripped(self):
        result = memory_sync.folder_to_safe_filename("C--Users-JohnDoe-Desktop-Project (v2)")
        assert result == "project-v2"


# ---------------------------------------------------------------------------
# parse_jsonl_file
# ---------------------------------------------------------------------------

def make_jsonl_entry(role, text, timestamp="2026-01-15T10:30:00Z"):
    """Helper to create a JSONL entry."""
    if role == "user":
        return json.dumps({
            "type": "user",
            "timestamp": timestamp,
            "message": {"content": text, "timestamp": timestamp}
        })
    else:
        return json.dumps({
            "type": "assistant",
            "timestamp": timestamp,
            "message": {"content": [{"type": "text", "text": text}], "timestamp": timestamp}
        })


class TestParseJsonlFile:
    def test_basic_parsing(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(
            make_jsonl_entry("user", "Hello", "2026-01-15T10:00:00Z") + "\n" +
            make_jsonl_entry("assistant", "Hi there", "2026-01-15T10:01:00Z") + "\n"
        )
        messages = memory_sync.parse_jsonl_file(f)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["text"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["text"] == "Hi there"

    def test_cutoff_filters_old_messages(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(
            make_jsonl_entry("user", "Old message", "2025-01-01T10:00:00Z") + "\n" +
            make_jsonl_entry("user", "New message", "2026-06-01T10:00:00Z") + "\n"
        )
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        messages = memory_sync.parse_jsonl_file(f, cutoff)
        assert len(messages) == 1
        assert messages[0]["text"] == "New message"

    def test_system_reminders_stripped(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(
            make_jsonl_entry("user", "Hello <system-reminder>noise</system-reminder> world") + "\n"
        )
        messages = memory_sync.parse_jsonl_file(f)
        assert len(messages) == 1
        assert "<system-reminder>" not in messages[0]["text"]
        assert "Hello" in messages[0]["text"]
        assert "world" in messages[0]["text"]

    def test_empty_messages_skipped(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(
            make_jsonl_entry("user", "") + "\n" +
            make_jsonl_entry("user", "Real message") + "\n"
        )
        messages = memory_sync.parse_jsonl_file(f)
        assert len(messages) == 1
        assert messages[0]["text"] == "Real message"

    def test_malformed_json_skipped(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(
            "not valid json\n" +
            make_jsonl_entry("user", "Valid message") + "\n"
        )
        messages = memory_sync.parse_jsonl_file(f)
        assert len(messages) == 1

    def test_tool_use_blocks(self, tmp_path):
        entry = json.dumps({
            "type": "assistant",
            "timestamp": "2026-01-15T10:00:00Z",
            "message": {
                "timestamp": "2026-01-15T10:00:00Z",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "name": "Read"},
                ]
            }
        })
        f = tmp_path / "conv.jsonl"
        f.write_text(entry + "\n")
        messages = memory_sync.parse_jsonl_file(f)
        assert len(messages) == 1
        assert "[Tool: Read]" in messages[0]["text"]


# ---------------------------------------------------------------------------
# build_project_digest
# ---------------------------------------------------------------------------

class TestBuildProjectDigest:
    def test_basic_digest(self):
        conversations = [{
            "file": "test.jsonl",
            "messages": [
                {"role": "user", "text": "Hello", "timestamp": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)},
                {"role": "assistant", "text": "Hi", "timestamp": datetime(2026, 1, 15, 10, 1, tzinfo=timezone.utc)},
            ],
            "earliest": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "latest": datetime(2026, 1, 15, 10, 1, tzinfo=timezone.utc),
        }]
        digest = memory_sync.build_project_digest("Test Project", conversations)
        assert "# Test Project" in digest
        assert "**USER**" in digest
        assert "**CLAUDE**" in digest
        assert "Hello" in digest
        assert "Hi" in digest

    def test_multiple_sessions_sorted(self):
        conv_early = {
            "file": "a.jsonl",
            "messages": [{"role": "user", "text": "First", "timestamp": datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)}],
            "earliest": datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            "latest": datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        }
        conv_late = {
            "file": "b.jsonl",
            "messages": [{"role": "user", "text": "Second", "timestamp": datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)}],
            "earliest": datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
            "latest": datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        }
        digest = memory_sync.build_project_digest("Test", [conv_late, conv_early])
        first_pos = digest.index("First")
        second_pos = digest.index("Second")
        assert first_pos < second_pos, "Earlier session should come first"


# ---------------------------------------------------------------------------
# Token counting in parse_jsonl_file and build_project_digest
# ---------------------------------------------------------------------------

class TestTokenCounting:
    def _make_entry_with_usage(self, role, text, timestamp, input_tokens=0, output_tokens=0):
        """Helper that creates a JSONL entry with usage data."""
        if role == "user":
            entry = {
                "type": "user",
                "timestamp": timestamp,
                "message": {"content": text, "timestamp": timestamp},
            }
        else:
            entry = {
                "type": "assistant",
                "timestamp": timestamp,
                "message": {
                    "content": [{"type": "text", "text": text}],
                    "timestamp": timestamp,
                    "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
                },
            }
        return json.dumps(entry)

    def test_parse_extracts_token_counts(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(
            self._make_entry_with_usage("assistant", "Response", "2026-01-15T10:00:00Z",
                                        input_tokens=500, output_tokens=200) + "\n"
        )
        messages = memory_sync.parse_jsonl_file(f)
        assert len(messages) == 1
        assert messages[0]["input_tokens"] == 500
        assert messages[0]["output_tokens"] == 200

    def test_parse_defaults_zero_without_usage(self, tmp_path):
        f = tmp_path / "conv.jsonl"
        f.write_text(make_jsonl_entry("user", "Hello", "2026-01-15T10:00:00Z") + "\n")
        messages = memory_sync.parse_jsonl_file(f)
        assert messages[0]["input_tokens"] == 0
        assert messages[0]["output_tokens"] == 0

    def test_digest_includes_token_header_when_present(self):
        conversations = [{
            "file": "test.jsonl",
            "messages": [
                {"role": "user", "text": "Hello", "timestamp": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
                 "input_tokens": 0, "output_tokens": 0},
                {"role": "assistant", "text": "Hi", "timestamp": datetime(2026, 1, 15, 10, 1, tzinfo=timezone.utc),
                 "input_tokens": 1500, "output_tokens": 500},
            ],
            "earliest": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "latest": datetime(2026, 1, 15, 10, 1, tzinfo=timezone.utc),
        }]
        digest = memory_sync.build_project_digest("Test", conversations)
        assert "**Tokens:**" in digest
        assert "2.0k total" in digest
        assert "1.5k in" in digest
        assert "500 out" in digest

    def test_digest_session_header_includes_tokens(self):
        conversations = [{
            "file": "test.jsonl",
            "messages": [
                {"role": "assistant", "text": "Hi", "timestamp": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
                 "input_tokens": 3000, "output_tokens": 1000},
            ],
            "earliest": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "latest": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        }]
        digest = memory_sync.build_project_digest("Test", conversations)
        assert "tokens: 4.0k" in digest

    def test_digest_no_token_header_when_zero(self):
        conversations = [{
            "file": "test.jsonl",
            "messages": [
                {"role": "user", "text": "Hello", "timestamp": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
                 "input_tokens": 0, "output_tokens": 0},
            ],
            "earliest": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "latest": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        }]
        digest = memory_sync.build_project_digest("Test", conversations)
        assert "**Tokens:**" not in digest
        # Session header should use the old format (no tokens mention)
        assert "tokens:" not in digest.lower().split("**Tokens:**")[0] if "**Tokens:**" in digest else True


# ---------------------------------------------------------------------------
# Deduplication: .last_sync mechanism
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_write_and_read_last_sync(self, tmp_path):
        memory_sync._write_last_sync(tmp_path, "my-project", 1234567890.5)
        result = memory_sync._read_last_sync(tmp_path, "my-project")
        assert result == 1234567890.5

    def test_read_last_sync_missing_returns_zero(self, tmp_path):
        result = memory_sync._read_last_sync(tmp_path, "nonexistent")
        assert result == 0.0

    def test_last_sync_path(self, tmp_path):
        p = memory_sync._last_sync_path(tmp_path, "my-project")
        assert p.name == ".last_sync_my-project"
        assert p.parent == tmp_path

    def test_get_max_jsonl_mtime(self, tmp_path):
        # Create two jsonl files with different content
        f1 = tmp_path / "a.jsonl"
        f2 = tmp_path / "b.jsonl"
        f1.write_text("{}")
        import time
        time.sleep(0.05)
        f2.write_text("{}")
        mtime = memory_sync.get_max_jsonl_mtime(tmp_path)
        assert mtime == pytest.approx(f2.stat().st_mtime, abs=0.01)

    def test_get_max_jsonl_mtime_empty_dir(self, tmp_path):
        assert memory_sync.get_max_jsonl_mtime(tmp_path) == 0.0

    def _setup_project(self, tmp_path, timestamp="2026-01-15T10:00:00Z"):
        """Create a minimal fake claude_projects/project_dir with one JSONL."""
        projects = tmp_path / "projects"
        project_dir = projects / "C--Users-test-Desktop-Demo"
        project_dir.mkdir(parents=True)
        (project_dir / "a.jsonl").write_text(
            make_jsonl_entry("user", "hello", timestamp) + "\n"
        )
        return projects, project_dir

    def test_run_skips_project_when_last_sync_current(self, tmp_path, monkeypatch):
        projects, project_dir = self._setup_project(tmp_path)
        output = tmp_path / "digests"
        output.mkdir()
        safe = memory_sync.folder_to_safe_filename(project_dir.name)
        # Seed .last_sync with a future timestamp so the project is skipped.
        memory_sync._write_last_sync(output, safe, project_dir.glob("*.jsonl").__next__().stat().st_mtime + 100)
        monkeypatch.setattr(memory_sync, "find_claude_projects_dir", lambda: projects)

        memory_sync.run(days=None, output_dir=str(output), extract_all=True)

        assert not (output / f"{safe}.md").exists()

    def test_run_processes_project_when_jsonl_newer(self, tmp_path, monkeypatch):
        projects, project_dir = self._setup_project(tmp_path)
        output = tmp_path / "digests"
        output.mkdir()
        safe = memory_sync.folder_to_safe_filename(project_dir.name)
        memory_sync._write_last_sync(output, safe, 1.0)  # Ancient
        monkeypatch.setattr(memory_sync, "find_claude_projects_dir", lambda: projects)

        memory_sync.run(days=None, output_dir=str(output), extract_all=True)

        assert (output / f"{safe}.md").exists()

    def test_run_force_bypasses_skip(self, tmp_path, monkeypatch):
        projects, project_dir = self._setup_project(tmp_path)
        output = tmp_path / "digests"
        output.mkdir()
        safe = memory_sync.folder_to_safe_filename(project_dir.name)
        memory_sync._write_last_sync(output, safe, 9999999999.0)  # Future
        monkeypatch.setattr(memory_sync, "find_claude_projects_dir", lambda: projects)

        memory_sync.run(days=None, output_dir=str(output), extract_all=True, force=True)

        assert (output / f"{safe}.md").exists()


class TestTrimToSize:
    def _make_conv(self, file_name, when, text="x" * 500):
        return {
            "file": file_name,
            "messages": [{"role": "user", "text": text, "timestamp": when,
                          "input_tokens": 0, "output_tokens": 0}],
            "earliest": when,
            "latest": when,
        }

    def test_no_trim_when_under_cap(self):
        c = [self._make_conv("a.jsonl", datetime(2026, 1, 1, tzinfo=timezone.utc))]
        kept, dropped, earliest = memory_sync._trim_to_size("P", c, 10_000_000)
        assert len(kept) == 1
        assert dropped == 0
        assert earliest is None

    def test_drops_oldest_and_reports_earliest(self):
        convs = [
            self._make_conv("old.jsonl", datetime(2026, 1, 1, tzinfo=timezone.utc), text="x" * 2000),
            self._make_conv("mid.jsonl", datetime(2026, 2, 1, tzinfo=timezone.utc), text="x" * 2000),
            self._make_conv("new.jsonl", datetime(2026, 3, 1, tzinfo=timezone.utc), text="x" * 2000),
        ]
        kept, dropped, earliest = memory_sync._trim_to_size("P", convs, 3000)
        assert dropped >= 1
        assert earliest == "2026-01-01"
        # Kept sessions should be the most recent ones
        latest_ts = [c["latest"] for c in kept]
        assert max(latest_ts) == datetime(2026, 3, 1, tzinfo=timezone.utc)


class TestFormatTokenCount:
    def test_small(self):
        assert memory_sync._format_token_count(500) == "500"

    def test_thousands(self):
        assert memory_sync._format_token_count(1500) == "1.5k"

    def test_millions(self):
        assert memory_sync._format_token_count(2_500_000) == "2.5M"
