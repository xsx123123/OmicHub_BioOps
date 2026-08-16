"""OmicHub 工具执行桥 —— 把 LLM 的 tool_call 分发到具体工具实现。

核心职责：
1. 从 tools_schema.yaml 发现工具并校验参数；
2. 按 invocation_mode 进程内调用 service/shim，禁止 HTTP 自调用；
3. 输出双通道结果：llm_payload（精简摘要，回灌 LLM）+ ui_payload（完整图/表，给前端）。
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
from pathlib import Path
from typing import Any

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.core.exceptions import ValidationError
from omichub.infrastructure.mcp.workspace_file_refs import resolve_workspace_file_refs
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from omichub.tools.schema_loader import ToolSchema, ToolsSchemaLoader, schema_loader

_UPLOAD_REF_RE = re.compile(r"^upload://(.+)$")


class ToolBridgeService:
    """工具执行桥。"""

    # 安全上限
    _MAX_STRING_LEN = 100_000
    _MAX_TEXT_LINES = 5_000
    _MAX_LLM_PAYLOAD_BYTES = 3_000
    _MAX_UPLOAD_FILE_BYTES = 5 * 1024 * 1024  # 5MB

    def __init__(
        self,
        loader: ToolsSchemaLoader | None = None,
        backend=None,
    ) -> None:
        self._loader = loader or schema_loader
        self._factory = get_path_factory()
        self._backend = backend or get_storage_backend()

    async def execute(
        self,
        user_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolInvocationContext | None = None,
    ) -> dict[str, Any]:
        """执行工具调用，返回统一格式。"""
        schema = self._loader.get_tool(tool_name)
        if schema is None:
            return self._error(f"未知工具: {tool_name}")

        # analysis_flow 模式：强制需要 ToolInvocationContext
        if schema.invocation_mode == "analysis_flow":
            if context is None:
                return self._error("analysis_flow 工具需要 ToolInvocationContext")
            return await self._execute_analysis_flow(context, schema, arguments)

        try:
            args = self._validate_and_sanitize(schema, arguments)
            args = await self._resolve_upload_refs(user_id, args, context)
        except ValidationError as e:
            return self._error(str(e))

        # 二次确认占位：Phase 1 先返回提示，由前端/LLM 交互确认
        if schema.requires_confirm and not arguments.get("_confirmed"):
            return {
                "success": True,
                "is_error": False,
                "llm_payload": {
                    "needs_confirm": True,
                    "tool_name": tool_name,
                    "summary": "该操作会提交计算任务，请用户确认后再执行。",
                    "preview_args": self._safe_preview(args),
                },
                "ui_payload": {
                    "confirm_card": True,
                    "tool_name": tool_name,
                    "args": self._safe_preview(args),
                },
            }

        try:
            raw = await self._dispatch(user_id, schema, args, context)
        except Exception as e:  # noqa: BLE001
            return self._error(str(e))

        return self._package(schema, raw)

    def _validate_and_sanitize(
        self, schema: ToolSchema, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """基础校验：必填、字符串长度/行数、枚举白名单。"""
        props = schema.input_schema.get("properties", {})
        required = set(schema.input_schema.get("required", []))

        for key in required:
            if key not in arguments or arguments[key] is None or arguments[key] == "":
                raise ValidationError(f"缺少必填参数: {key}")

        sanitized: dict[str, Any] = {}
        for key, value in arguments.items():
            if key not in props:
                continue
            prop = props[key]
            expected_type = prop.get("type")

            if expected_type == "string" and isinstance(value, str):
                if len(value) > self._MAX_STRING_LEN:
                    raise ValidationError(f"参数 {key} 超过最大长度 {self._MAX_STRING_LEN}")
                if value.count("\n") > self._MAX_TEXT_LINES:
                    raise ValidationError(f"参数 {key} 超过最大行数 {self._MAX_TEXT_LINES}")
                sanitized[key] = value
            elif expected_type == "number" and isinstance(value, (int, float)) or expected_type == "integer" and isinstance(value, int) or expected_type == "boolean" and isinstance(value, bool) or expected_type == "array" and isinstance(value, list) or expected_type == "object" and isinstance(value, dict):
                sanitized[key] = value
            else:
                # 尝试简单转换
                sanitized[key] = value

        # 枚举校验
        for key, value in sanitized.items():
            enum_values = props.get(key, {}).get("enum")
            if enum_values is not None and value not in enum_values:
                raise ValidationError(f"参数 {key} 必须是 {enum_values} 之一")

        return sanitized

    async def _resolve_upload_refs(
        self,
        user_id: str,
        args: dict[str, Any],
        context: ToolInvocationContext | None = None,
    ) -> dict[str, Any]:
        """把聊天上传和工作区文件引用解析为文本内容。"""
        resolved: dict[str, Any] = dict(args)
        for key, value in resolved.items():
            if not isinstance(value, str):
                continue
            match = _UPLOAD_REF_RE.match(value.strip())
            if match:
                file_id = match.group(1).strip()
                content = await self._read_chat_upload(user_id, file_id)
                if content is None:
                    raise ValidationError(f"无法读取上传文件: {file_id}")
            else:
                continue
            if len(content.encode("utf-8")) > self._MAX_UPLOAD_FILE_BYTES:
                raise ValidationError(
                    f"引用文件超过 {self._MAX_UPLOAD_FILE_BYTES} 字节，无法直接作为工具输入"
                )
            resolved[key] = content
        return await resolve_workspace_file_refs(
            resolved, user_id=user_id, context=context
        )

    async def _read_chat_upload(self, user_id: str, file_id: str) -> str | None:
        """从聊天上传目录读取文件内容。"""
        upload_dir = self._factory.chat_uploads_dir(user_id)
        upload_rel = self._factory.relative_to_root(upload_dir)
        entries = await self._backend.list(upload_rel, recursive=False)
        candidates = [
            e for e in entries if e["type"] == "file" and e["name"].startswith(file_id)
        ]
        if not candidates:
            return None
        # 优先匹配完全相等或带常见文本扩展名
        candidates.sort(key=lambda e: (len(Path(e["name"]).suffix), e["name"]))
        target_name = candidates[0]["name"]
        target_abs = upload_dir / target_name
        try:
            # 安全校验：确保文件在 upload_dir 内
            target_abs.resolve().relative_to(upload_dir.resolve())
        except ValueError:
            return None
        try:
            content = await self._backend.read(self._factory.relative_to_root(target_abs))
            return content.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    async def _dispatch(
        self,
        user_id: str,
        schema: ToolSchema,
        args: dict[str, Any],
        context: ToolInvocationContext | None = None,
    ) -> dict[str, Any]:
        """按 invocation_mode 分发执行。"""
        mode = schema.invocation_mode
        if mode == "backend_sync":
            return await self._run_service_sync(user_id, schema, args, context)
        if mode == "backend_shim":
            return await self._run_shim(user_id, schema, args)
        if mode == "backend_async":
            return await self._submit_async_arq(user_id, schema.name, schema, args)
        if mode == "open_page":
            return self._open_page_payload(schema, args)
        if mode == "analysis_flow":
            raise RuntimeError("analysis_flow 应在 execute 顶层处理，不应进入 _dispatch")
        raise RuntimeError(f"不支持的 invocation_mode: {mode}")

    async def _execute_analysis_flow(
        self,
        context: ToolInvocationContext,
        schema: ToolSchema,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 analysis_flow 模式工具调用。"""
        from omichub.application.services.analysis_flow_tool_service import (
            AnalysisFlowToolService,
        )

        service = AnalysisFlowToolService(context=context)
        flow_id = schema.extra.get("flow_id") if schema.extra else None
        if not flow_id:
            return self._error("analysis_flow schema 缺少 flow_id")

        try:
            if schema.extra and schema.extra.get("tool_role") == "status":
                task_id = arguments.get("task_id", "")
                result = await service.get_task_status(task_id)
            elif schema.extra and schema.extra.get("tool_role") == "summary":
                task_id = arguments.get("task_id", "")
                result = await service.get_task_summary(task_id)
            else:
                result = await service.prepare(flow_id, arguments)
        except Exception as e:  # noqa: BLE001
            return self._error(str(e))

        return self._package_analysis_flow_result(result)

    def _package_analysis_flow_result(self, raw: dict[str, Any]) -> dict[str, Any]:
        """打包 analysis_flow 结果为双通道格式。"""
        if raw.get("valid") is False:
            return {
                "success": True,
                "is_error": False,
                "llm_payload": {
                    "valid": False,
                    "errors": raw.get("errors", []),
                    "warnings": raw.get("warnings", []),
                    "summary": "参数校验未通过，请根据错误信息补充或修正。",
                },
                "ui_payload": {
                    "type": "error_card",
                    "errors": raw.get("errors", []),
                    "warnings": raw.get("warnings", []),
                },
            }

        if "task_id" in raw:
            # confirm_and_submit 或查询结果
            return {
                "success": True,
                "is_error": False,
                "llm_payload": {
                    "task_id": raw.get("task_id"),
                    "status": raw.get("status"),
                    "task_url": raw.get("task_url"),
                    "summary": f"任务已提交，ID: {raw.get('task_id')}",
                },
                "ui_payload": raw.get("task_card") or {"type": "task_card", **raw},
            }

        # prepare 成功返回确认预览
        return {
            "success": True,
            "is_error": False,
            "llm_payload": {
                "valid": True,
                "confirmation_id": raw.get("confirmation_id"),
                "flow_id": raw.get("flow_id"),
                "flow_name": raw.get("flow_name"),
                "sample_count": raw.get("sample_count"),
                "comparison_count": raw.get("comparison_count"),
                "resource_hint": raw.get("resource_hint"),
                "parameter_preview": raw.get("parameter_preview"),
                "expires_at": raw.get("expires_at"),
                "summary": (
                    f"已为您预检 '{raw.get('flow_name')}' 流程，"
                    f"样本数 {raw.get('sample_count')}，比较组数 {raw.get('comparison_count')}。"
                    "请用户在确认卡上确认后正式提交。"
                ),
            },
            "ui_payload": {
                "type": "confirmation_card",
                **raw,
                "actions": {
                    "approve": {
                        "method": "POST",
                        "url": f"/api/v1/ai/tool-confirmations/{raw.get('confirmation_id')}/approve",
                    },
                    "reject": {
                        "method": "POST",
                        "url": f"/api/v1/ai/tool-confirmations/{raw.get('confirmation_id')}/reject",
                    },
                },
            },
        }

    async def _submit_async_arq(
        self, user_id: str, tool_name: str, schema: ToolSchema, args: dict[str, Any]
    ) -> dict[str, Any]:
        """投递 ARQ 异步任务，立即返回 task_id。"""
        from omichub.infrastructure.task_queue.arq_jobs import run_tool_async
        from omichub.infrastructure.task_queue.arq_pool import get_arq_pool

        try:
            pool = await get_arq_pool()
            job = await pool.enqueue_job(
                run_tool_async.__name__,
                tool_name,
                user_id,
                **args,
            )
            if job is None:
                return {
                    "success": False,
                    "is_error": True,
                    "error": "ARQ 入队失败，未返回任务对象",
                }
            task_id = job.job_id
            return {
                "success": True,
                "task_id": task_id,
                "status": "PENDING",
                "message": "任务已投递，可在任务中心查看进度。",
                "progress_url": f"/api/v1/tasks/{task_id}/progress",
                "result_url": f"/api/v1/tasks/{task_id}/status",
            }
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "is_error": True,
                "error": f"ARQ 投递失败: {e}",
            }

    async def _run_service_sync(
        self,
        user_id: str,
        schema: ToolSchema,
        args: dict[str, Any],
        context: ToolInvocationContext | None = None,
    ) -> dict[str, Any]:
        """反射实例化 service 并调用方法。"""
        if not schema.service or not schema.method:
            raise RuntimeError("backend_sync 工具必须配置 service 和 method")

        module_path, class_name = schema.service.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        # Phase 1：service 统一无参构造（EnrichmentService 等均为可选依赖注入）。
        # 后续若 service 需要 db，可在此按约定从 AsyncSession 构造。
        instance = cls() if inspect.isclass(cls) else cls

        method = getattr(instance, schema.method)
        kwargs = {"user_id": user_id, **args}
        if context is not None and "context" in inspect.signature(method).parameters:
            kwargs["context"] = context
        result = await method(**kwargs)

        if hasattr(result, "model_dump"):
            return {"success": True, **result.model_dump()}
        if isinstance(result, dict):
            return {"success": True, **result}
        return {"success": True, "result": result}

    async def _run_shim(
        self, user_id: str, schema: ToolSchema, args: dict[str, Any]
    ) -> dict[str, Any]:
        """动态导入 shim 模块并执行。"""
        if not schema.shim_module:
            raise RuntimeError("backend_shim 工具必须配置 shim_module")
        module = importlib.import_module(schema.shim_module)
        func = getattr(module, "execute", None)
        if func is None:
            raise RuntimeError(f"shim 模块 {schema.shim_module} 缺少 execute 函数")
        result = await func(user_id=user_id, **args)
        if hasattr(result, "model_dump"):
            return {"success": True, **result.model_dump()}
        if isinstance(result, dict):
            return {"success": True, **result}
        return {"success": True, "result": result}

    def _open_page_payload(self, schema: ToolSchema, args: dict[str, Any]) -> dict[str, Any]:
        """返回前端路由引导。"""
        return {
            "success": True,
            "message": f"请在工具页完成操作：{schema.route}",
            "route": schema.route,
            "arguments": args,
        }

    def _package(self, schema: ToolSchema, raw: dict[str, Any]) -> dict[str, Any]:
        """把原始结果按字段白名单打包为 llm_payload / ui_payload。"""
        success = bool(raw.get("success", True))
        is_error = bool(raw.get("is_error", not success))

        llm_payload = self._pick(raw, schema.llm_result_fields)
        ui_payload = self._pick(raw, schema.ui_result_fields)

        # 保证 llm_payload 不超过 3KB
        llm_json = json.dumps(llm_payload, ensure_ascii=False, default=str)
        if len(llm_json.encode("utf-8")) > self._MAX_LLM_PAYLOAD_BYTES:
            llm_payload = {
                "summary": "工具执行结果较大，已省略细节。",
                "success": success,
            }

        return {
            "success": success,
            "is_error": is_error,
            "llm_payload": llm_payload,
            "ui_payload": ui_payload,
        }

    @staticmethod
    def _pick(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        """按字段白名单提取。"""
        result: dict[str, Any] = {}
        for field in fields:
            if field in data:
                result[field] = data[field]
        return result

    @staticmethod
    def _safe_preview(args: dict[str, Any]) -> dict[str, Any]:
        """生成安全的参数预览，截断长字符串。"""
        preview: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 200:
                preview[key] = value[:200] + "..."
            else:
                preview[key] = value
        return preview

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {
            "success": False,
            "is_error": True,
            "llm_payload": {"success": False, "error": message},
            "ui_payload": {"error": message},
        }


# 便捷函数：供 presets.py 直接调用
_bridge_service: ToolBridgeService | None = None


def get_tool_bridge_service() -> ToolBridgeService:
    """全局单例。"""
    global _bridge_service
    if _bridge_service is None:
        _bridge_service = ToolBridgeService()
    return _bridge_service
