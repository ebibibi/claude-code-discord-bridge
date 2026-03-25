"""JBS AI業務支援ツール — Azure Functions API。

タスク定義（YAML）に基づいてファイルを処理するAPIエンドポイント群。
"""

import json
import logging
import os
import time

import azure.functions as func
from azure.identity import DefaultAzureCredential
from services.ai_service import AIService
from services.excel_service import extract_as_text
from services.task_service import TaskService

app = func.FunctionApp()

_endpoint = os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "")
_task_service = TaskService()


def _get_ai_service() -> AIService:
    return AIService(
        endpoint=_endpoint,
        credential=DefaultAzureCredential(),
    )


# -------------------------------------------------------------------
# GET /api/tasks — タスク一覧
# -------------------------------------------------------------------
@app.function_name("tasks_list")
@app.route(route="tasks", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def tasks_list(req: func.HttpRequest) -> func.HttpResponse:
    tasks = _task_service.load_all()
    result = [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "department": t.department,
            "category": t.category,
            "icon": t.icon,
            "version": t.version,
            "input_files": [
                {
                    "name": f.name,
                    "label": f.label,
                    "accept": f.accept,
                    "required": f.required,
                    "max_size_mb": f.max_size_mb,
                }
                for f in t.input_files
            ],
        }
        for t in tasks.values()
    ]
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


# -------------------------------------------------------------------
# GET /api/tasks/{task_id} — タスク定義詳細
# -------------------------------------------------------------------
@app.function_name("task_detail")
@app.route(route="tasks/{task_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def task_detail(req: func.HttpRequest) -> func.HttpResponse:
    task_id = req.route_params.get("task_id", "")
    task = _task_service.get_task(task_id)
    if not task:
        return func.HttpResponse(
            json.dumps({"error": f"Task '{task_id}' not found"}, ensure_ascii=False),
            status_code=404,
            mimetype="application/json",
        )

    result = {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "department": task.department,
        "category": task.category,
        "icon": task.icon,
        "version": task.version,
        "input_files": [
            {
                "name": f.name,
                "label": f.label,
                "accept": f.accept,
                "required": f.required,
                "max_size_mb": f.max_size_mb,
            }
            for f in task.input_files
        ],
        "output_files": [
            {"name": f.name, "label": f.label, "format": f.format} for f in task.output_files
        ],
        "preview": {"type": task.preview.type, "editable": task.preview.editable},
    }
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


# -------------------------------------------------------------------
# POST /api/tasks/{task_id}/execute — タスク実行
# -------------------------------------------------------------------
@app.function_name("task_execute")
@app.route(route="tasks/{task_id}/execute", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def task_execute(req: func.HttpRequest) -> func.HttpResponse:
    task_id = req.route_params.get("task_id", "")
    task = _task_service.get_task(task_id)
    if not task:
        return func.HttpResponse(
            json.dumps({"error": f"Task '{task_id}' not found"}, ensure_ascii=False),
            status_code=404,
            mimetype="application/json",
        )

    # ファイル取得（クライアントエラーを先にチェック）
    files = req.files
    if not files:
        return func.HttpResponse(
            json.dumps({"error": "ファイルがアップロードされていません"}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )

    if not _endpoint:
        return func.HttpResponse(
            json.dumps({"error": "AI endpoint not configured"}, ensure_ascii=False),
            status_code=503,
            mimetype="application/json",
        )

    # 最初の入力ファイルを取得
    first_file_spec = task.input_files[0] if task.input_files else None
    file_key = first_file_spec.name if first_file_spec else list(files.keys())[0]
    uploaded = files.get(file_key)
    if not uploaded:
        # フォームフィールド名が違う場合、最初のファイルを使う
        uploaded = list(files.values())[0]

    file_bytes = uploaded.read()
    filename = uploaded.filename or "uploaded.xlsx"

    # ファイルサイズチェック
    max_size = (first_file_spec.max_size_mb if first_file_spec else 10) * 1024 * 1024
    if len(file_bytes) > max_size:
        return func.HttpResponse(
            json.dumps(
                {"error": f"ファイルサイズが上限（{first_file_spec.max_size_mb}MB）を超えています"},
                ensure_ascii=False,
            ),
            status_code=400,
            mimetype="application/json",
        )

    start_time = time.time()

    try:
        # Excelをテキストに変換
        excel_text = extract_as_text(file_bytes)

        # システムプロンプト読み込み
        system_prompt = _task_service.get_system_prompt(task)

        # フィールドマッピング読み込み
        field_mapping = _task_service.get_field_mapping(task)
        mapping_instruction = ""
        if field_mapping:
            mapping_instruction = "\n\n## フィールドマッピング\n" + json.dumps(
                field_mapping, ensure_ascii=False, indent=2
            )

        # AI呼出
        ai_service = _get_ai_service()
        user_message = (
            f"以下のExcelファイルの内容を処理してください。\n\n"
            f"ファイル名: {filename}\n\n"
            f"{excel_text}{mapping_instruction}"
        )

        response_text, usage = await ai_service.invoke(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=system_prompt,
            model=task.processing.model,
        )

        # AI出力をJSONとしてパース
        fields = _parse_ai_response(response_text)

        processing_time_ms = int((time.time() - start_time) * 1000)

        result = {
            "execution_id": _generate_id(),
            "task_id": task_id,
            "status": "success",
            "preview": {
                "type": task.preview.type,
                "editable": task.preview.editable,
                "fields": fields,
            },
            "processing_time_ms": processing_time_ms,
            "token_usage": usage,
        }
        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Task execution failed")
        processing_time_ms = int((time.time() - start_time) * 1000)
        return func.HttpResponse(
            json.dumps(
                {
                    "status": "error",
                    "error": str(e),
                    "processing_time_ms": processing_time_ms,
                },
                ensure_ascii=False,
            ),
            status_code=500,
            mimetype="application/json",
        )


# -------------------------------------------------------------------
# POST /api/executions/{id}/edits — ユーザー修正の記録
# -------------------------------------------------------------------
@app.function_name("record_edits")
@app.route(
    route="executions/{execution_id}/edits", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS
)
async def record_edits(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )

    # 修正記録はログに残す（Table Storage は後で追加）
    execution_id = req.route_params.get("execution_id", "")
    edits = body.get("edits", [])
    logging.info("Edits recorded for execution %s: %d fields modified", execution_id, len(edits))

    return func.HttpResponse(
        json.dumps({"status": "ok", "edits_count": len(edits)}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


# -------------------------------------------------------------------
# GET /api/health — ヘルスチェック
# -------------------------------------------------------------------
@app.function_name("tools_health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    tasks = _task_service.load_all()
    return func.HttpResponse(
        json.dumps(
            {
                "status": "healthy",
                "tasks_loaded": len(tasks),
                "task_ids": list(tasks.keys()),
            },
            ensure_ascii=False,
        ),
        status_code=200,
        mimetype="application/json",
    )


# -------------------------------------------------------------------
# ヘルパー関数
# -------------------------------------------------------------------
def _parse_ai_response(text: str) -> list[dict]:
    """AIの出力をフィールド一覧にパースする。

    AIにはJSON形式で出力するよう指示する。
    パースに失敗した場合はテキストをそのまま返す。
    """
    # ```json ... ``` ブロックを探す
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "fields" in parsed:
            return parsed["fields"]
        return [{"name": "result", "source_value": "", "output_value": str(parsed)}]
    except (json.JSONDecodeError, ValueError):
        return [{"name": "result", "source_value": "", "output_value": text}]


def _generate_id() -> str:
    import uuid

    return str(uuid.uuid4())
