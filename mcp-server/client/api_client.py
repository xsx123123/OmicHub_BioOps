"""CygnusX 平台 REST API 客户端"""

from __future__ import annotations

from typing import Any

import httpx
from core.config import settings


class CygnusXAPIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class CygnusXAPIClient:
    """通过 HTTP 调用 CygnusX 平台 REST API，使用 API Key 认证。"""

    def __init__(self) -> None:
        self._base_url = f"{settings.base_url.rstrip('/')}/api/v1"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=settings.request_timeout,
            headers={"X-API-Key": settings.api_key},
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise CygnusXAPIError(0, f"无法连接到平台: {settings.base_url} ({e})") from e
        except httpx.TimeoutException as e:
            raise CygnusXAPIError(0, f"请求超时 ({settings.request_timeout}s)") from e

        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise CygnusXAPIError(resp.status_code, str(detail))

        if resp.status_code == 204:
            return None
        # 平台部分端点（如 /reports/{id}/preview）返回 PlainText HTML，
        # 不能无条件 resp.json()，否则抛未捕获的 JSONDecodeError。
        content_type = (resp.headers.get("content-type") or "").lower()
        if "json" in content_type:
            return resp.json()
        return resp.text

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    # ===== Tasks =====
    async def list_tasks(self, status: str | None = None) -> dict:
        params = {}
        if status:
            params["status"] = status
        return await self.get("/tasks", params=params)

    async def get_task(self, task_id: str) -> dict:
        return await self.get(f"/tasks/{task_id}")

    async def cancel_task(self, task_id: str) -> dict:
        return await self.post(f"/tasks/{task_id}/cancel")

    async def get_task_dag(self, task_id: str) -> dict:
        return await self.get(f"/tasks/{task_id}/dag")

    # ===== Flows =====
    async def list_flows(self, category: str | None = None) -> dict:
        params = {}
        if category:
            params["category"] = category
        return await self.get("/flows", params=params)

    async def get_flow(self, flow_id: str) -> dict:
        return await self.get(f"/flows/{flow_id}")

    async def get_flow_schema(self, flow_id: str) -> dict:
        return await self.get(f"/flows/{flow_id}/schema")

    # ===== Analysis =====
    async def submit_task(self, payload: dict) -> dict:
        return await self.post("/tasks", json=payload)

    # ===== Pipelines =====
    async def list_available_pipelines(self) -> list[dict[str, Any]]:
        return await self.get("/pipelines")

    async def check_workspace_data(self, analysis_type: str, data_path: str) -> dict:
        return await self.post(
            "/pipelines/check-workspace",
            json={"analysis_type": analysis_type, "data_path": data_path},
        )

    async def prepare_pipeline(self, pipeline_type: str, payload: dict[str, Any]) -> dict:
        return await self.post(f"/pipelines/{pipeline_type}/prepare", json=payload)

    async def submit_pipeline(self, pipeline_type: str, prepared_params: dict[str, Any]) -> dict:
        # 确认门在 MCP 工具层（user_confirmed=True 才会走到这里），
        # 平台侧据此字段放行提交。
        return await self.post(
            f"/pipelines/{pipeline_type}/submit",
            json={"prepared_params": prepared_params, "user_confirmed": True},
        )

    async def get_pipeline_status(self, pipeline_type: str, task_id: str) -> dict:
        return await self.get(f"/pipelines/{pipeline_type}/{task_id}/status")

    async def get_pipeline_results(
        self, pipeline_type: str, task_id: str, result_types: list[str]
    ) -> dict:
        return await self.post(
            f"/pipelines/{pipeline_type}/{task_id}/results",
            json={"result_types": result_types},
        )

    # ===== Downloads =====
    async def list_downloads(self) -> dict:
        return await self.get("/downloads")

    async def submit_download(self, payload: dict) -> dict:
        return await self.post("/downloads", json=payload)

    async def get_download_progress(self, task_id: str) -> dict:
        return await self.get(f"/downloads/{task_id}/progress")

    # ===== Files =====
    async def list_files(self, directory: str | None = None) -> dict:
        params = {}
        if directory:
            params["directory"] = directory
        return await self.get("/files", params=params)

    async def get_file_tree(self) -> dict:
        return await self.get("/files/tree")

    async def list_directories(self) -> list:
        return await self.get("/files/directories")

    async def get_quota(self) -> dict:
        return await self.get("/files/quota")

    async def preview_file(self, path: str, max_lines: int = 50) -> dict:
        return await self.get("/files/preview", params={"path": path, "max_lines": max_lines})

    async def list_workspace_files(
        self, path: str | None = None, pattern: str | None = None
    ) -> dict:
        params = {key: value for key, value in {"path": path, "pattern": pattern}.items() if value}
        return await self.get("/files/workspace", params=params)

    async def search_workspace_files(self, query: str, limit: int = 50) -> dict:
        return await self.get(
            "/files/search", params={"q": query, "root": "", "limit": limit}
        )

    # ===== Reports =====
    async def list_reports(self, **filters: Any) -> dict:
        params = {k: v for k, v in filters.items() if v is not None}
        return await self.get("/reports", params=params)

    async def get_report(self, report_id: str) -> dict:
        return await self.get(f"/reports/{report_id}")

    async def get_report_content(self, report_id: str) -> str:
        return await self.get(f"/reports/{report_id}/preview")

    # ===== Sandbox =====
    async def sandbox_list_sessions(self) -> list:
        return await self.get("/sandbox/sessions")

    async def sandbox_create_session(self, language: str = "python") -> dict:
        return await self.post("/sandbox/sessions", json={"language": language})

    async def sandbox_execute(self, session_id: str, code: str, timeout: int = 300) -> dict:
        return await self.post(
            f"/sandbox/sessions/{session_id}/execute",
            json={"code": code, "timeout": timeout},
        )

    async def sandbox_delete_session(self, session_id: str) -> dict:
        return await self.delete(f"/sandbox/sessions/{session_id}")

    # ===== User / Platform =====
    async def get_me(self) -> dict:
        return await self.get("/auth/me")


api = CygnusXAPIClient()
