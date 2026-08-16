"""MCP 的工作区文件引用解析。"""

from __future__ import annotations

import re
import uuid
from typing import Any

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.core.exceptions import NotFoundError, ValidationError

_WORKSPACE_FILE_REF_RE = re.compile(r"^file://([0-9a-fA-F-]{36})$")
_REFERENCE_IDENTIFIER_KEYS = frozenset(
    {
        "file_id",
        "file_ids",
        "path",
        "paths",
        "directory",
        "workspace_path",
        "source_path",
        "target_path",
    }
)
_MAX_WORKSPACE_TEXT_BYTES = 5 * 1024 * 1024


async def resolve_workspace_file_refs(
    arguments: dict[str, Any],
    *,
    user_id: str | None,
    context: ToolInvocationContext | None,
) -> dict[str, Any]:
    """递归解析 MCP 参数中的 ``file://UUID`` 文本引用。

    ``file_id``、路径等控制字段保留为引用原值，避免破坏本身就消费标识符的工具。
    只有内容参数中的精确 ``file://UUID`` 才替换为文本，且必须携带与用户一致的
    受控调用上下文。
    """
    async def resolve_value(value: Any, *, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {
                item_key: await resolve_value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [await resolve_value(item, key=key) for item in value]
        if not isinstance(value, str) or key in _REFERENCE_IDENTIFIER_KEYS:
            return value

        match = _WORKSPACE_FILE_REF_RE.fullmatch(value.strip())
        if not match:
            return value
        return await _read_workspace_text(
            file_id=match.group(1), user_id=user_id, context=context
        )

    resolved = await resolve_value(arguments)
    return resolved if isinstance(resolved, dict) else dict(arguments)


async def _read_workspace_text(
    *,
    file_id: str,
    user_id: str | None,
    context: ToolInvocationContext | None,
) -> str:
    if context is None or not user_id:
        raise ValidationError("工作区文件引用需要受控的当前用户请求上下文")
    if str(context.user_id) != str(user_id):
        raise ValidationError("工作区文件引用的用户上下文不一致")
    try:
        user_uuid = uuid.UUID(str(user_id))
        file_uuid = uuid.UUID(file_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"非法工作区文件引用: file://{file_id}") from exc

    from omichub.application.services.file_service import FileService

    service = FileService(context.db)
    try:
        return await service.read_file_text(user_uuid, file_uuid, _MAX_WORKSPACE_TEXT_BYTES)
    except NotFoundError as exc:
        raise ValidationError("工作区文件不存在、已移除或无权访问") from exc
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"读取工作区文件失败: {exc}") from exc


__all__ = ["resolve_workspace_file_refs"]
