"""声明式环境还原服务（WP2 任务 3，替代容器快照）。

会话激活（Studio 容器懒启动/重建后首次执行）时检测工作区根目录声明文件：
- ``conda-explicit.txt`` 优先：按运行时镜像约定用 micromamba 以 explicit spec
  安装进 base 环境（``micromamba install --yes --name base --file ...``）；
- 否则 ``environment.yml``：剥离顶层 ``name:`` / ``prefix:`` 后以 base 环境为准
  更新（``micromamba update --yes --name base --file ...``），保证 CLI 目标环境
  不被文件内字段劫持；
- 两者都没有则跳过；WP1 打包 manifest 标了 ``missing_env_snapshot`` 的会话，
  跳过原因中带上缺失清单（存在性检测本身就是不还原的第一道闸）。

还原结果（成功/失败/耗时/跳过原因）由 manager 钩子写入 loguru（含 session_id）
并经本服务落 ``audit_logs``（resource_type='workspace_env_restore'）。
还原失败不阻断会话启动 —— 本服务所有 DB 访问都尽力而为，异常只记日志。
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from sqlalchemy import select

from cygnusx.infrastructure.database.models.audit_log import AuditLogModel
from cygnusx.infrastructure.database.session import get_session_factory

# 还原声明文件（与 WP1 环境快照四件套前两项同名同位置：工作区根目录）
RESTORE_FILE_EXPLICIT = "conda-explicit.txt"
RESTORE_FILE_YML = "environment.yml"
RESTORE_FILES = (RESTORE_FILE_EXPLICIT, RESTORE_FILE_YML)

# 还原超时下限：环境安装（conda 解依赖）通常超过普通 exec 的 600s 默认线，
# 参考 sandbox_agent MAX_EXEC_TIMEOUT=3600 的既有上限约定。
_MIN_RESTORE_TIMEOUT_SECONDS = 900
_MAX_RESTORE_TIMEOUT_SECONDS = 3600

_FAILURE_SUMMARY_LIMIT = 300


@dataclass
class EnvRestoreResult:
    """一次环境还原尝试的结果（成功 / 失败 / 跳过）。"""

    status: Literal["restored", "failed", "skipped"]
    file: str | None
    duration_ms: int
    reason: str | None  # 跳过原因或失败摘要（前者给日志，后者给前端 toast）
    container_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_restore_file(workspace: Path) -> str | None:
    """按优先级检测工作区根目录的还原声明文件；不存在返回 None。"""
    for name in RESTORE_FILES:
        if (workspace / name).is_file():
            return name
    return None


# WP3 任务 3 门控跳过原因（写入 _env_restore_state.reason，区别于"无声明文件"跳过）
RESTORE_SKIP_RESEARCH_MODE_OFF = "research_mode_off"


async def research_restore_gate_enabled(session_id: str) -> tuple[bool, str | None]:
    """科研模式门控：仅当会话 research_mode.enabled=true 且 workspace_protocol="research"
    时才执行声明式环境还原（WP3 任务 3）。

    返回 (是否放行, 不放行原因)。开关只影响交互层——执行/审批/审计路径不变；
    DB 读取异常按不放行降级（默认全关 = 现状默认行为）。
    """
    try:
        async with get_session_factory()() as db:
            from cygnusx.infrastructure.database.models.chat import ChatSessionModel

            result = await db.execute(
                select(ChatSessionModel.sandbox_meta).where(
                    ChatSessionModel.session_id == session_id
                )
            )
            sandbox_meta = result.scalar_one_or_none() or {}
    except Exception as exc:  # noqa: BLE001 - 开关读失败按关闭降级，绝不阻断激活
        logger.debug("[EnvRestore] research_mode 门控读取失败（按关闭处理）: {}", exc)
        return False, f"gate_read_error: {exc}"
    research_mode = (sandbox_meta or {}).get("research_mode")
    if not isinstance(research_mode, dict) or not research_mode.get("enabled"):
        return False, "research_mode 未开启（sandbox_meta.research_mode.enabled != true）"
    if research_mode.get("workspace_protocol") != "research":
        return False, (
            "workspace_protocol 非 research"
            f"（实际: {research_mode.get('workspace_protocol')!r}）"
        )
    return True, None


def build_restore_script(file_name: str) -> str:
    """生成容器内一次性执行的还原脚本（非交互，stdout/stderr 经 exec 通道回收）。

    运行时镜像（deploy/runtime-images/core.Dockerfile）基于
    mambaorg/micromamba，科学栈装在 base 环境（/opt/conda），无 conda 二进制，
    因此统一走 micromamba（与镜像内 CMD、提示词契约一致）。
    """
    if file_name == RESTORE_FILE_EXPLICIT:
        return (
            "set -o pipefail\n"
            "micromamba install --yes --name base --file /workspace/conda-explicit.txt\n"
        )
    if file_name == RESTORE_FILE_YML:
        # 剥离 name:/prefix:：micromamba 对 yml 内环境名的优先级随版本变化，
        # 显式去掉后 --name base 是唯一目标，行为确定。
        # 注意用 install 而非 update：micromamba 2.x 的 update --file 对 yml 中
        # 尚未安装的包是 no-op（实测），install --file 才等价 conda env update -f。
        return (
            "set -o pipefail\n"
            "sed -e '/^name:/d' -e '/^prefix:/d' /workspace/environment.yml "
            "> /tmp/cygnusx-env-restore.yml\n"
            "micromamba install --yes --name base --file /tmp/cygnusx-env-restore.yml\n"
        )
    raise ValueError(f"不支持的还原声明文件: {file_name}")


def restore_timeout_seconds(exec_timeout_seconds: int) -> int:
    """还原超时：普通 exec 超时与 900s 下限取大，封顶 3600s（agent 上限）。"""
    return min(max(int(exec_timeout_seconds), _MIN_RESTORE_TIMEOUT_SECONDS), _MAX_RESTORE_TIMEOUT_SECONDS)


def summarize_failure(stderr_tail: str, exit_code: int) -> str:
    """把容器内还原输出的尾部压成单行失败摘要（前端 toast / audit detail 用）。"""
    tail = " ".join(str(stderr_tail or "").split())[-_FAILURE_SUMMARY_LIMIT:]
    summary = f"exit_code={exit_code}"
    if tail:
        summary = f"{summary}: {tail}"
    return summary


async def latest_missing_env_snapshot(session_id: str) -> list[str] | None:
    """从 WP1 打包审计中取最近一次 manifest 的 missing_env_snapshot 清单。

    manifest 本身在 tar.gz 内（无独立 DB 列），打包时落过一条
    resource_type='workspace_archive' 的审计（detail.missing_env_snapshot），
    这里是该事实的廉价查询口；查不到返回 None（不阻断、不猜测）。
    """
    try:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(AuditLogModel)
                .where(
                    AuditLogModel.resource_type == "workspace_archive",
                    AuditLogModel.resource_id == session_id,
                )
                .order_by(AuditLogModel.created_at.desc())
                .limit(5)
            )
            for row in result.scalars():
                detail = row.detail or {}
                if detail.get("event") != "workspace_archive_packed":
                    continue
                missing = detail.get("missing_env_snapshot")
                if isinstance(missing, list):
                    return [str(item) for item in missing]
                return None
    except Exception as exc:  # noqa: BLE001 - 审计读是尽力而为，绝不阻断激活
        logger.debug("[EnvRestore] 查询 missing_env_snapshot 失败（按无标记处理）: {}", exc)
    return None


async def write_restore_audit(
    *,
    session_id: str,
    user_id: str | None,
    result: EnvRestoreResult,
) -> None:
    """还原结果落 audit_logs；status_code 沿用 HTTP 语义（200 成功 / 500 失败 / 204 跳过）。"""
    user_uuid: uuid.UUID | None = None
    with contextlib.suppress(ValueError, TypeError, AttributeError):
        user_uuid = uuid.UUID(str(user_id)) if user_id else None
    status_code = {"restored": 200, "failed": 500, "skipped": 204}[result.status]
    detail: dict[str, Any] = {
        "event": "workspace_env_restore",
        "session_id": session_id,
        "status": result.status,
        "success": result.status == "restored",
        "file": result.file,
        "duration_ms": result.duration_ms,
        "container_id": result.container_id,
    }
    if result.reason:
        detail["reason"] = result.reason
    try:
        async with get_session_factory()() as db:
            db.add(
                AuditLogModel(
                    id=uuid.uuid4(),
                    user_id=user_uuid,
                    username=None if user_uuid else (str(user_id) if user_id else "system"),
                    method="POST",
                    path=f"/internal/studio/sessions/{session_id}/env-restore",
                    resource_type="workspace_env_restore",
                    resource_id=session_id[:100],
                    status_code=status_code,
                    detail=detail,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - 审计写失败不阻断会话
        logger.warning(
            "[EnvRestore] 会话 {} 还原审计落库失败（结果仍按日志为准）: {}",
            session_id[:8],
            exc,
        )
