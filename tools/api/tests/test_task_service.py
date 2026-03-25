"""TaskService のテスト。"""

import tempfile
from pathlib import Path

import pytest
import yaml
from services.task_service import TaskService


@pytest.fixture
def task_yaml():
    return {
        "id": "test-task",
        "name": "テストタスク",
        "description": "テスト用のタスク定義",
        "department": "テスト部",
        "category": "テスト",
        "icon": "🧪",
        "version": "1.0.0",
        "input": {
            "files": [
                {
                    "name": "input_file",
                    "label": "入力ファイル",
                    "accept": ".xlsx",
                    "required": True,
                    "max_size_mb": 5,
                }
            ]
        },
        "output": {
            "files": [{"name": "output_file", "label": "出力ファイル", "format": "xlsx"}],
            "preview": {"type": "field_mapping", "editable": True},
        },
        "processing": {
            "model": "claude-sonnet-4-6",
            "system_prompt_file": "prompts/test.md",
            "field_mapping_file": "mappings/test.json",
            "timeout_seconds": 60,
        },
        "access": {"roles": ["test-role", "all-staff"]},
    }


@pytest.fixture
def tasks_dir(task_yaml):
    with tempfile.TemporaryDirectory() as tmpdir:
        tasks_path = Path(tmpdir) / "tasks"
        tasks_path.mkdir()
        with open(tasks_path / "test-task.yaml", "w", encoding="utf-8") as f:
            yaml.dump(task_yaml, f, allow_unicode=True)
        yield str(tasks_path)


class TestTaskServiceLoadAll:
    def test_loads_task_from_yaml(self, tasks_dir):
        svc = TaskService(tasks_dir)
        tasks = svc.load_all()
        assert "test-task" in tasks

    def test_task_has_correct_fields(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.load_all()["test-task"]
        assert task.id == "test-task"
        assert task.name == "テストタスク"
        assert task.department == "テスト部"
        assert task.icon == "🧪"
        assert task.version == "1.0.0"

    def test_input_files_parsed(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.load_all()["test-task"]
        assert len(task.input_files) == 1
        assert task.input_files[0].name == "input_file"
        assert task.input_files[0].max_size_mb == 5

    def test_output_files_parsed(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.load_all()["test-task"]
        assert len(task.output_files) == 1
        assert task.output_files[0].format == "xlsx"

    def test_processing_parsed(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.load_all()["test-task"]
        assert task.processing.model == "claude-sonnet-4-6"
        assert task.processing.timeout_seconds == 60

    def test_access_roles_parsed(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.load_all()["test-task"]
        assert "test-role" in task.access.roles
        assert "all-staff" in task.access.roles

    def test_empty_directory_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svc = TaskService(tmpdir)
            assert svc.load_all() == {}

    def test_caches_after_first_load(self, tasks_dir):
        svc = TaskService(tasks_dir)
        first = svc.load_all()
        second = svc.load_all()
        assert first == second


class TestTaskServiceGetTask:
    def test_returns_task_by_id(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.get_task("test-task")
        assert task is not None
        assert task.id == "test-task"

    def test_returns_none_for_missing(self, tasks_dir):
        svc = TaskService(tasks_dir)
        assert svc.get_task("nonexistent") is None


class TestTaskServicePromptAndMapping:
    def test_get_system_prompt_reads_file(self, tasks_dir):
        # プロンプトファイルを作成
        prompts_dir = Path(tasks_dir).parent / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "test.md").write_text("テストプロンプト", encoding="utf-8")

        svc = TaskService(tasks_dir)
        task = svc.get_task("test-task")
        prompt = svc.get_system_prompt(task)
        assert prompt == "テストプロンプト"

    def test_get_system_prompt_returns_empty_for_missing(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.get_task("test-task")
        prompt = svc.get_system_prompt(task)
        assert prompt == ""

    def test_get_field_mapping_reads_json(self, tasks_dir):
        import json

        mappings_dir = Path(tasks_dir).parent / "mappings"
        mappings_dir.mkdir()
        mapping_data = [{"source_field": "A", "target_field": "B"}]
        (mappings_dir / "test.json").write_text(json.dumps(mapping_data), encoding="utf-8")

        svc = TaskService(tasks_dir)
        task = svc.get_task("test-task")
        mapping = svc.get_field_mapping(task)
        assert len(mapping) == 1
        assert mapping[0]["source_field"] == "A"


class TestTaskDefinitionImmutability:
    def test_task_is_frozen(self, tasks_dir):
        svc = TaskService(tasks_dir)
        task = svc.get_task("test-task")
        with pytest.raises(AttributeError):
            task.name = "changed"
