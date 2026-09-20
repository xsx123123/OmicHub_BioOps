"""聊天 Runtime 共用的文件、附件、额度、技能和搜索支撑。"""

from __future__ import annotations

import ipaddress
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx
from loguru import logger
from sqlalchemy import select

from cygnusx.application.services.overdrive_planning_service import build_research_queries
from cygnusx.application.services.research_search_optimizer import ResearchSearchOptimizer
from cygnusx.application.services.search_provider_service import SearchProviderService
from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter, get_tracer
from cygnusx.domain.skill.services import SKILL_RESOURCE_TOOL_NAME, USE_SKILL_TOOL_NAME
from cygnusx.infrastructure.ai_provider.openai_compatible import provider_manager
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel
from cygnusx.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel

_chat_meter = get_meter("cygnusx.chat")
_skill_count = _chat_meter.create_counter("skill.execute.count", description="技能工具执行次数")
_skill_duration = _chat_meter.create_histogram(
    "skill.execute.duration", unit="ms", description="技能工具执行耗时"
)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def extract_docx_text(source: Any) -> str:
    """从 docx（OOXML zip 容器）提取正文纯文本，仅依赖标准库。

    source 可以是本地路径（str/Path）或文件字节（bytes）。
    原理：读取 word/document.xml，把段落结尾/换行/制表符转成文本符号后剥掉其余 XML 标签。
    提取失败（非 zip、缺 document.xml 等）返回空串。
    """
    import io
    import re
    import zipfile
    from html import unescape

    try:
        if isinstance(source, bytes):
            zf_ctx = zipfile.ZipFile(io.BytesIO(source))
        else:
            zf_ctx = zipfile.ZipFile(str(source))
        with zf_ctx as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""
    xml = re.sub(r"<w:tab\b[^>]*/?>", "\t", xml)
    xml = re.sub(r"<w:br\b[^>]*/?>", "\n", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    text = unescape(re.sub(r"<[^>]+>", "", xml))
    # 收敛空行，避免注入大量空白
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_docx_attachment(mime_type: str, filename: str) -> bool:
    """按 MIME 或扩展名识别 docx 附件。"""
    return mime_type == _DOCX_MIME or Path(filename).suffix.lower() == ".docx"


class ChatRuntimeSupport:
    """供聊天 Runtime 复用的无状态能力混入。"""

    async def _link_session_files_to_workspace(
        self,
        session_id: str,
        user_id: str | None,
        attachment_dicts: list[dict[str, Any]],
    ) -> dict[str, str]:
        """把本轮和历史受控附件幂等引入当前 Session ``/workspace/input/``。

        返回 ``{规范化引用(upload://…、file://… 或 directory://…): 沙盒可读路径}``。
        沙盒内无法解析 file:// / upload:// 引用，只有挂载进工作区的平台软链才能被沙盒
        代码按文件系统路径直接读取；任一文件引入失败仅记录并跳过，不阻断对话。
        """
        if not user_id:
            return {}

        def _normalize_ref(file_id: str) -> str:
            fid = str(file_id or "").strip()
            if not fid:
                return ""
            return fid if "://" in fid else f"upload://{fid}"

        refs: list[str] = [_normalize_ref(att.get("file_id")) for att in attachment_dicts]

        # 历史轮次的上传同样需要挂载才能在沙盒读取（多轮分析场景）
        try:
            result = await self._db.execute(
                select(ChatMessageModel)
                .where(ChatMessageModel.session_id == session_id)
                .order_by(ChatMessageModel.created_at)
            )
            for msg in self._order_messages(result.scalars().all()):
                if msg.role != "user":
                    continue
                for att in (msg.metadata_json or {}).get("attachments") or []:
                    refs.append(_normalize_ref(att.get("file_id")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Studio 收集历史上传文件引用失败: {}", exc)

        refs = [ref for ref in refs if ref]
        if not refs:
            return {}

        from cygnusx.application.services.studio_context_service import link_session_workspace_refs

        try:
            paths, _manifests, errors = await link_session_workspace_refs(
                str(user_id), session_id, refs, self._db
            )
        except Exception as exc:  # noqa: BLE001 - 挂载失败不能打断对话，模型仍可走 datahub_import
            logger.warning("Studio 批量引入工作区文件失败: {}", exc)
            return {}
        if errors:
            logger.info(f"Session 工作区资源部分引入失败（{len(errors)} 项）: {errors}")
        return paths

    async def _collect_session_file_context(
        self,
        session_id: str,
        exclude_file_ids: set[str] | None = None,
        user_id: str | None = None,
        studio_sandbox_paths: dict[str, str] | None = None,
        studio_mode: bool = False,
    ) -> str:
        """汇总本会话历史消息中的附件引用，供后续轮次继承文件上下文。

        返回空串表示没有可继承的历史文件。附件元数据在消息落库时写入
        metadata_json.attachments，这里只做读取与去重。
        额外兜底：扫描该用户 chat-uploads 目录，按文件名内嵌的会话标记
        （``.s{session_id前8位}``）找回本会话上传过、但未进入消息元数据的文件。
        严格按会话隔离：其它会话的上传不注入，避免跨对话污染。
        ``studio_mode`` 决定未挂载文件的回退措辞：Studio 会话没有
        chat_sandbox_execute，不能再用"执行时自动注入沙盒"的说法。
        """
        exclude = exclude_file_ids or set()
        result = await self._db.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at)
        )
        lines: list[str] = []
        seen: set[str] = set()
        for msg in self._order_messages(result.scalars().all()):
            if msg.role != "user":
                continue
            for att in (msg.metadata_json or {}).get("attachments") or []:
                file_id = str(att.get("file_id") or "")
                if not file_id or file_id in seen or file_id in exclude:
                    continue
                seen.add(file_id)
                ref = file_id if "://" in file_id else f"upload://{file_id}"
                sandbox_path = (studio_sandbox_paths or {}).get(ref)
                if att.get("type") == "directory":
                    if sandbox_path:
                        lines.append(
                            f"- {att.get('name', '')}/（已只读引入工作区 {sandbox_path}；"
                            "请先用 workspace_list 分页列举，再按需读取文件）"
                        )
                    continue
                if sandbox_path:
                    lines.append(
                        f"- {att.get('name', '')}（已引入工作区 {sandbox_path}，"
                        "沙盒代码请直接按该路径读取，勿用 file:// / upload:// 引用）"
                    )
                else:
                    if studio_mode:
                        lines.append(
                            f"- {att.get('name', '')}（file_id: {ref}，未挂载进沙盒工作区；"
                            f'可用 workspace_read_file(file_id="{ref}") 在宿主侧读取内容，'
                            f"或调用 datahub_import 引入沙盒 /workspace/input/ 后按路径读取）"
                        )
                    else:
                        lines.append(
                            f"- {att.get('name', '')}（file_id: {ref}，"
                            f'可用 workspace_read_file(file_id="{ref}") 读取；'
                            f"chat_sandbox_execute 执行时会自动注入沙盒 /workspace/input/）"
                        )

        sections: list[str] = []
        if lines:
            sections.append(
                "[本会话中用户历史上传过的文件，可直接用 file_id 引用，无需重新搜索。"
                "仅当用户请求涉及这些文件时才使用；与当前请求无关时忽略，不要主动读取或提及]\n"
                + "\n".join(lines)
            )

        if user_id:
            recent_lines = self._collect_recent_upload_lines(
                user_id, seen | exclude, session_id=session_id
            )
            if recent_lines:
                sections.append(
                    "[本会话最近上传的文件，仅供备用：仅当用户请求与这些文件相关"
                    "或用户明确引用时才可使用；与当前请求无关时忽略，不要主动读取、检查或提及。"
                    "纯代码编写/概念问答类请求无需任何数据文件]\n" + "\n".join(recent_lines)
                )

        return "\n\n".join(sections)

    @staticmethod
    def _collect_recent_upload_lines(
        user_id: str, skip_file_ids: set[str], session_id: str = "", limit: int = 5
    ) -> list[str]:
        """扫描用户 chat-uploads 目录，返回本会话最近上传文件的引用行（按修改时间倒序）。

        聊天上传文件名内嵌会话标记（``.s{session_id前8位}``）；给了 session_id 时
        只保留带本会话标记的文件，其它会话的上传一律不注入（会话隔离）。
        """
        from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir

        upload_dir = get_user_chat_upload_dir(user_id)
        if not upload_dir.is_dir():
            return []
        session_marker = f".s{session_id[:8]}" if session_id else ""
        try:
            recent = sorted(
                (
                    p
                    for p in upload_dir.iterdir()
                    if p.is_file() and (not session_marker or session_marker in p.name)
                ),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []
        lines: list[str] = []
        for path in recent:
            fid = path.name.split(".", 1)[0]
            if not fid or fid in skip_file_ids:
                continue
            ref = f"upload://{fid}"
            lines.append(
                f'- {path.name}（file_id: {ref}，可用 workspace_read_file(file_id="{ref}") 读取）'
            )
            if len(lines) >= limit:
                break
        return lines

    @staticmethod
    def _append_context_to_last_user_message(
        messages: list[dict[str, Any]], context_text: str
    ) -> list[dict[str, Any]]:
        """把补充上下文追加到最后一条用户消息（仅影响送 LLM 的视图，不落库）。"""
        if not messages:
            return messages
        target_index = max(
            (i for i, m in enumerate(messages) if m.get("role") == "user"),
            default=-1,
        )
        if target_index == -1:
            return messages
        target = messages[target_index]
        content = target.get("content", "")
        new_messages = list(messages)
        if isinstance(content, list):
            new_messages[target_index] = {
                **target,
                "content": content + [{"type": "text", "text": f"\n\n{context_text}"}],
            }
        else:
            new_messages[target_index] = {
                **target,
                "content": f"{content}\n\n{context_text}",
            }
        return new_messages

    # --- 上下文压缩（256K 窗口保护） ---

    # 256K 上下文窗口预留输出/系统词/工具定义空间后的触发阈值
    _CONTEXT_COMPRESS_THRESHOLD_TOKENS = 200_000
    # 压缩时保留原文的最近消息条数
    _CONTEXT_KEEP_RECENT_MESSAGES = 10

    @staticmethod
    def _message_text(message: dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, list):
            return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return str(content)

    @classmethod
    def _estimate_messages_tokens(cls, messages: list[dict[str, Any]]) -> int:
        """粗略估算 token 数：中英混合按 2 字符 ≈ 1 token 的保守口径。"""
        return sum(len(cls._message_text(m)) // 2 + 4 for m in messages)

    async def _compress_context_if_needed(
        self,
        messages: list[dict[str, Any]],
        model_config: Any,
    ) -> tuple[list[dict[str, Any]], bool, int]:
        """估算 token 超过阈值时，把较早消息压缩为摘要，仅保留最近若干条原文。

        返回 (messages, 是否压缩, 压缩前估算 token)。摘要复用当前模型生成；
        摘要调用失败时降级为"保留首条 + 最近 N 条"的硬截断，保证请求可继续。
        """
        tokens = self._estimate_messages_tokens(messages)
        keep = self._CONTEXT_KEEP_RECENT_MESSAGES
        if tokens <= self._CONTEXT_COMPRESS_THRESHOLD_TOKENS or len(messages) <= keep + 2:
            return messages, False, tokens

        old, recent = messages[:-keep], messages[-keep:]
        digest_lines: list[str] = []
        for m in old:
            text = self._message_text(m)[:2000]
            if text.strip():
                digest_lines.append(f"[{m.get('role', '?')}] {text}")
        summary = ""
        try:
            from cygnusx.infrastructure.ai_provider.openai_compatible import provider_manager

            parts: list[str] = []
            async for chunk in provider_manager.chat_stream(
                config=model_config,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "请将以下对话历史压缩为一份结构化摘要，必须保留：用户的分析目标与需求、"
                            "关键数据文件引用（file_id / 文件名 / 路径）、已完成的分析步骤与结论、"
                            "生成的产物（图表/文件）、以及未完成的待办事项。\n\n"
                            + "\n\n".join(digest_lines)
                        ),
                    }
                ],
                system_prompt="你是对话压缩器，只输出摘要本身，不超过 1500 字。",
                max_tokens=2048,
            ):
                if chunk.type == "text":
                    parts.append(chunk.content)
            summary = "".join(parts).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"上下文压缩摘要生成失败，降级为硬截断: {e}")

        if summary:
            compressed = [
                {
                    "role": "system",
                    "content": ("[早期对话已压缩为摘要，后续请基于摘要与最近对话继续]\n" + summary),
                }
            ] + recent
            logger.info(
                f"上下文已压缩: 估算 {tokens} tokens，{len(old)} 条早期消息 → 摘要 + 最近 {len(recent)} 条"
            )
            return compressed, True, tokens

        # 降级：摘要失败时保留首条用户消息 + 最近 N 条
        fallback = [m for m in old[:1] if m.get("role") == "user"] + recent
        logger.info(f"上下文硬截断: 估算 {tokens} tokens，保留 {len(fallback)}/{len(messages)} 条")
        return fallback, True, tokens

    @staticmethod
    async def _build_multimodal_messages(
        messages: list[dict[str, Any]],
        attachments: list[Any],
        studio_sandbox_paths: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """把附件注入到最后一条用户消息中。

        兼容策略：
        - 只有文本/文件附件时，保持 content 为字符串（对 Qwen 等国产模型兼容性最好）。
        - 包含图片附件时，使用 OpenAI 多模态 list 格式。

        ``studio_sandbox_paths``：Studio 模式下文件引用 → 沙盒可读路径的映射；
        命中时提示模型直接用工作区路径读取（沙盒无法解析 file:// / upload:// 引用）。
        传 ``None`` 表示普通聊天（附件由 chat_sandbox_execute 执行前注入轻量沙盒）。
        """
        if not messages:
            return messages
        target_index = max(
            (i for i, m in enumerate(messages) if m.get("role") == "user"),
            default=-1,
        )
        if target_index == -1:
            return messages

        target = messages[target_index]
        base_text = str(target.get("content", ""))

        # attachments 可能是 Pydantic ChatAttachment 对象列表，统一转成 dict
        attachment_dicts: list[dict[str, Any]] = [
            att.model_dump() if hasattr(att, "model_dump") else dict(att)
            for att in (attachments or [])
        ]

        has_image = any(
            att.get("type") == "image" or (att.get("mime_type", "").startswith("image/"))
            for att in attachment_dicts
        )

        async def _build_snippets(att: dict[str, Any]) -> list[str]:
            """为单个附件生成文本提示片段。"""
            file_id = att.get("file_id", "")
            if att.get("type") == "directory":
                ref = file_id if "://" in file_id else ""
                sandbox_path = (studio_sandbox_paths or {}).get(ref)
                if sandbox_path:
                    return [
                        f"[目录: {att.get('name', '')}/，已只读引入当前 Session：{sandbox_path}。"
                        "请先用 workspace_list 分页列举，再按需用 workspace_read 读取具体文件；"
                        "不要修改 input/ 或访问目录之外的路径。]"
                    ]
                return [
                    f"[目录 {att.get('name', '')}/ 未获得可读取工作区权限，不能按名称推测或访问路径。]"
                ]
            text = await ChatRuntimeSupport._read_attachment_text(att)
            max_len = 8000
            snippets: list[str] = []
            if file_id:
                # file_id 可能已带 scheme（file://uuid 或 upload://hex）；无 scheme 时按上传文件处理
                ref = file_id if "://" in file_id else f"upload://{file_id}"
                sandbox_path = (studio_sandbox_paths or {}).get(ref)
                if sandbox_path:
                    # Studio：文件已挂载进沙盒工作区，指示模型按文件系统路径读取
                    snippets.append(
                        f"[文件: {att.get('name', '')}，已引入沙盒工作区 {sandbox_path}。"
                        f"在 sandbox_execute 代码或工作区工具中请直接使用该路径读取，"
                        f"不要使用 file:// / upload:// 引用（沙盒内无法解析）]"
                    )
                elif studio_sandbox_paths is None:
                    # 普通聊天：轻量沙盒执行前由 chat_sandbox_execute 注入附件
                    snippets.append(
                        f"[文件: {att.get('name', '')}，file_id: {ref}，"
                        f'可用 workspace_read_file(file_id="{ref}") 读取内容，'
                        f"或在其它工具参数中直接引用该 file_id；"
                        f"调用 chat_sandbox_execute 执行代码时，该文件会自动注入沙盒 "
                        f"/workspace/input/ 目录（真实路径见工具结果的 input_files）]"
                    )
                else:
                    # Studio：文件未挂载进工作区，沙盒代码在文件系统中找不到它，
                    # 不能再提 chat_sandbox_execute 自动注入（Studio 模式该工具不挂载）。
                    snippets.append(
                        f"[文件: {att.get('name', '')}，file_id: {ref}，"
                        f"该文件未挂载进沙盒工作区，沙盒内无法按文件路径访问；"
                        f'请用 workspace_read_file(file_id="{ref}") 在宿主侧读取内容]'
                    )
            if text:
                snippet = text[:max_len] + ("\n...（已截断）" if len(text) > max_len else "")
                snippets.append(f"[文件内容预览: {att.get('name', '')}]\n{snippet}")
            if not snippets:
                snippets.append(f"[文件 {att.get('name', '')} 读取失败或为空]")
            return snippets

        new_messages = list(messages)

        if not has_image:
            # 纯文本附件：拼成字符串，兼容性最好
            parts = [base_text]
            for att in attachment_dicts:
                snippets = await _build_snippets(att)
                parts.append("\n\n".join(snippets))
            new_messages[target_index] = {**target, "content": "\n\n".join(parts)}
            return new_messages

        # 含图片：使用 OpenAI 多模态 list 格式
        content: list[dict[str, Any]] = [{"type": "text", "text": base_text}]
        for att in attachment_dicts:
            att_type = att.get("type", "file")
            mime = att.get("mime_type", "")
            if att_type == "image" or (mime and mime.startswith("image/")):
                data_url = await ChatRuntimeSupport._read_attachment_data_url(att)
                if data_url:
                    content.append({"type": "image_url", "image_url": {"url": data_url}})
                else:
                    content.append(
                        {
                            "type": "text",
                            "text": f"\n\n[图片 {att.get('name', '')} 读取失败]",
                        }
                    )
            else:
                snippets = await _build_snippets(att)
                content.append({"type": "text", "text": "\n\n" + "\n\n".join(snippets)})

        new_messages[target_index] = {**target, "content": content}
        return new_messages

    @staticmethod
    def _resolve_attachment_path(att_url: str) -> str | None:
        """把聊天附件 URL 解析为本地路径，非本地上传或越权则返回 None。"""
        prefix = "/api/v1/files/chat-upload/"
        if not att_url.startswith(prefix):
            return None
        rest = att_url[len(prefix) :]
        parts = rest.split("/", 1)
        if len(parts) != 2:
            return None
        user_id, filename = parts
        filename = Path(filename).name
        from cygnusx.infrastructure.config.storage_config import get_user_chat_upload_dir

        path = get_user_chat_upload_dir(user_id) / filename
        if path.is_file():
            return str(path)
        return None

    @staticmethod
    def _is_internal_url(url: str) -> bool:
        """禁止访问内网、回环、链路本地、metadata 等地址，防止 SSRF。"""
        if not url:
            return True
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return True
        host = parsed.hostname
        if not host:
            return True
        if host == "169.254.169.254":
            return True
        try:
            addr = ipaddress.ip_address(host)
            return (
                addr.is_loopback
                or addr.is_private
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
            )
        except ValueError:
            # 域名：放行；如需更严格可再校验是否解析到内网
            return False

    @staticmethod
    async def _read_attachment_data_url(att: dict[str, Any]) -> str:
        """读取附件并返回 base64 data URL（主要用于图片）。"""
        import base64

        att_url = att.get("url", "")
        mime = att.get("mime_type") or "application/octet-stream"
        local_path = ChatRuntimeSupport._resolve_attachment_path(att_url)
        try:
            if local_path:
                async with await anyio.open_file(local_path, "rb") as f:
                    data = await f.read()
            else:
                if ChatRuntimeSupport._is_internal_url(att_url):
                    logger.warning(f"拒绝读取内网/非法附件 URL: {att_url}")
                    return ""
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(att_url)
                    resp.raise_for_status()
                    data = resp.content
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取附件失败 {att.get('name')}: {e}")
            return ""

    @staticmethod
    async def _read_attachment_text(att: dict[str, Any]) -> str:
        """读取文本类附件内容；PDF/DOCX 走专用抽取，避免二进制乱码注入模型。"""
        att_url = att.get("url", "")
        local_path = ChatRuntimeSupport._resolve_attachment_path(att_url)
        mime_type = str(att.get("mime_type", "")).lower()
        filename = str(att.get("name", ""))
        is_pdf = mime_type == "application/pdf" or Path(filename).suffix.lower() == ".pdf"
        is_docx = is_docx_attachment(mime_type, filename)
        try:
            if local_path:
                if is_pdf:
                    return await ChatRuntimeSupport._extract_pdf_text(local_path)
                if is_docx:
                    return await anyio.to_thread.run_sync(extract_docx_text, local_path)
                async with await anyio.open_file(
                    local_path, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    return await f.read()
            if ChatRuntimeSupport._is_internal_url(att_url):
                logger.warning(f"拒绝读取内网/非法附件 URL: {att_url}")
                return ""
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(att_url)
                resp.raise_for_status()
                if is_pdf:
                    import tempfile

                    suffix = Path(filename).suffix or ".pdf"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(resp.content)
                        tmp_path = tmp.name
                    try:
                        return await ChatRuntimeSupport._extract_pdf_text(tmp_path)
                    finally:
                        await anyio.Path(tmp_path).unlink(missing_ok=True)
                if is_docx:
                    return await anyio.to_thread.run_sync(extract_docx_text, resp.content)
                return resp.text
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取文本附件失败 {att.get('name')}: {e}")
            return ""

    @staticmethod
    async def _extract_pdf_text(file_path: str) -> str:
        """提取聊天 PDF 的分页文本，避免把二进制内容按 UTF-8 注入模型。"""
        from cygnusx.application.services.pdf_processor import (
            CHAT_ATTACHMENT_CONFIG,
            PDFProcessor,
        )

        processor = PDFProcessor(config=CHAT_ATTACHMENT_CONFIG)
        result = await processor.process(file_path)
        return result.content

    async def _resolve_model(self, model_id: uuid.UUID) -> AIProviderConfigModel | None:
        """按 ID 解析已启用的模型配置。"""
        result = await self._db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.id == model_id,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def _apply_usage_to_session(
        self,
        message_id: str,
        usage: dict[str, Any] | None,
    ) -> None:
        """把 LLM 返回的 usage 累加到会话 total_tokens，并写入消息 metadata。"""
        if not usage:
            return
        try:
            total = int(
                usage.get("total_tokens")
                or usage.get("total")
                or (
                    int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                    + int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                )
                or 0
            )
            if total <= 0:
                return
            msg_result = await self._db.execute(
                select(ChatMessageModel).where(ChatMessageModel.message_id == message_id)
            )
            msg = msg_result.scalar_one_or_none()
            if not msg:
                return
            session_result = await self._db.execute(
                select(ChatSessionModel).where(ChatSessionModel.session_id == msg.session_id)
            )
            session = session_result.scalar_one_or_none()
            if session:
                session.total_tokens += total
                await self._deduct_ai_cookies(session, total, message_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"累加 token 用量失败: {e}")

    async def _ensure_cookie_balance(self, user_id: str) -> str | None:
        """AI 对话准入闸门：饼干余额不足时返回错误文案，放行返回 None。"""
        settings = get_settings()
        if not settings.enable_cookie_system:
            return None
        try:
            from cygnusx.application.services.cookie_service import CookieService

            balance = await CookieService(self._db).check_balance(uuid.UUID(user_id))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI 对话饼干余额检查失败，放行: {e}")
            return None
        if balance > 0:
            return None
        rate = settings.ai_token_cookie_rate
        return (
            f"饼干余额不足，无法使用 AI 助手（每 1K tokens 消耗 {rate} 🥫）。"
            "请先通过提交分析任务赚取饼干后再试。"
        )

    async def _deduct_ai_cookies(
        self, session: ChatSessionModel, tokens: int, message_id: str
    ) -> None:
        """按 ai_token_cookie_rate 🥫/1K tokens 从会话属主账户扣减饼干。"""
        settings = get_settings()
        if not settings.enable_cookie_system or tokens <= 0:
            return
        try:
            from cygnusx.application.services.cookie_service import CookieService

            await CookieService(self._db).spend_ai_tokens(
                user_id=uuid.UUID(str(session.user_id)),
                tokens=tokens,
                source_id=message_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI 对话饼干扣减失败: {e}")

    async def _record_skill_invocation(
        self,
        *,
        skill_meta: dict[str, Any],
        status: str,
        duration_ms: float,
        summary: str,
        error: str,
        session_id: str,
        message_id: Any,
        user_id: str | None,
    ) -> None:
        """落库一条技能调用记录（绝不阻断对话流：任何失败只记日志）。"""
        try:
            from cygnusx.application.services.skill_service import SkillService

            def _to_uuid(value: Any) -> uuid.UUID | None:
                try:
                    return uuid.UUID(str(value)) if value else None
                except (ValueError, AttributeError, TypeError):
                    return None

            await SkillService(self._db).record_invocation(
                skill_id=str(skill_meta.get("skill_id") or ""),
                skill_name=str(skill_meta.get("name") or ""),
                skill_version=str(skill_meta.get("version") or "") or None,
                source=str(skill_meta.get("source") or ""),
                tool_name=USE_SKILL_TOOL_NAME,
                status=status,
                duration_ms=duration_ms,
                summary=summary,
                error=error,
                session_id=_to_uuid(session_id),
                message_id=_to_uuid(message_id),
                user_id=_to_uuid(user_id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("技能调用记录落库失败（忽略）: {}", exc)

    async def _execute_skill_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        skills: list[Any],
        skill_pins: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """技能工具执行入口（带 Trace/Log/Metrics 埋点）。"""
        skill_key = str(args.get("skill_id") or args.get("name") or "").strip()
        tracer = get_tracer("cygnusx.chat")
        with tracer.start_as_current_span(
            "skill.execute",
            attributes={"skill.tool_name": tool_name, "skill.skill_id": skill_key},
        ) as span:
            start = time.perf_counter()
            status = "success"
            try:
                result = await self._execute_skill_tool_inner(
                    tool_name, args, skills, skill_pins=skill_pins
                )
                if not result.get("success"):
                    status = "error"
                return result
            except Exception as exc:  # noqa: BLE001
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                attrs = {"skill.tool_name": tool_name, "skill.status": status}
                span.set_attribute("skill.status", status)
                span.set_attribute("skill.duration_ms", round(duration_ms, 2))
                try:
                    _skill_count.add(1, attrs)
                    _skill_duration.record(duration_ms, attrs)
                except Exception:  # noqa: BLE001
                    pass
                logger.bind(
                    event="skill.execute",
                    tool_name=tool_name,
                    skill_id=skill_key,
                    status=status,
                    duration_ms=round(duration_ms, 2),
                ).info("skill.execute completed")

    async def _execute_skill_tool_inner(
        self,
        tool_name: str,
        args: dict[str, Any],
        skills: list[Any],
        skill_pins: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """技能渐进式披露内部工具：

        - use_skill（L2）：返回已挂载技能的 SKILL.md 正文。会话 pin 优先（会话启动时
          锁定的版本快照），其次磁盘优先，最后 DB prompt 兜底
        - skill_resource（L3）：按需读取技能 references/assets 文件，代码不进上下文
        """
        from cygnusx.infrastructure.skills import skill_store

        skill_key = str(args.get("skill_id") or args.get("name") or "").strip()
        skill = next((s for s in skills if s.skill_id == skill_key or s.name == skill_key), None)
        if skill is None:
            mounted = "、".join(s.skill_id for s in skills) or "无"
            return {
                "success": False,
                "error": f"技能 '{skill_key}' 未挂载到该助手（已挂载：{mounted}）",
            }

        if tool_name == USE_SKILL_TOOL_NAME:
            body: str | None = None
            pinned_from: str | None = None
            pinned_rev = (skill_pins or {}).get(skill.skill_id)
            if pinned_rev:
                # 会话 pin：读取会话启动时锁定 revision 的快照正文，
                # 会话中途升级/回滚不影响进行中的任务
                try:
                    from cygnusx.infrastructure.database.models.skill import (
                        SkillVersionModel,
                    )

                    snap = (
                        await self._db.execute(
                            select(SkillVersionModel).where(
                                SkillVersionModel.skill_id == skill.skill_id,
                                SkillVersionModel.revision == int(pinned_rev),
                            )
                        )
                    ).scalar_one_or_none()
                    if snap and (snap.prompt or "").strip():
                        body = snap.prompt
                        pinned_from = f"r{snap.revision}"
                except Exception as pin_exc:  # noqa: BLE001
                    logger.warning("读取 pin 版本失败（回落当前内容）: {}", pin_exc)
            if body is None:
                body = skill_store.read_skill_body(skill.skill_id) or (skill.prompt or "")
            if not body.strip():
                return {"success": False, "error": f"技能 '{skill.name}' 暂无指令正文"}
            resources = skill_store.list_skill_files(skill.skill_id)
            return {
                "success": True,
                "result": {
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                    "instructions": body,
                    "pinned_revision": pinned_from,
                    "resources": resources or None,
                    "resource_hint": (
                        "正文引用的 references/assets 文件请用 skill_resource 工具读取"
                        if resources
                        else None
                    ),
                },
            }

        if tool_name == SKILL_RESOURCE_TOOL_NAME:
            path = str(args.get("path") or "").strip()
            if not path:
                return {"success": False, "error": "缺少 path 参数"}
            ok, msg, content = skill_store.read_skill_resource(skill.skill_id, path)
            if not ok or content is None:
                return {"success": False, "error": msg}
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                return {
                    "success": True,
                    "result": {
                        "path": path,
                        "note": "该资源为二进制文件，无法作为文本读取",
                    },
                }
            return {"success": True, "result": {"path": path, "content": text}}

        return {"success": False, "error": f"未知技能工具: {tool_name}"}

    async def _web_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行默认联网搜索服务商，并返回统一结果结构。"""
        query = arguments.get("query", "")
        top_n = int(arguments.get("top_n", 5))
        if not query.strip():
            return {"success": False, "error": "缺少搜索关键词"}
        try:
            result = await self._optimized_web_search(query, top_n=top_n)
            return {"success": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            logger.warning("联网搜索工具调用失败: %s", exc)
            return {"success": False, "error": "联网搜索失败，已跳过搜索结果"}

    async def _optimized_web_search(
        self,
        query: str,
        *,
        top_n: int = 8,
        model_config: Any | None = None,
    ) -> dict[str, Any]:
        """Run cached query refinement, multi-query retrieval, dedupe and reranking."""
        from cygnusx.application.services.chat_service import _extract_route_json

        optimizer = ResearchSearchOptimizer()
        fallback_queries = build_research_queries(query)["web_queries"]

        async def refine(value: str) -> dict[str, Any]:
            if model_config is None:
                return {"queries": []}
            answer = ""
            async for item in provider_manager.chat_stream(
                config=model_config,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"用户问题：{value}\n\n"
                            "请生成 2-4 条英文联网检索式。每条保留 2-4 个最关键概念或短语，"
                            "用 AND/OR 连接；优先保留实体、主题、任务目标和时效条件。"
                            "不要解释，不添加网站域名。严格返回 JSON："
                            '{"queries":["...","..."]}。'
                        ),
                    }
                ],
                system_prompt="你只负责精炼联网检索式，不回答用户问题。",
                temperature=0.1,
                max_tokens=240,
                tools=None,
                deep_thinking=False,
            ):
                if item.type == "text" and not item.metadata.get("is_reasoning"):
                    answer += item.content
            parsed = _extract_route_json(answer) or {}
            return {"queries": parsed.get("queries") or []}

        refinement = await optimizer.refine_queries(
            query,
            fallback_queries=fallback_queries,
            refiner=refine if model_config is not None else None,
        )
        candidates: list[dict[str, Any]] = []
        errors: list[str] = []
        for refined_query in refinement["queries"][:4]:
            try:
                candidates.extend(
                    await SearchProviderService(self._db).search_default(
                        refined_query,
                        max(5, min(int(top_n), 12)),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - partial query success is useful
                errors.append(str(exc)[:300])
        if not candidates and errors:
            raise RuntimeError(errors[0])
        results = await optimizer.rerank(query, candidates, limit=max(5, min(int(top_n), 8)))
        payload: dict[str, Any] = {
            "query": query,
            "queries": refinement["queries"],
            "query_refinement": refinement,
            "results": results,
            "reranked": True,
        }
        if errors:
            payload["partial_errors"] = errors
        return payload

    async def _knowledge_search_chat(
        self, arguments: dict[str, Any], *, project_id: str | None = None
    ) -> dict[str, Any]:
        """普通聊天的知识库检索：复用 Studio 工具实现（只检索已发布文档的当前修订）。"""
        from cygnusx.application.services.studio_tools import _knowledge_search

        try:
            return await _knowledge_search(arguments, self._db, project_id=project_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识库检索工具调用失败: %s", exc)
            return {"success": False, "error": "知识库检索失败，已跳过"}

    # --- 助手管理 ---
