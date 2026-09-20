"""项目分析归档服务 —— 平台级、非 LLM 依赖的可追溯文档生成。

平台约定：每次分析归档到 ``users/{user_id}/projects/{slug}/runs/{分析名}-{时间戳}/``
（由 ``StoragePathFactory.create_project_run_dir`` 创建）。本服务在归档点强制生成/更新：

- 项目级 ``AGENTS.md``：不存在时创建（项目名/客户/描述/创建时间 + “分析记录”小节），
  每次归档向“分析记录”追加一行条目（按 run 目录名幂等，重复归档不产生重复条目）；
- run 级 ``README.md``：项目/客户/时间戳/分析类型与流程版本/最终产物清单（文件名 +
  大小 + md5 + sha256，MD5 保留兼容）/代码脚本清单/软件与版本段/分析环境段；
- run 级 ``manifest.json``：逐文件 path/size/sha256 实测对账记录（OpenAI4S 契约同款字段）；
- run 级 ``environment.json``：结构化环境快照（字段命名稳定，供机器校验）。

所有内容由平台代码生成，不依赖 LLM；调用方必须用 try/except 兜底，
归档失败记录 error 日志后不得阻断主流程。
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.artifact_manifest import sha256_stream
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.config.runtime_image_loader import get_runtime_images
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.models.project import ProjectModel
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory, project_slug

ARCHIVE_SCHEMA_VERSION = 1
ANALYSIS_LOG_HEADING = "## 分析记录"
_ANALYSIS_LOG_TABLE_HEADER = (
    "| 时间 | 运行目录 | 分析类型 | 状态 | 摘要 |\n| --- | --- | --- | --- | --- |"
)
_MD5_CHUNK_SIZE = 1024 * 1024
_CODE_EXTENSIONS = {".py", ".sh", ".r", ".ipynb", ".sql"}
_CODE_SCAN_LIMIT = 50


@dataclass
class ProjectInfo:
    """归档文档所需的项目元信息（DB 记录缺失时按名称兜底）。"""

    name: str
    slug: str = ""
    description: str = ""
    customer: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = project_slug(self.name)


@dataclass
class ArchivedFile:
    """run 目录内一个已归档文件的清单条目。"""

    name: str
    relative_path: str  # 相对 run 目录，如 "output/de.csv"
    size: int = 0
    md5: str = ""
    # 登记/归档时实测的 sha256（流式分块读取）；读取失败为空串，
    # 与 md5 并存：MD5 保留兼容，sha256 为新的对账口径。
    sha256: str = ""


# ------------------------------------------------------------------
# 环境快照（单一来源：README 与 environment.json 共用）
# ------------------------------------------------------------------


def collect_environment(
    *,
    image: str | None = None,
    flow_id: str = "",
    flow_name: str = "",
    flow_version: str = "",
) -> dict[str, Any]:
    """采集一次分析的运行环境快照（字段命名稳定，供机器校验）。

    运行时镜像能反查到注册表 profile 时，附带其 software/languages/resources
    清单；查不到（未注册镜像、注册表缺失）时只记录镜像名，不报错。
    """
    settings = get_settings()
    runtime: dict[str, Any] = {
        "image": image or "",
        "profile": "",
        "languages": {},
        "software": {},
        "resources": {},
    }
    if image:
        try:
            found = get_runtime_images().profile_for_image(image)
        except Exception as exc:  # noqa: BLE001 - 注册表不可用时只记录镜像名
            logger.warning("运行时镜像注册表读取失败（归档继续）: {}", exc)
            found = None
        if found is not None:
            profile_id, profile = found
            runtime.update(
                {
                    "profile": profile_id,
                    "languages": dict(profile.languages),
                    "software": dict(profile.software),
                    "resources": {
                        "cpu": profile.resources.cpu,
                        "memory": profile.resources.memory,
                        "pids": profile.resources.pids,
                    },
                }
            )
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "platform": {
            "name": settings.app_name,
            "version": settings.app_version,
            "git_sha": settings.app_git_sha,
        },
        "python": {"version": platform.python_version()},
        "runtime": runtime,
        "flow": {"id": flow_id, "name": flow_name, "version": flow_version},
    }


async def collect_session_environment(
    db: AsyncSession,
    session_id: str,
    *,
    flow_id: str = "",
    flow_name: str = "",
    flow_version: str = "",
) -> dict[str, Any]:
    """按会话采集环境快照：运行时镜像取自 session.sandbox_meta.image。"""
    session = await db.scalar(
        select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
    )
    image = ""
    if session is not None:
        image = str((session.sandbox_meta or {}).get("image") or "")
    return collect_environment(
        image=image or None, flow_id=flow_id, flow_name=flow_name, flow_version=flow_version
    )


def render_environment_markdown(environment: dict[str, Any]) -> list[str]:
    """把环境快照渲染为 README 的“软件与版本 / 分析环境”两段。"""
    runtime = environment.get("runtime") or {}
    flow = environment.get("flow") or {}
    platform_info = environment.get("platform") or {}
    software = runtime.get("software") or {}
    resources = runtime.get("resources") or {}
    lines = ["## 软件与版本", ""]
    lines.append(f"- 运行时镜像: `{runtime.get('image') or '未记录'}`")
    if runtime.get("profile"):
        lines.append(f"- 运行时 Profile: `{runtime['profile']}`")
    if software:
        lines.extend(["", "| 软件 | 版本 |", "| --- | --- |"])
        for name, version in sorted(software.items()):
            lines.append(f"| {name} | {version or 'installed'} |")
    if flow.get("id") or flow.get("name"):
        lines.append(f"- 分析流程: {flow.get('name') or flow.get('id')}")
    if flow.get("version"):
        lines.append(f"- 流程版本: {flow['version']}")
    lines.append(
        f"- 平台版本: {platform_info.get('version', 'unknown')}"
        f" (git `{platform_info.get('git_sha', 'unknown')}`)"
    )
    lines.extend(["", "## 分析环境", ""])
    lines.append(f"- Python: {(environment.get('python') or {}).get('version', 'unknown')}")
    if resources:
        lines.append(
            "- 资源画像: "
            f"CPU {resources.get('cpu')} / 内存 {resources.get('memory')}"
            f" / PID 上限 {resources.get('pids')}"
        )
    lines.append(f"- 环境快照: `environment.json` (schema v{environment.get('schema_version')})")
    return lines


# ------------------------------------------------------------------
# AGENTS.md（项目级）
# ------------------------------------------------------------------


def render_project_agents_md(project: ProjectInfo) -> str:
    """首次归档时生成项目级 AGENTS.md 初始内容。"""
    created = project.created_at or datetime.now(UTC).isoformat()
    lines = [
        f"# {project.name}",
        "",
        "> 本文件由 CygnusX 平台自动生成与维护：每次分析归档时追加运行记录，请勿手工删除条目。",
        "",
        f"- 项目: {project.name}",
        f"- 客户: {project.customer or '未填写'}",
        f"- 描述: {project.description or '（无）'}",
        f"- 创建时间: {created}",
        f"- 项目目录: `projects/{project.slug}/`",
        "",
        ANALYSIS_LOG_HEADING,
        "",
        _ANALYSIS_LOG_TABLE_HEADER,
    ]
    return "\n".join(lines) + "\n"


def _one_line(text: str, *, limit: int = 120) -> str:
    collapsed = " ".join(str(text or "").split())
    collapsed = collapsed.replace("|", "\\|")
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return collapsed or "（无）"


def append_analysis_entry(
    content: str,
    *,
    run_name: str,
    timestamp: str,
    analysis_type: str,
    status: str,
    summary: str,
) -> tuple[str, bool]:
    """向 AGENTS.md 的“分析记录”追加一行；run 目录名已存在时幂等跳过。"""
    marker = f"runs/{run_name}"
    if marker in content:
        return content, False
    row = (
        f"| {timestamp} | `{marker}/` | {_one_line(analysis_type, limit=40)}"
        f" | {_one_line(status, limit=20)} | {_one_line(summary)} |"
    )
    if ANALYSIS_LOG_HEADING not in content:
        content = (
            content.rstrip()
            + f"\n\n{ANALYSIS_LOG_HEADING}\n\n{_ANALYSIS_LOG_TABLE_HEADER}\n"
        )
        return content + row + "\n", True
    return content.rstrip() + "\n" + row + "\n", True


# ------------------------------------------------------------------
# run 级 README.md / environment.json
# ------------------------------------------------------------------


def render_run_readme(
    *,
    project: ProjectInfo,
    run_name: str,
    analysis_type: str,
    status: str,
    summary: str,
    environment: dict[str, Any],
    artifacts: list[ArchivedFile],
    code_files: list[ArchivedFile],
    archived_at: str,
) -> str:
    flow = environment.get("flow") or {}
    lines = [
        f"# 分析运行归档:{analysis_type}",
        "",
        f"- 项目: {project.name}",
        f"- 客户: {project.customer or '未填写'}",
        f"- 运行目录: `runs/{run_name}/`",
        f"- 归档时间: {archived_at}",
        f"- 分析类型: {analysis_type}",
        f"- 状态: {status}",
    ]
    if flow.get("version"):
        lines.append(f"- 流程版本: {flow['version']}")
    lines.extend(["", "## 摘要", "", summary.strip() or "（无）"])
    lines.extend(["", "## 最终结果", ""])
    if artifacts:
        lines.extend(["| 文件 | 大小(bytes) | MD5 | SHA-256 |", "| --- | --- | --- | --- |"])
        for item in artifacts:
            lines.append(
                f"| `{item.relative_path}` | {item.size} | {item.md5 or '-'} | {item.sha256 or '-'} |"
            )
    else:
        lines.append("（无）")
    lines.extend(["", "## 代码与脚本", ""])
    if code_files:
        for item in code_files:
            lines.append(f"- `{item.relative_path}`({item.size} bytes)")
    else:
        lines.append("（本次未归档独立的代码/脚本文件）")
    lines.extend(["", *render_environment_markdown(environment)])
    return "\n".join(lines).rstrip() + "\n"


def md5_stream(path: Path) -> str:
    """流式计算本地文件 md5（分块读取，参考 verify_manifest.py）；失败返回空串。"""
    checksum = hashlib.md5()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_MD5_CHUNK_SIZE), b""):
                checksum.update(block)
    except OSError:
        return ""
    return checksum.hexdigest()


def _scan_code_files(run_dir: Path) -> list[ArchivedFile]:
    """扫描 run 目录内的代码/脚本文件（work/ 与 output/，限深限量）。"""
    found: list[ArchivedFile] = []
    for sub in ("work", "output", ""):
        base = run_dir / sub if sub else run_dir
        if not base.is_dir():
            continue
        try:
            candidates = sorted(base.iterdir())
        except OSError:
            continue
        for entry in candidates:
            if len(found) >= _CODE_SCAN_LIMIT:
                return found
            if not entry.is_file() or entry.suffix.lower() not in _CODE_EXTENSIONS:
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            relative = entry.relative_to(run_dir).as_posix()
            found.append(ArchivedFile(name=entry.name, relative_path=relative, size=size))
    return found


# ------------------------------------------------------------------
# 归档主入口
# ------------------------------------------------------------------


def _assert_run_dir_within_project(project_root: Path, run_dir: Path) -> None:
    try:
        run_dir.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"run 目录不在项目目录内: {run_dir}") from exc


async def archive_run(
    *,
    user_id: str,
    project: ProjectInfo,
    run_dir: Path,
    analysis_type: str,
    status: str = "completed",
    summary: str = "",
    environment: dict[str, Any] | None = None,
    artifacts: list[ArchivedFile] | None = None,
    code_files: list[ArchivedFile] | None = None,
    factory: StoragePathFactory | None = None,
    backend: Any = None,
) -> dict[str, Any]:
    """为已存在的项目 run 目录补写 README.md / environment.json 并更新项目 AGENTS.md。

    返回实际写入的 environment 快照。所有路径由 StoragePathFactory 派生并校验
    边界，不允许逃逸项目目录。
    """
    factory = factory or get_path_factory()
    backend = backend or get_storage_backend()
    if not factory.is_within_root(run_dir):
        raise ValueError(f"run 目录越权: {run_dir}")
    project_root = factory.project_dir(user_id, project.slug)
    _assert_run_dir_within_project(project_root, run_dir)

    environment = environment or collect_environment()
    artifacts = artifacts if artifacts is not None else []
    if code_files is None:
        code_files = _scan_code_files(run_dir)
    archived_at = datetime.now(UTC).isoformat()
    environment = {
        **environment,
        "run": {
            "directory": f"projects/{project.slug}/runs/{run_dir.name}",
            "analysis_type": analysis_type,
            "status": status,
            "archived_at": archived_at,
        },
        "artifacts": [
            {
                "path": item.relative_path,
                "name": item.name,
                "size": item.size,
                "md5": item.md5,
                "sha256": item.sha256,
            }
            for item in artifacts
        ],
    }

    run_rel = factory.relative_to_root(run_dir)
    readme = render_run_readme(
        project=project,
        run_name=run_dir.name,
        analysis_type=analysis_type,
        status=status,
        summary=summary,
        environment=environment,
        artifacts=artifacts,
        code_files=code_files,
        archived_at=archived_at,
    )
    await backend.write(f"{run_rel}/README.md", readme.encode("utf-8"))
    await backend.write(
        f"{run_rel}/environment.json",
        (json.dumps(environment, ensure_ascii=False, indent=2, default=str) + "\n").encode(
            "utf-8"
        ),
    )
    # 产物 manifest 旁落 README：逐文件 path/size/sha256 的实测对账记录，
    # OpenAI4S compute/manifest 契约同款字段；sha256 缺省（None）即实测失败。
    manifest = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "archived_at": archived_at,
        "files": [
            {
                "path": item.relative_path,
                "size": item.size,
                "sha256": item.sha256 or None,
            }
            for item in artifacts
        ],
    }
    await backend.write(
        f"{run_rel}/manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )

    agents_rel = factory.relative_to_root(project_root / "AGENTS.md")
    if await backend.exists(agents_rel):
        content = (await backend.read(agents_rel)).decode("utf-8")
    else:
        content = render_project_agents_md(project)
    content, appended = append_analysis_entry(
        content,
        run_name=run_dir.name,
        timestamp=archived_at,
        analysis_type=analysis_type,
        status=status,
        summary=summary,
    )
    if appended:
        await backend.write(agents_rel, content.encode("utf-8"))
    return environment


async def _resolve_project_by_slug(
    db: AsyncSession | None, user_id: str, name: str
) -> ProjectInfo:
    """按 (user_id, slug) 查项目记录补全元信息；查不到按名称兜底。"""
    info = ProjectInfo(name=name)
    if db is None:
        return info
    model: Any = None
    try:
        result = await db.execute(
            select(ProjectModel).where(
                ProjectModel.user_id == UUID(str(user_id)),
                ProjectModel.slug == info.slug,
            )
        )
        model = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - 项目记录缺失不阻断归档
        logger.warning("归档时查询项目记录失败（按名称兜底）: {}", exc)
    if model is not None:
        info.name = model.name
        info.slug = model.slug
        info.description = model.description or ""
        # customer 字段由项目模型后续版本提供，不存在时兜底为空
        info.customer = str(getattr(model, "customer", "") or "")
        info.created_at = model.created_at.isoformat() if model.created_at else ""
    return info


async def archive_studio_run(
    *,
    user_id: str,
    session: Any,
    run_dir: Path,
    report: Any,
    artifact: Any,
    factory: StoragePathFactory | None = None,
    backend: Any = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """register_artifact_report 归档后的文档补写（run 目录已存在，直接增强）。"""
    factory = factory or get_path_factory()
    backend = backend or get_storage_backend()
    project_name = str(getattr(session, "title", "") or "").strip() or run_dir.parent.parent.name
    project = await _resolve_project_by_slug(db, user_id, project_name)
    image = str((getattr(session, "sandbox_meta", None) or {}).get("image") or "")
    environment = collect_environment(
        image=image or None, flow_id="studio", flow_name="OmicStudio"
    )
    artifact_name = str(getattr(artifact, "name", "") or "")
    local_file = run_dir / "output" / artifact_name
    artifacts = [
        ArchivedFile(
            name=artifact_name,
            relative_path=f"output/{artifact_name}",
            size=int(getattr(artifact, "size", 0) or 0),
            md5=md5_stream(local_file) if local_file.is_file() else "",
            sha256=sha256_stream(local_file) if local_file.is_file() else "",
        )
    ]
    summary = str(getattr(report, "title", "") or artifact_name)
    description = str(getattr(report, "description", "") or "").strip()
    if description:
        summary = f"{summary} — {description}"
    return await archive_run(
        user_id=user_id,
        project=project,
        run_dir=run_dir,
        analysis_type="OmicStudio 产物登记",
        status=str(getattr(report, "status", "") or "completed"),
        summary=summary,
        environment=environment,
        artifacts=artifacts,
        factory=factory,
        backend=backend,
    )


async def archive_overdrive_delivery(
    db: AsyncSession,
    run: Any,
    *,
    delivery_paths: list[str],
    planning_only: bool = False,
    environment: dict[str, Any] | None = None,
    factory: StoragePathFactory | None = None,
    backend: Any = None,
) -> Path | None:
    """overdrive run 完成后把交付物复制进项目 runs 目录并生成归档文档。

    会话无 project_id 时维持现状（返回 None，不报错）。复制而非引用：
    工作区/会话目录有保留期，项目归档需独立存续。
    """
    factory = factory or get_path_factory()
    backend = backend or get_storage_backend()
    session = await db.scalar(
        select(ChatSessionModel).where(ChatSessionModel.session_id == run.session_id)
    )
    project_id = str(getattr(session, "project_id", None) or "") if session else ""
    if not project_id:
        return None
    user_id = str(run.user_id)

    project: ProjectInfo | None = None
    try:
        model = await db.get(ProjectModel, UUID(project_id))
    except ValueError:
        model = None
    if model is not None and str(model.user_id) == user_id:
        project = ProjectInfo(
            name=model.name,
            slug=model.slug,
            description=model.description or "",
            customer=str(getattr(model, "customer", "") or ""),
            created_at=model.created_at.isoformat() if model.created_at else "",
        )
    if project is None:
        fallback = str(getattr(session, "title", "") or "").strip() or project_id
        project = ProjectInfo(name=fallback)

    plan = run.plan or {}
    summary_info = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    title = str(summary_info.get("title") or "超频协作")
    analysis_name = title if title != "超频协作" else ("overdrive-plan" if planning_only else "overdrive")
    plan_version = int(plan.get("version") or 0)
    plan_digest = str(plan.get("hash") or "")
    flow_version = f"v{plan_version}" + (f" (hash {plan_digest[:8]})" if plan_digest else "")
    if environment is None:
        environment = await collect_session_environment(
            db,
            str(run.session_id),
            flow_id="overdrive",
            flow_name="超频协作",
            flow_version=flow_version,
        )

    run_dir = factory.create_project_run_dir(user_id, project.name, analysis_name)
    dest_rel_root = factory.relative_to_root(run_dir / "output")
    await backend.ensure_dir(dest_rel_root)

    artifacts: list[ArchivedFile] = []
    seen: set[str] = set()
    for raw in delivery_paths:
        rel = str(raw or "").strip()
        if not rel or rel.startswith("/") or ".." in PurePosixPath(rel).parts:
            continue
        name = PurePosixPath(rel).name
        if name in {"", ".", ".."} or name in seen:
            continue
        seen.add(name)
        try:
            content = await backend.read(rel)
        except Exception as exc:  # noqa: BLE001 - 单个交付物缺失不丢失整批归档
            logger.warning("Overdrive 归档复制产物失败（跳过）: {} {}", rel, exc)
            continue
        await backend.write(f"{dest_rel_root}/{name}", content)
        local_file = run_dir / "output" / name
        artifacts.append(
            ArchivedFile(
                name=name,
                relative_path=f"output/{name}",
                size=len(content),
                md5=md5_stream(local_file) if local_file.is_file() else "",
                sha256=sha256_stream(local_file) if local_file.is_file() else "",
            )
        )

    overview = str(summary_info.get("summary") or "").strip()
    analysis_type = "超频协作(方案规划)" if planning_only else "超频协作"
    status = str(getattr(run, "status", "") or "completed").lower()
    await archive_run(
        user_id=user_id,
        project=project,
        run_dir=run_dir,
        analysis_type=analysis_type,
        status=status,
        summary=f"{title}" + (f" — {overview}" if overview else ""),
        environment=environment,
        artifacts=artifacts,
        factory=factory,
        backend=backend,
    )
    return run_dir
