"""タスク実行管理。AI呼出・結果生成・ログ記録を担う。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from azure.data.tables import TableServiceClient


@dataclass(frozen=True)
class FieldResult:
    name: str
    source_value: str
    output_value: str
    confidence: str = "high"
    warning: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    task_id: str
    status: str  # "success" | "error"
    fields: tuple[FieldResult, ...] = ()
    output_blob_url: str = ""
    processing_time_ms: int = 0
    error_message: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)


class ExecutionService:
    def __init__(
        self, table_service: TableServiceClient, table_name: str = "toolexecutions"
    ) -> None:
        self._table_client = table_service.get_table_client(table_name)
        self._table_name = table_name

    def record_execution(
        self,
        result: ExecutionResult,
        user_id: str,
        user_name: str,
    ) -> None:
        entity = {
            "PartitionKey": result.task_id,
            "RowKey": result.execution_id,
            "user_id": user_id,
            "user_name": user_name,
            "status": result.status,
            "output_blob_url": result.output_blob_url,
            "processing_time_ms": result.processing_time_ms,
            "error_message": result.error_message,
            "token_usage": json.dumps(result.token_usage),
            "field_count": len(result.fields),
            "timestamp_iso": datetime.now(UTC).isoformat(),
        }
        self._table_client.upsert_entity(entity)

    def record_edit(
        self,
        execution_id: str,
        field_name: str,
        original_value: str,
        edited_value: str,
    ) -> None:
        entity = {
            "PartitionKey": execution_id,
            "RowKey": field_name,
            "original_value": original_value,
            "edited_value": edited_value,
            "timestamp_iso": datetime.now(UTC).isoformat(),
        }
        self._table_client.upsert_entity(entity)

    @staticmethod
    def new_execution_id() -> str:
        return str(uuid.uuid4())
