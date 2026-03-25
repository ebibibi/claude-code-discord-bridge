"""function_app エンドポイントのテスト。"""

import json

import azure.functions as func
import pytest
from function_app import _parse_ai_response, app


class TestParseAiResponse:
    def test_parses_json_array(self):
        text = json.dumps(
            [
                {
                    "name": "就業場所",
                    "source_value": "虎ノ門",
                    "output_value": "虎ノ門",
                    "confidence": "high",
                    "warning": "",
                }
            ]
        )
        result = _parse_ai_response(text)
        assert len(result) == 1
        assert result[0]["name"] == "就業場所"

    def test_parses_json_in_code_block(self):
        inner = json.dumps(
            [
                {
                    "name": "test",
                    "source_value": "a",
                    "output_value": "b",
                    "confidence": "high",
                    "warning": "",
                }
            ]
        )
        text = f"```json\n{inner}\n```"
        result = _parse_ai_response(text)
        assert len(result) == 1
        assert result[0]["name"] == "test"

    def test_parses_dict_with_fields_key(self):
        text = '{"fields": [{"name": "test", "source_value": "a", "output_value": "b"}]}'
        result = _parse_ai_response(text)
        assert len(result) == 1

    def test_handles_plain_text(self):
        result = _parse_ai_response("これはただのテキストです")
        assert len(result) == 1
        assert result[0]["name"] == "result"
        assert "テキスト" in result[0]["output_value"]

    def test_parses_generic_code_block(self):
        text = '```\n[{"name": "a", "source_value": "b", "output_value": "c"}]\n```'
        result = _parse_ai_response(text)
        assert len(result) == 1


class TestHealthEndpoint:
    @pytest.fixture
    def client(self):
        return app

    def test_health_returns_200(self):
        req = func.HttpRequest(
            method="GET",
            url="/api/health",
            body=b"",
        )
        import asyncio

        from function_app import health

        resp = asyncio.get_event_loop().run_until_complete(health(req))
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["status"] == "healthy"
        assert "tasks_loaded" in data


class TestTasksListEndpoint:
    def test_returns_task_list(self):
        req = func.HttpRequest(
            method="GET",
            url="/api/tasks",
            body=b"",
        )
        import asyncio

        from function_app import tasks_list

        resp = asyncio.get_event_loop().run_until_complete(tasks_list(req))
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert isinstance(data, list)
        # legal-transcribe が読み込まれているはず
        ids = [t["id"] for t in data]
        assert "legal-transcribe" in ids


class TestTaskDetailEndpoint:
    def test_returns_task_detail(self):
        req = func.HttpRequest(
            method="GET",
            url="/api/tasks/legal-transcribe",
            route_params={"task_id": "legal-transcribe"},
            body=b"",
        )
        import asyncio

        from function_app import task_detail

        resp = asyncio.get_event_loop().run_until_complete(task_detail(req))
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["id"] == "legal-transcribe"
        assert data["department"] == "法務"

    def test_returns_404_for_missing(self):
        req = func.HttpRequest(
            method="GET",
            url="/api/tasks/nonexistent",
            route_params={"task_id": "nonexistent"},
            body=b"",
        )
        import asyncio

        from function_app import task_detail

        resp = asyncio.get_event_loop().run_until_complete(task_detail(req))
        assert resp.status_code == 404


class TestTaskExecuteEndpoint:
    def test_returns_400_without_file(self):
        req = func.HttpRequest(
            method="POST",
            url="/api/tasks/legal-transcribe/execute",
            route_params={"task_id": "legal-transcribe"},
            body=b"",
        )
        import asyncio

        from function_app import task_execute

        resp = asyncio.get_event_loop().run_until_complete(task_execute(req))
        assert resp.status_code == 400

    def test_returns_404_for_missing_task(self):
        req = func.HttpRequest(
            method="POST",
            url="/api/tasks/nonexistent/execute",
            route_params={"task_id": "nonexistent"},
            body=b"",
        )
        import asyncio

        from function_app import task_execute

        resp = asyncio.get_event_loop().run_until_complete(task_execute(req))
        assert resp.status_code == 404


class TestRecordEditsEndpoint:
    def test_records_edits(self):
        body = json.dumps(
            {
                "edits": [
                    {
                        "field_name": "就業場所",
                        "original_value": "虎ノ門",
                        "edited_value": "虎ノ門ヒルズ 42F",
                    }
                ]
            }
        )
        req = func.HttpRequest(
            method="POST",
            url="/api/executions/test-id/edits",
            route_params={"execution_id": "test-id"},
            body=body.encode(),
            headers={"Content-Type": "application/json"},
        )
        import asyncio

        from function_app import record_edits

        resp = asyncio.get_event_loop().run_until_complete(record_edits(req))
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["edits_count"] == 1

    def test_returns_400_for_invalid_json(self):
        req = func.HttpRequest(
            method="POST",
            url="/api/executions/test-id/edits",
            route_params={"execution_id": "test-id"},
            body=b"not json",
        )
        import asyncio

        from function_app import record_edits

        resp = asyncio.get_event_loop().run_until_complete(record_edits(req))
        assert resp.status_code == 400
