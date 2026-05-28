"""Tests for pure-Python helpers in build_pipeline_activities.

These tests cover _write_task, _find_task_file, _build_agent_task, and
process_triage_output without requiring a live Temporal server or any
async runtime.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── _write_task ───────────────────────────────────────────────────────────────


def test_write_task_creates_yml_file(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    task = {"id": "abc12345-0000-0000-0000-000000000000", "summary": "test task"}
    act._write_task(task)

    yml_files = list(tmp_path.glob("*.yml"))
    assert len(yml_files) == 1
    assert yml_files[0].suffix == ".yml"


def test_write_task_file_contains_correct_data(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    task = {"id": "abc12345-0000-0000-0000-000000000000", "summary": "hello"}
    act._write_task(task)

    yml_file = list(tmp_path.glob("*.yml"))[0]
    data = yaml.safe_load(yml_file.read_text())
    assert data["id"] == "abc12345-0000-0000-0000-000000000000"
    assert data["summary"] == "hello"


def test_write_task_is_atomic_no_tmp_left(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    act._write_task({"id": "abc12345-0000-0000-0000-000000000000", "x": 1})

    assert list(tmp_path.glob("*.tmp")) == []


def test_write_task_filename_includes_task_id_prefix(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    task = {"id": "deadbeef-0000-0000-0000-000000000000", "x": 1}
    act._write_task(task)

    yml_files = list(tmp_path.glob("*.yml"))
    assert "deadbeef"[:8] in yml_files[0].name


def test_write_task_file_permissions(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    act._write_task({"id": "abc12345-0000-0000-0000-000000000000"})

    yml_file = list(tmp_path.glob("*.yml"))[0]
    # Owner read/write only (0o600)
    assert oct(yml_file.stat().st_mode)[-3:] == "600"


# ── _find_task_file ───────────────────────────────────────────────────────────


def test_find_task_file_found_in_queue(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    task_id = "findme00-0000-0000-0000-000000000000"
    act._write_task({"id": task_id, "summary": "find me"})

    result = act._find_task_file(task_id)
    assert result is not None
    assert result.exists()


def test_find_task_file_found_in_archive(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    archive = tmp_path / "archive"
    archive.mkdir()
    task_id = "archived0-0000-0000-0000-000000000000"
    yml = archive / "20260101-000000-archived0.yml"
    yml.write_text(yaml.dump({"id": task_id}))

    result = act._find_task_file(task_id)
    assert result is not None
    assert "archive" in str(result)


def test_find_task_file_not_found_returns_none(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    result = act._find_task_file("missing-id-0000-0000-0000-000000000000")
    assert result is None


def test_find_task_file_skips_malformed_yaml(tmp_path, monkeypatch):
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "TASK_QUEUE_DIR", tmp_path)

    (tmp_path / "bad.yml").write_text(": : : invalid yaml {{{")

    result = act._find_task_file("any-id-0000-0000-0000-000000000000")
    assert result is None


# ── _build_agent_task ─────────────────────────────────────────────────────────


def test_build_agent_task_structure(monkeypatch):
    import activities.build_pipeline_activities as act

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    task = act._build_agent_task(
        task_id="test1234-0000-0000-0000-000000000000",
        target_agent="dev",
        task_type="build",
        summary="build something",
        payload={"key": "val"},
        task_token_b64="dG9rZW4=",
        now=now,
    )

    assert task["id"] == "test1234-0000-0000-0000-000000000000"
    assert task["target_agent"] == "dev"
    assert task["source_agent"] == "temporal-worker"
    assert task["status"] == "submitted"
    assert task["task_type"] == "build"
    assert task["payload"]["task_token"] == "dG9rZW4="
    assert task["payload"]["key"] == "val"
    assert task["ttl_days"] == 7


def test_build_agent_task_history_entry(monkeypatch):
    import activities.build_pipeline_activities as act

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    task = act._build_agent_task(
        task_id="test1234-0000-0000-0000-000000000000",
        target_agent="dev",
        task_type="build",
        summary="my summary",
        payload={},
        task_token_b64="tok",
        now=now,
    )

    assert len(task["history"]) == 1
    assert task["history"][0]["status"] == "submitted"
    assert task["history"][0]["note"] == "my summary"


# ── process_triage_output ────────────────────────────────────────────────────


def test_process_triage_output_parses_correctly(tmp_path, monkeypatch):
    import asyncio
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "AUDIT_DIR", tmp_path)

    build_dir = tmp_path / "my-build"
    build_dir.mkdir()
    (build_dir / "triage-output.yml").write_text(yaml.dump({
        "blocks": ["critical issue A", "critical issue B"],
        "flags": ["warning 1"],
        "info": ["note 1", "note 2"],
    }))

    result = asyncio.run(act.process_triage_output("my-build"))
    assert result.blocks == ["critical issue A", "critical issue B"]
    assert result.flags == ["warning 1"]
    assert result.info == ["note 1", "note 2"]


def test_process_triage_output_file_not_found(tmp_path, monkeypatch):
    import asyncio
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "AUDIT_DIR", tmp_path)

    with pytest.raises(FileNotFoundError):
        asyncio.run(act.process_triage_output("nonexistent-build"))


def test_process_triage_output_malformed_yaml_raises(tmp_path, monkeypatch):
    import asyncio
    import activities.build_pipeline_activities as act
    from temporalio.exceptions import ApplicationError
    monkeypatch.setattr(act, "AUDIT_DIR", tmp_path)

    build_dir = tmp_path / "bad-build"
    build_dir.mkdir()
    (build_dir / "triage-output.yml").write_text("- this is a list, not a dict")

    with pytest.raises(ApplicationError):
        asyncio.run(act.process_triage_output("bad-build"))


def test_process_triage_output_empty_sections(tmp_path, monkeypatch):
    import asyncio
    import activities.build_pipeline_activities as act
    monkeypatch.setattr(act, "AUDIT_DIR", tmp_path)

    build_dir = tmp_path / "clean-build"
    build_dir.mkdir()
    (build_dir / "triage-output.yml").write_text(yaml.dump({"blocks": [], "flags": [], "info": []}))

    result = asyncio.run(act.process_triage_output("clean-build"))
    assert result.blocks == []
    assert result.flags == []
    assert result.info == []
