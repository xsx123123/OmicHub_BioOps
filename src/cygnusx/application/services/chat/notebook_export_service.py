"""WP3-Task2：会话历史 → 只读确定性 ``.ipynb`` 导出（纯投影）。

数据全部来自既有落库（chat_messages.metadata_json.tool_invocations 的
arguments.code / ui_payload / language / cell_index + 消息顺序），不新建
业务存储、不回放事件流、不触碰沙盒。导出语义借鉴 OpenAI4S
``server/notebook_export.py``（确定性编码 / 语言元数据映射 / 安全文件名），
不移植其代码：

- 确定性：无时间戳字段；cell id 由内容 hash 生成；同一历史导出两次字节一致
  （``json.dumps(sort_keys=True, indent=1) + "\\n"`` 编码）。
- 截断条目（WP0 护栏的 ``_cygnusx_payload_truncated`` 标记或信封截断元信息）
  导出为带说明的 markdown cell + cell 元数据标记，不静默丢弃。
- 富输出（plotly 图表、产物清单）尽力文本化为 stream 输出，同时保留在
  cell 元数据中，无法映射的部分以文本化注释呈现。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.chat.dto_support import ChatDtoSupport
from cygnusx.application.services.chat.utils import CODE_EXECUTION_TOOL_NAMES
from cygnusx.infrastructure.database.models.chat import (
    ChatMessageModel,
    ChatSessionModel,
)

_NBFORMAT = 4
_NBFORMAT_MINOR = 5
_TRUNCATED_MARKER = "_cygnusx_payload_truncated"

#: kernelspec/language_info 映射（OpenAI4S 契约：python → python3）
_LANGUAGE_SPECS: dict[str, dict[str, str]] = {
    "python": {
        "display_name": "Python 3 (CygnusX export)",
        "name": "python3",
        "language": "python",
        "mimetype": "text/x-python",
        "file_extension": ".py",
    },
    "r": {
        "display_name": "R (CygnusX export)",
        "name": "ir",
        "language": "R",
        "mimetype": "text/x-r-source",
        "file_extension": ".r",
    },
}
_DEFAULT_LANGUAGE_SPEC: dict[str, str] = {
    "display_name": "CygnusX export",
    "name": "python3",
    "language": "python",
    "mimetype": "text/x-python",
    "file_extension": ".py",
}


class ChatNotebookExportService:
    """把会话落库历史投影为 canonical Jupyter 文档（只读）。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def export_session(self, session: ChatSessionModel) -> dict[str, Any]:
        """导出会话为 notebook 字节与 HTTP 描述符。

        调用方须已完成会话归属复核（与 get_messages 同款）。
        """
        result = await self._db.execute(
            select(ChatMessageModel).where(ChatMessageModel.session_id == session.session_id)
        )
        messages = ChatDtoSupport._order_messages(list(result.scalars().all()))
        notebook = build_notebook(messages)
        data = _encode(notebook)
        return {
            "filename": f"{_safe_stem(session.title) or _safe_stem(session.session_id)}.ipynb",
            "content_type": "application/x-ipynb+json",
            "data": data,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }


def build_notebook(messages: list[Any]) -> dict[str, Any]:
    """纯函数：消息列表 → nbformat 4.x notebook dict（确定性）。"""
    cells: list[dict[str, Any]] = []
    session_language: str | None = None
    code_ordinal = 0  # 无 cell_index 的旧信封按代码 cell 顺序补编号（1 起）

    for message in messages:
        metadata = message.metadata_json if isinstance(message.metadata_json, dict) else {}
        invocations = metadata.get("tool_invocations")
        if isinstance(invocations, list):
            for invocation in invocations:
                if not isinstance(invocation, dict):
                    continue
                tool_name = str(invocation.get("tool_name") or "")
                if tool_name not in CODE_EXECUTION_TOOL_NAMES:
                    continue
                cells.extend(_invocation_to_cells(invocation, message, code_ordinal))
                code_ordinal += 1
        # 文本投影为 markdown cell：同一条消息内位于其代码 cell 之后
        # （与该消息的实际过程序一致：工具执行 → 模型总结），跨消息按会话顺序交错
        content = str(message.content or "").strip()
        if content:
            cells.append(_markdown_cell(content, message))

    for cell in cells:
        if cell["cell_type"] != "code":
            continue
        language = (cell.get("metadata") or {}).get("cygnusx", {}).get("language")
        if language:
            session_language = str(language).lower()
            break
    spec = _LANGUAGE_SPECS.get(session_language or "", _DEFAULT_LANGUAGE_SPEC)

    notebook: dict[str, Any] = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": spec["display_name"],
                "language": spec["language"],
                "name": spec["name"],
            },
            "language_info": {
                "name": spec["language"],
                "mimetype": spec["mimetype"],
                "file_extension": spec["file_extension"],
            },
            "cygnusx": {
                "history_is_read_only": True,
                "cell_count": len(cells),
            },
        },
        "nbformat": _NBFORMAT,
        "nbformat_minor": _NBFORMAT_MINOR,
    }
    # 平台注释用内容自身的确定性 hash（不含本字段，避免自引用）
    notebook["metadata"]["cygnusx"]["content_sha256"] = hashlib.sha256(
        _encode(notebook)
    ).hexdigest()
    return notebook


def _invocation_to_cells(
    invocation: dict[str, Any], message: Any, ordinal: int
) -> list[dict[str, Any]]:
    """单个代码执行类工具调用 → [可选截断说明 markdown] + code cell。"""
    raw_arguments = invocation.get("arguments")
    arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
    raw_ui_payload = invocation.get("ui_payload")
    ui_payload: dict[str, Any] = raw_ui_payload if isinstance(raw_ui_payload, dict) else {}
    raw_result = invocation.get("result")
    result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}

    truncation_notes = _truncation_notes(invocation)
    cells: list[dict[str, Any]] = []
    if truncation_notes:
        note_lines = [
            "> ⚠️ **该 cell 的落库内容已被 WP0 护栏截断**（不静默丢弃，按截断说明导出）",
            "",
        ]
        note_lines.extend(f"> - {note}" for note in truncation_notes)
        cells.append(_markdown_cell("\n".join(note_lines), message))

    language = invocation.get("language") or ui_payload.get("language") or "python"
    cell_index = invocation.get("cell_index")
    if isinstance(cell_index, int) and not isinstance(cell_index, bool):
        execution_count = cell_index + 1
    else:
        # 旧信封无 cell_index：按代码 cell 出现顺序补 1 起编号
        execution_count = ordinal + 1

    source = str(arguments.get("code") or "")
    code_cell: dict[str, Any] = {
        "cell_type": "code",
        "execution_count": execution_count,
        "id": _cell_id(source, str(message.message_id), execution_count),
        "metadata": {
            "cygnusx": {
                "tool_name": str(invocation.get("tool_name") or ""),
                "tool_call_id": str(invocation.get("tool_call_id") or ""),
                "cell_index": cell_index if isinstance(cell_index, int) else None,
                "language": str(language),
                "success": bool(invocation.get("success")),
                "mcp_server": invocation.get("mcp_server"),
                "payload_truncated": bool(truncation_notes),
                "history_is_read_only": True,
            }
        },
        "outputs": _rebuild_outputs(ui_payload, result, truncation_notes),
        "source": _lines(source),
    }
    cells.append(code_cell)
    return cells


def _rebuild_outputs(
    ui_payload: dict[str, Any],
    result: dict[str, Any],
    truncation_notes: list[str],
) -> list[dict[str, Any]]:
    """从 ui_payload（缺失时回退 result）重建 outputs。

    文本输出走 stream；error 走 error output；plotly 图表与产物清单尽力
    文本化为 stream 行，原始结构保留在 cell 元数据由前端/读者参考。
    """
    payload = ui_payload or result or {}
    outputs: list[dict[str, Any]] = []
    for name in ("stdout", "stderr"):
        text = str(payload.get(name) or "")
        if text:
            outputs.append({"name": name, "output_type": "stream", "text": _lines(text)})
    if payload.get("_cygnusx_payload_truncated") and not any(
        output.get("name") == "stderr" for output in outputs
    ):
        outputs.append(
            {
                "name": "stderr",
                "output_type": "stream",
                "text": ["[cygnusx] 该输出在落库时被截断，完整结果见沙盒产物或归档文件\n"],
            }
        )
    error = payload.get("error")
    if error:
        error_text = str(error)
        headline = next((line for line in error_text.splitlines() if line.strip()), error_text)
        outputs.append(
            {
                "ename": "SandboxExecutionError" if payload.get("timed_out") else "SandboxError",
                "evalue": headline[:1000],
                "output_type": "error",
                "traceback": _lines(error_text),
            }
        )
    plotly_figures = payload.get("plotly_figures")
    if isinstance(plotly_figures, list) and plotly_figures:
        outputs.append(
            {
                "name": "stdout",
                "output_type": "stream",
                "text": [
                    "[cygnusx] 该 cell 产出了 "
                    f"{len(plotly_figures)} 个 plotly 交互图表（已内联预览，"
                    "导出为只读文本说明，原始数据见落库 ui_payload.plotly_figures）\n"
                ],
            }
        )
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        names = [str(item.get("path") if isinstance(item, dict) else item) for item in artifacts]
        outputs.append(
            {
                "name": "stdout",
                "output_type": "stream",
                "text": ["[cygnusx] 产物: " + ", ".join(names) + "\n"],
            }
        )
    if truncation_notes:
        outputs.append(
            {
                "name": "stderr",
                "output_type": "stream",
                "text": ["[cygnusx] 截断说明: " + "；".join(truncation_notes) + "\n"],
            }
        )
    return outputs


def _truncation_notes(invocation: dict[str, Any]) -> list[str]:
    """收集截断说明（WP0 标记 + 信封截断元信息），无截断返回空列表。"""
    notes: list[str] = []
    for key in ("result_truncation", "ui_payload_truncation"):
        meta = invocation.get(key)
        if isinstance(meta, dict) and meta.get("payload_truncated"):
            note = str(meta.get("truncation_note") or "").strip()
            if note:
                notes.append(note)
            original_bytes = meta.get("original_bytes")
            if original_bytes is not None:
                with contextlib.suppress(TypeError, ValueError):
                    notes.append(f"原始大小 {int(original_bytes)} 字节")
    for payload_key in ("result", "ui_payload"):
        payload = invocation.get(payload_key)
        if isinstance(payload, dict) and payload.get(_TRUNCATED_MARKER):
            note = f"{payload_key} 落库载荷被截断标记替换"
            if note not in notes:
                notes.append(note)
    return notes


def _markdown_cell(source: str, message: Any) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "id": _cell_id(source, str(message.message_id), 0),
        "metadata": {
            "cygnusx": {
                "message_id": str(message.message_id),
                "role": str(message.role),
                "history_is_read_only": True,
            }
        },
        "source": _lines(source),
    }


def _cell_id(*parts: Any) -> str:
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"cell-{digest[:12]}"


def _lines(value: str) -> list[str]:
    if not value:
        return []
    return value.splitlines(keepends=True)


def _encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def _safe_stem(value: str) -> str:
    stem = "".join(
        character for character in str(value or "") if character.isalnum() or character in "-_"
    )
    return stem[:120]


__all__ = ["ChatNotebookExportService", "build_notebook"]
