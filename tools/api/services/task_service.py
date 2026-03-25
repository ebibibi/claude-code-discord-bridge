"""タスク定義の読み込み・バリデーション。

tasks/*.yaml を読み込んで TaskDefinition を返す。
ユースケース追加はYAMLファイルを追加するだけ。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FileSpec:
    name: str
    label: str
    accept: str = ".xlsx"
    required: bool = True
    max_size_mb: int = 10


@dataclass(frozen=True)
class OutputFileSpec:
    name: str
    label: str
    format: str = "xlsx"
    template: str = ""


@dataclass(frozen=True)
class PreviewSpec:
    type: str = "field_mapping"
    editable: bool = True


@dataclass(frozen=True)
class ProcessingSpec:
    model: str = "claude-sonnet-4-6"
    system_prompt_file: str = ""
    field_mapping_file: str = ""
    timeout_seconds: int = 120


@dataclass(frozen=True)
class AccessSpec:
    roles: tuple[str, ...] = ("authenticated",)


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    name: str
    description: str = ""
    department: str = ""
    category: str = ""
    icon: str = "📋"
    version: str = "1.0.0"
    input_files: tuple[FileSpec, ...] = ()
    output_files: tuple[OutputFileSpec, ...] = ()
    preview: PreviewSpec = field(default_factory=PreviewSpec)
    processing: ProcessingSpec = field(default_factory=ProcessingSpec)
    access: AccessSpec = field(default_factory=AccessSpec)


def _parse_task(raw: dict[str, Any]) -> TaskDefinition:
    input_section = raw.get("input", {})
    input_files = tuple(FileSpec(**f) for f in input_section.get("files", []))

    output_section = raw.get("output", {})
    output_files = tuple(OutputFileSpec(**f) for f in output_section.get("files", []))

    preview_raw = output_section.get("preview", {})
    preview = PreviewSpec(**preview_raw) if preview_raw else PreviewSpec()

    proc_raw = raw.get("processing", {})
    # skill フィールドは今は使わない（将来用）
    proc_raw.pop("skill", None)
    processing = ProcessingSpec(**proc_raw) if proc_raw else ProcessingSpec()

    access_raw = raw.get("access", {})
    roles = tuple(access_raw.get("roles", ["authenticated"]))
    access = AccessSpec(roles=roles)

    return TaskDefinition(
        id=raw["id"],
        name=raw["name"],
        description=raw.get("description", ""),
        department=raw.get("department", ""),
        category=raw.get("category", ""),
        icon=raw.get("icon", "📋"),
        version=raw.get("version", "1.0.0"),
        input_files=input_files,
        output_files=output_files,
        preview=preview,
        processing=processing,
        access=access,
    )


class TaskService:
    def __init__(self, tasks_dir: str | None = None) -> None:
        if tasks_dir is None:
            tasks_dir = os.path.join(os.path.dirname(__file__), "..", "tasks")
        self._tasks_dir = Path(tasks_dir)
        self._cache: dict[str, TaskDefinition] = {}

    def load_all(self) -> dict[str, TaskDefinition]:
        if self._cache:
            return dict(self._cache)

        result: dict[str, TaskDefinition] = {}
        if not self._tasks_dir.exists():
            return result

        for yaml_path in sorted(self._tasks_dir.glob("*.yaml")):
            with open(yaml_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if raw and "id" in raw:
                task = _parse_task(raw)
                result[task.id] = task

        self._cache = result
        return dict(result)

    def get_task(self, task_id: str) -> TaskDefinition | None:
        tasks = self.load_all()
        return tasks.get(task_id)

    def get_system_prompt(self, task: TaskDefinition) -> str:
        if not task.processing.system_prompt_file:
            return ""
        prompt_path = self._tasks_dir.parent / task.processing.system_prompt_file
        if not prompt_path.exists():
            return ""
        return prompt_path.read_text(encoding="utf-8")

    def get_field_mapping(self, task: TaskDefinition) -> list[dict[str, str]]:
        if not task.processing.field_mapping_file:
            return []
        mapping_path = self._tasks_dir.parent / task.processing.field_mapping_file
        if not mapping_path.exists():
            return []
        import json

        return json.loads(mapping_path.read_text(encoding="utf-8"))
