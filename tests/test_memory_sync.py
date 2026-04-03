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
