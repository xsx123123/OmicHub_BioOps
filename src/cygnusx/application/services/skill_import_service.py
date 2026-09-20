"""技能导入应用服务 —— 五入口统一"先解析预览、确认后入库"

入口：技能市场（仓库内置）/ GitHub 仓库或子目录 URL / 本地 zip 上传 / Markdown 文件 / JSON 粘贴（兼容）。
解析产出 SkillImportPreviewDTO；确认后写 data/ai/skills/<skill_id>/ 文件夹 + skills 表。
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.skill import (
    AliyunMarketplaceStatusDTO,
    SkillDTO,
    SkillImportPreviewDTO,
    SkillMarketplaceItemDTO,
    SkillUpdateCheckDTO,
)
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.infrastructure.database.models.skill import SkillModel
from cygnusx.infrastructure.skills.skill_store import remove_skill_folder, write_skill_folder
from cygnusx.infrastructure.skills.skillmd import (
    BODY_SOFT_LIMIT_CHARS,
    ParsedSkill,
    SkillFileEntry,
    SkillParseError,
    parse_skill_folder,
    parsed_from_legacy_json,
    slugify_skill_id,
)

# zip 解压总量护栏（防 zip bomb 打爆内存；技能包本身上限 1MiB）
MAX_ZIP_TOTAL_BYTES = 4 * 1024 * 1024
# 阿里云官方源整仓同步总量护栏（官方 Skills 仓库为纯文本，远小于此）
MAX_ALIYUN_SYNC_BYTES = 16 * 1024 * 1024
# 提取规则变更时强制重新索引缓存，即使上游 commit 尚未变化。
ALIYUN_SKILL_EXTRACTOR_VERSION = 2
GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {"User-Agent": "CygnusX-SkillImporter", "Accept": "application/vnd.github+json"}
HTTP_TIMEOUT = 30.0


class SkillImportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ---------- 解析入口（均产出预览，不落库） ----------

    async def parse_from_json(self, text: str) -> SkillImportPreviewDTO:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SkillParseError(f"JSON 解析失败: {exc}") from exc
        if not isinstance(obj, dict):
            raise SkillParseError("JSON 配置必须是对象")
        parsed = parsed_from_legacy_json(obj)
        parsed.source_type = "json"
        return self._preview(parsed, source_type="json")

    async def parse_from_zip(self, data: bytes) -> SkillImportPreviewDTO:
        files: dict[str, bytes] = {}
        total = 0
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    name = info.filename
                    if info.is_dir() or name.startswith("/") or ".." in name.split("/"):
                        continue
                    total += info.file_size
                    if total > MAX_ZIP_TOTAL_BYTES:
                        raise SkillParseError("zip 解压后总量超过 4MB 上限")
                    files[name] = zf.read(info)
        except zipfile.BadZipFile as exc:
            raise SkillParseError("不是有效的 zip 文件") from exc
        try:
            parsed = parse_skill_folder(files, source_type="zip")
        except SkillParseError as exc:
            markdown_files = [
                (path, content)
                for path, content in files.items()
                if path.lower().endswith(".md") and Path(path).name.lower() != "skill.md"
            ]
            if "未找到 SKILL.md" not in str(exc) or len(markdown_files) != 1:
                raise
            filename, markdown = markdown_files[0]
            preview = await self.parse_from_markdown(markdown, filename)
            preview.source_type = "zip"
            preview.warnings.insert(
                0,
                "检测到 ZIP 内仅包含一份 Markdown 指令文件，已按 Markdown 技能导入处理。",
            )
            return preview
        return self._preview(parsed, source_type="zip")

    async def parse_from_markdown(self, data: bytes, filename: str) -> SkillImportPreviewDTO:
        """Convert a standalone Markdown instruction file into a standard Skill preview."""
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SkillParseError("Markdown 文件不是有效的 UTF-8 文本") from exc
        body = text.strip()
        if not body:
            raise SkillParseError("Markdown 文件内容为空")

        safe_name = Path(filename or "skill.md").name
        stem = Path(safe_name).stem.strip() or "skill"
        # Existing SKILL.md files retain their frontmatter when valid; ordinary
        # Markdown is deliberately accepted without any packaging convention.
        if body.startswith("---"):
            try:
                parsed = parse_skill_folder({"SKILL.md": data}, source_type="markdown")
                return self._preview(parsed, source_type="markdown")
            except SkillParseError:
                pass

        name = re.sub(r"[-_]+", " ", stem).strip() or "未命名技能"
        warnings = [
            "已将独立 Markdown 作为技能指令正文；请在预览中补全名称、版本和描述后确认导入。"
        ]
        if len(body) > BODY_SOFT_LIMIT_CHARS:
            warnings.append(
                f"正文约 {len(body) // 4} tokens，超过建议上限 5000 tokens，"
                "建议将细节拆分到 references/ 按需加载"
            )
        parsed = ParsedSkill(
            skill_id=slugify_skill_id(stem),
            name=name,
            description="",
            body=body,
            files=[
                SkillFileEntry(
                    path="SKILL.md",
                    size=len(data),
                    kind="skill_md",
                    content=body,
                )
            ],
            warnings=warnings,
        )
        return self._preview(parsed, source_type="markdown")

    async def parse_from_github(self, url: str) -> SkillImportPreviewDTO:
        files, source_ref, source_commit = await self._fetch_github(url.strip())
        parsed = parse_skill_folder(files, source_type="github", source_ref=source_ref)
        return self._preview(
            parsed, source_type="github", source_ref=source_ref, source_commit=source_commit
        )

    # ---------- 市场 ----------

    async def list_marketplace(self) -> list[SkillMarketplaceItemDTO]:
        """市场列表 = 平台内置源 + 阿里云官方源（本地同步缓存，列表不触网）"""
        items: list[SkillMarketplaceItemDTO] = []
        items.extend(await self._list_market_dir(Path(get_settings().skill_marketplace_dir)))
        if not get_settings().aliyun_skills_enabled:
            return items
        # AgentExplorer API 的目录元数据存于 manifest；历史 GitHub 缓存保留兼容读取。
        aliyun_items = await self._list_aliyun_catalog()
        if aliyun_items:
            items.extend(aliyun_items)
        else:
            items.extend(
                await self._list_market_dir(
                    Path(get_settings().aliyun_skills_cache_dir),
                    source="aliyun_official",
                    official=True,
                )
            )
        return items

    async def _list_market_dir(
        self,
        market_dir: Path,
        *,
        source: str = "builtin",
        official: bool = False,
    ) -> list[SkillMarketplaceItemDTO]:
        items: list[SkillMarketplaceItemDTO] = []
        if market_dir.is_dir():
            category_map = _builtin_category_map(market_dir) if source == "builtin" else {}
            folders: list[tuple[Path, ParsedSkill]] = []
            for folder in sorted(market_dir.iterdir()):
                skill_md = folder / "SKILL.md"
                if not folder.is_dir() or not skill_md.is_file():
                    continue
                try:
                    parsed = self._read_folder(folder)
                except SkillParseError:
                    continue
                folders.append((folder, parsed))

            installed_ids = await self._installed_ids([folder.name for folder, _ in folders])
            for folder, parsed in folders:
                items.append(
                    SkillMarketplaceItemDTO(
                        # 市场以文件夹名为安装键（frontmatter 无显式 skill_id 时
                        # 派生 ID 可能是中文名，与文件夹名不一致）
                        skill_id=folder.name,
                        name=parsed.name,
                        description=parsed.description,
                        icon=parsed.icon,
                        category=_resolve_market_category(
                            folder.name, category_map.get(folder.name, parsed.category)
                        ),
                        version=parsed.version,
                        author=parsed.author,
                        has_scripts=parsed.has_scripts,
                        installed=folder.name in installed_ids,
                        source=source,
                        official=official,
                    )
                )
        return items

    async def install_marketplace(self, skill_id: str, overwrite: bool = False) -> SkillDTO:
        market_dir = Path(get_settings().skill_marketplace_dir)
        folder = (market_dir / skill_id).resolve()
        if (
            not str(folder).startswith(str(market_dir.resolve()))
            or not (folder / "SKILL.md").is_file()
        ):
            raise NotFoundError(f"市场技能 '{skill_id}' 不存在")
        parsed = self._read_folder(folder)
        preview = self._preview(
            parsed, source_type="market", source_ref=f"builtin://{skill_id}"
        )
        preview.skill_id = skill_id  # 文件夹名为规范键，保证 DB/磁盘/市场三处一致
        preview.category = _resolve_market_category(
            skill_id, _builtin_category_map(market_dir).get(skill_id, preview.category)
        )
        return await self.confirm_import(preview, overwrite=overwrite)

    # ---------- 阿里云官方技能源（市场第二分组） ----------

    async def aliyun_status(self) -> AliyunMarketplaceStatusDTO:
        """官方源状态：本地缓存条目数 + 同步元数据 + 过期标记（不触网）"""
        if not get_settings().aliyun_skills_enabled:
            return AliyunMarketplaceStatusDTO(enabled=False, available=False)
        return self._build_aliyun_status()

    async def sync_aliyun_marketplace(self, force: bool = False) -> AliyunMarketplaceStatusDTO:
        """同步阿里云官方 Skills 目录到本地缓存。

        - 配置 AccessKey 时走 AgentExplorer OpenAPI；否则回退 GitHub 仓库同步
        - 上游 commit 未变且非强制：GitHub 回退源直接返回当前状态（幂等，可高频调用）
        - 下载/解析成功后整体替换缓存文件夹 + 写 manifest（旧缓存只在成功后删除）
        - 网络失败：保留旧缓存、记录 last_error，内置条目与已缓存条目不受影响
        """
        settings = get_settings()
        if not settings.aliyun_skills_enabled:
            return AliyunMarketplaceStatusDTO(enabled=False, available=False)
        if settings.aliyun_skills_access_key_id and settings.aliyun_skills_access_key_secret:
            return await self._sync_agentexplorer_marketplace(force=force)
        cache_dir = Path(settings.aliyun_skills_cache_dir)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return self._aliyun_cache_error_status(cache_dir, exc)
        repo = settings.aliyun_skills_repo
        branch = settings.aliyun_skills_branch
        manifest_path = cache_dir / "manifest.json"
        manifest = _read_json(manifest_path)

        try:
            owner, _, repo_name = repo.partition("/")
            if not owner or not repo_name:
                raise SkillParseError(f"配置 aliyun_skills_repo 非法: {repo}（应为 owner/repo）")
            latest = await self._latest_commit(owner, repo_name, branch)
            if not latest:
                # 配置分支拉取失败：回落仓库默认分支（如 main → master）
                fallback = await self._default_branch(owner, repo_name)
                if fallback and fallback != branch:
                    logger.info("官方源分支 {} 不可用，回落默认分支 {}", branch, fallback)
                    branch = fallback
                    latest = await self._latest_commit(owner, repo_name, branch)
            if not latest:
                raise SkillParseError("无法获取上游仓库最新 commit（网络不可达或仓库不存在）")
            if (
                manifest.get("commit") == latest
                and manifest.get("extractor_version") == ALIYUN_SKILL_EXTRACTOR_VERSION
                and not force
            ):
                return self._build_aliyun_status()  # 已是最新，跳过下载
            tar_url = f"https://codeload.github.com/{repo}/tar.gz/refs/heads/{branch}"
            async with httpx.AsyncClient(timeout=60.0, headers=GITHUB_HEADERS) as client:
                resp = await client.get(tar_url)
                if resp.status_code == 404:
                    raise SkillParseError(f"仓库或分支不存在: {repo}@{branch}")
                resp.raise_for_status()
                blob = resp.content
            skills = _extract_aliyun_skills(blob)
            if not skills:
                raise SkillParseError(f"仓库 {repo} 中未找到包含 SKILL.md 的技能目录")
            # 成功后才整体替换缓存
            for sub in cache_dir.iterdir():
                if sub.is_dir():
                    shutil.rmtree(sub, ignore_errors=True)
            for folder_name, files in skills.items():
                target = cache_dir / folder_name
                target.mkdir(parents=True, exist_ok=True)
                for rel, content in files.items():
                    rel_path = Path(rel)
                    if rel_path.is_absolute() or ".." in rel_path.parts:
                        continue
                    dest = target / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
            _write_json(
                manifest_path,
                {
                    "repo": repo,
                    "branch": branch,
                    "commit": latest,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "count": len(skills),
                    "extractor_version": ALIYUN_SKILL_EXTRACTOR_VERSION,
                },
            )
            logger.info(
                "阿里云官方技能源同步完成: repo={} commit={} skills={}",
                repo,
                latest,
                len(skills),
            )
        except (httpx.HTTPError, SkillParseError) as exc:
            # 同步失败不清缓存：manifest 追加错误信息供前端空态展示
            manifest["last_error"] = str(exc)
            manifest["last_error_at"] = datetime.now(timezone.utc).isoformat()
            manifest.setdefault("repo", repo)
            manifest.setdefault("branch", branch)
            _write_json(manifest_path, manifest)
            logger.warning("阿里云官方技能源同步失败（保留旧缓存）: {}", exc)
        return self._build_aliyun_status()

    async def _sync_agentexplorer_marketplace(
        self, *, force: bool
    ) -> AliyunMarketplaceStatusDTO:
        """使用 AgentExplorer SearchSkills API 分页同步官方目录元数据。"""
        settings = get_settings()
        cache_dir = Path(settings.aliyun_skills_cache_dir)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return self._aliyun_cache_error_status(cache_dir, exc)
        manifest_path = cache_dir / "manifest.json"
        manifest = _read_json(manifest_path)
        try:
            catalog = await self._search_agentexplorer_skills()
            if not catalog:
                raise SkillParseError("AgentExplorer 未返回任何官方 Skill")
            _write_json(
                manifest_path,
                {
                    "provider": "agentexplorer_api",
                    "repo": "AgentExplorer OpenAPI",
                    "branch": settings.aliyun_skills_region_id,
                    "commit": "",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "count": len(catalog),
                    "items": catalog,
                },
            )
            logger.info("阿里云 AgentExplorer 官方目录同步完成: skills={}", len(catalog))
        except Exception as exc:
            manifest["last_error"] = str(exc)
            manifest["last_error_at"] = datetime.now(timezone.utc).isoformat()
            manifest.setdefault("provider", "agentexplorer_api")
            manifest.setdefault("repo", "AgentExplorer OpenAPI")
            manifest.setdefault("branch", settings.aliyun_skills_region_id)
            _write_json(manifest_path, manifest)
            logger.warning("阿里云 AgentExplorer 官方目录同步失败（保留旧缓存）: {}", exc)
        return self._build_aliyun_status()

    def _aliyun_cache_error_status(
        self, cache_dir: Path, exc: OSError
    ) -> AliyunMarketplaceStatusDTO:
        """缓存卷不可写时返回可展示错误，避免同步接口因写 manifest 而变成 500。"""
        settings = get_settings()
        message = f"阿里云官方 Skill 缓存目录不可写: {cache_dir}（{exc.strerror or exc}）"
        logger.error(message)
        return AliyunMarketplaceStatusDTO(
            available=False,
            repo="AgentExplorer OpenAPI",
            branch=settings.aliyun_skills_region_id,
            stale=True,
            error=message,
        )

    async def _list_aliyun_catalog(self) -> list[SkillMarketplaceItemDTO]:
        manifest = _read_json(Path(get_settings().aliyun_skills_cache_dir) / "manifest.json")
        if manifest.get("provider") != "agentexplorer_api":
            return []
        raw_items = manifest.get("items")
        if not isinstance(raw_items, list):
            return []
        items: list[SkillMarketplaceItemDTO] = []
        normalized_items: list[tuple[dict, str, str]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            skill_id = str(raw.get("skill_name") or "").strip()
            if not skill_id:
                continue
            category = str(
                raw.get("sub_category_name") or raw.get("category_name") or "general"
            )
            normalized_items.append((raw, skill_id, category))

        installed_ids = await self._installed_ids([skill_id for _, skill_id, _ in normalized_items])
        for raw, skill_id, category in normalized_items:
            items.append(
                SkillMarketplaceItemDTO(
                    skill_id=skill_id,
                    name=str(raw.get("display_name") or skill_id),
                    description=str(raw.get("description") or ""),
                    icon="☁️",
                    category=category,
                    version=str(raw.get("updated_at") or ""),
                    author="阿里云官方",
                    has_scripts=False,
                    installed=skill_id in installed_ids,
                    source="aliyun_official",
                    official=True,
                )
            )
        return items

    async def install_aliyun(self, skill_id: str, overwrite: bool = False) -> SkillDTO:
        """从官方源本地缓存安装技能，走统一的预览校验入库流程。"""
        settings = get_settings()
        if not settings.aliyun_skills_enabled:
            raise NotFoundError("阿里云官方技能源未启用（ALIYUN_SKILLS_ENABLED=false）")
        cache_dir = Path(settings.aliyun_skills_cache_dir)
        manifest = _read_json(cache_dir / "manifest.json")
        if manifest.get("provider") == "agentexplorer_api":
            return await self._install_agentexplorer_skill(
                skill_id, manifest=manifest, overwrite=overwrite
            )
        folder = (cache_dir / skill_id).resolve()
        if (
            not str(folder).startswith(str(cache_dir.resolve()))
            or not (folder / "SKILL.md").is_file()
        ):
            raise NotFoundError(f"阿里云官方技能 '{skill_id}' 不存在，请先同步官方源")
        repo = manifest.get("repo") or settings.aliyun_skills_repo
        branch = manifest.get("branch") or settings.aliyun_skills_branch
        source_ref = f"https://github.com/{repo}/tree/{branch}/{skill_id}"
        parsed = self._read_folder(folder)
        preview = self._preview(
            parsed,
            source_type="aliyun_official",
            source_ref=source_ref,
            source_commit=manifest.get("commit") or "",
        )
        preview.skill_id = skill_id  # 缓存文件夹名为规范键
        preview.category = _aliyun_category(manifest, skill_id, preview.category)
        return await self.confirm_import(preview, overwrite=overwrite)

    async def _install_agentexplorer_skill(
        self, skill_id: str, *, manifest: dict, overwrite: bool
    ) -> SkillDTO:
        catalog = manifest.get("items")
        item = (
            next(
                (
                    value
                    for value in catalog
                    if isinstance(value, dict) and value.get("skill_name") == skill_id
                ),
                None,
            )
            if isinstance(catalog, list)
            else None
        )
        if item is None:
            raise NotFoundError(f"阿里云官方技能 '{skill_id}' 不存在，请先同步官方源")
        content = await self._get_agentexplorer_skill_content(skill_id)
        parsed = parse_skill_folder(
            {"SKILL.md": content.encode("utf-8")},
            source_type="aliyun_official",
            source_ref=f"aliyun://agentexplorer/skills/{skill_id}",
        )
        preview = self._preview(
            parsed,
            source_type="aliyun_official",
            source_ref=f"aliyun://agentexplorer/skills/{skill_id}",
            source_commit=str(item.get("updated_at") or ""),
        )
        preview.skill_id = skill_id
        preview.category = str(
            item.get("sub_category_name") or item.get("category_name") or preview.category
        )
        return await self.confirm_import(preview, overwrite=overwrite)

    def _agentexplorer_client(self):
        """延迟加载官方 SDK，避免未启用官方源的部署承担导入成本。"""
        settings = get_settings()
        if not settings.aliyun_skills_access_key_id or not settings.aliyun_skills_access_key_secret:
            raise SkillParseError(
                "未配置阿里云 AccessKey：请设置 ALIYUN_SKILLS_ACCESS_KEY_ID 和 "
                "ALIYUN_SKILLS_ACCESS_KEY_SECRET"
            )
        try:
            from alibabacloud_agentexplorer20260317.client import Client
            from alibabacloud_tea_openapi import utils_models as open_api_models
        except ImportError as exc:
            raise SkillParseError(
                "未安装 AgentExplorer SDK，请安装 alibabacloud_agentexplorer20260317"
            ) from exc
        config = open_api_models.Config(
            access_key_id=settings.aliyun_skills_access_key_id,
            access_key_secret=settings.aliyun_skills_access_key_secret,
            region_id=settings.aliyun_skills_region_id,
        )
        return Client(config)

    async def _search_agentexplorer_skills(self) -> list[dict[str, str]]:
        """调用 SearchSkills，持续使用 nextToken 直至取完官方目录。"""
        try:
            from alibabacloud_agentexplorer20260317 import models as agentexplorer_models
        except ImportError as exc:
            raise SkillParseError(
                "未安装 AgentExplorer SDK，请安装 alibabacloud_agentexplorer20260317"
            ) from exc
        client = self._agentexplorer_client()
        next_token: str | None = None
        seen_tokens: set[str] = set()
        catalog: list[dict[str, str]] = []
        while True:
            response = await client.search_skills_async(
                agentexplorer_models.SearchSkillsRequest(max_results=100, next_token=next_token)
            )
            body = response.body
            for skill in body.data or []:
                skill_name = str(skill.skill_name or "").strip()
                if not skill_name:
                    continue
                catalog.append(
                    {
                        "skill_name": skill_name,
                        "display_name": str(skill.display_name or skill_name),
                        "description": str(skill.description or ""),
                        "category_name": str(skill.category_name or ""),
                        "sub_category_name": str(skill.sub_category_name or ""),
                        "updated_at": str(skill.updated_at or ""),
                    }
                )
            next_token = str(body.next_token or "").strip() or None
            if not next_token:
                break
            if next_token in seen_tokens:
                raise SkillParseError("AgentExplorer 返回了重复的 nextToken，已停止分页以避免循环")
            seen_tokens.add(next_token)
        return catalog

    async def _get_agentexplorer_skill_content(self, skill_id: str) -> str:
        try:
            from alibabacloud_agentexplorer20260317 import models as agentexplorer_models
        except ImportError as exc:
            raise SkillParseError(
                "未安装 AgentExplorer SDK，请安装 alibabacloud_agentexplorer20260317"
            ) from exc
        response = await self._agentexplorer_client().get_skill_content_async(
            skill_id, agentexplorer_models.GetSkillContentRequest()
        )
        content = str(response.body.content or "")
        if not content.strip():
            raise SkillParseError(f"阿里云官方技能 '{skill_id}' 未返回 SKILL.md 内容")
        return content

    def _build_aliyun_status(self) -> AliyunMarketplaceStatusDTO:
        settings = get_settings()
        cache_dir = Path(settings.aliyun_skills_cache_dir)
        manifest = _read_json(cache_dir / "manifest.json") if cache_dir.is_dir() else {}
        catalog = manifest.get("items")
        count = (
            len(catalog)
            if manifest.get("provider") == "agentexplorer_api" and isinstance(catalog, list)
            else sum(1 for p in cache_dir.glob("*/SKILL.md")) if cache_dir.is_dir() else 0
        )
        synced_at: datetime | None = None
        raw_synced = manifest.get("synced_at")
        if raw_synced:
            try:
                synced_at = datetime.fromisoformat(str(raw_synced))
            except ValueError:
                synced_at = None
        stale = True
        if synced_at is not None:
            base = synced_at if synced_at.tzinfo else synced_at.replace(tzinfo=timezone.utc)
            stale = (datetime.now(timezone.utc) - base).total_seconds() > settings.aliyun_skills_cache_ttl
        return AliyunMarketplaceStatusDTO(
            available=count > 0,
            count=count,
            repo=str(manifest.get("repo") or settings.aliyun_skills_repo),
            branch=str(manifest.get("branch") or settings.aliyun_skills_branch),
            commit=str(manifest.get("commit") or ""),
            last_synced_at=synced_at,
            stale=stale,
            error=str(manifest.get("last_error") or ""),
        )

    # ---------- 确认入库 ----------

    async def confirm_import(
        self, preview: SkillImportPreviewDTO, overwrite: bool = False
    ) -> SkillDTO:
        preview.name = preview.name.strip()
        preview.description = preview.description.strip()
        preview.version = preview.version.strip()
        if not preview.name:
            raise SkillParseError("请填写技能名称")
        if not preview.description:
            raise SkillParseError("请填写技能描述（用于判断何时调用该技能）")
        parsed = ParsedSkill.from_preview_dict(preview.model_dump())
        existing = await self._get_model(parsed.skill_id)
        if existing and not overwrite:
            raise BusinessError(
                f"技能 '{parsed.skill_id}' 已存在（可开启覆盖导入以升级到新版本）"
            )

        write_skill_folder(parsed)

        if existing:
            existing.name = parsed.name
            existing.description = parsed.description
            existing.prompt = parsed.body
            existing.icon = parsed.icon
            existing.category = parsed.category
            existing.version = parsed.version or None
            existing.author = parsed.author or None
            existing.source_type = preview.source_type
            existing.source_ref = preview.source_ref or None
            existing.source_commit = preview.source_commit or None
            existing.has_scripts = parsed.has_scripts
            existing.frontmatter = parsed.frontmatter or None
            model = existing
        else:
            model = SkillModel(
                id=uuid.uuid4(),
                skill_id=parsed.skill_id,
                name=parsed.name,
                description=parsed.description,
                prompt=parsed.body,
                icon=parsed.icon,
                category=parsed.category,
                is_active=True,
                is_builtin=False,
                version=parsed.version or None,
                author=parsed.author or None,
                source_type=preview.source_type,
                source_ref=preview.source_ref or None,
                source_commit=preview.source_commit or None,
                has_scripts=parsed.has_scripts,
                frontmatter=parsed.frontmatter or None,
            )
            self._db.add(model)
        await self._db.flush()
        from cygnusx.application.services.skill_service import SkillService, _snapshot_skill

        # 版本留档：覆盖升级为 import 快照；新装技能不经 create_skill，也在此留首版
        await _snapshot_skill(
            self._db,
            model,
            source="import",
            changelog="导入覆盖升级" if existing else "导入技能",
        )
        await self._db.flush()
        return SkillService._to_dto(model)

    async def delete_skill_folder(self, skill_id: str) -> None:
        """删除技能时同步清理磁盘文件夹（由 SkillService.delete_skill 调用）"""
        remove_skill_folder(skill_id)

    # ---------- 检查更新 ----------

    async def check_update(self, skill_id: str) -> SkillUpdateCheckDTO:
        model = await self._get_model(skill_id)
        if model is None:
            raise NotFoundError(f"技能 '{skill_id}' 不存在")
        current_commit = model.source_commit or ""
        if model.source_type not in ("github", "aliyun_official") or not model.source_ref:
            return SkillUpdateCheckDTO(
                has_update=False,
                current_version=model.version or "",
                current_commit=current_commit,
                source_ref=model.source_ref or "",
                message="该技能来源不支持自动检查更新",
            )
        # 阿里云官方源：基于本地同步目录零网络比对版本。
        if model.source_type == "aliyun_official":
            manifest = _read_json(
                Path(get_settings().aliyun_skills_cache_dir) / "manifest.json"
            )
            if manifest.get("provider") == "agentexplorer_api":
                catalog = manifest.get("items")
                item = next(
                    (
                        value
                        for value in catalog
                        if isinstance(value, dict) and value.get("skill_name") == skill_id
                    ),
                    None,
                ) if isinstance(catalog, list) else None
                latest = str(item.get("updated_at") or "") if item else ""
                if latest:
                    has_update = bool(current_commit) and latest != current_commit
                    return SkillUpdateCheckDTO(
                        has_update=has_update,
                        current_version=model.version or "",
                        current_commit=current_commit,
                        latest_commit=latest,
                        source_ref=model.source_ref or "",
                        message=(
                            "官方源有新版本，可在技能市场重新安装升级"
                            if has_update
                            else "已是最新（基于本地同步目录）"
                        ),
                    )
            latest = str(manifest.get("commit") or "")
            if latest:
                has_update = bool(current_commit) and latest != current_commit
                return SkillUpdateCheckDTO(
                    has_update=has_update,
                    current_version=model.version or "",
                    current_commit=current_commit,
                    latest_commit=latest[:12],
                    source_ref=model.source_ref or "",
                    message=(
                        "官方源有新版本，可在技能市场重新安装升级"
                        if has_update
                        else "已是最新（基于本地同步缓存）"
                    ),
                )
        info = _parse_github_url(model.source_ref)
        if info is None:
            return SkillUpdateCheckDTO(
                has_update=False,
                current_version=model.version or "",
                current_commit=current_commit,
                source_ref=model.source_ref or "",
                message="无法解析来源 URL",
            )
        owner, repo, branch, _sub = info
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=GITHUB_HEADERS) as client:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{owner}/{repo}/commits",
                    params={"sha": branch or "HEAD", "per_page": 1},
                )
                resp.raise_for_status()
                latest = (resp.json() or [{}])[0].get("sha", "")
        except httpx.HTTPError as exc:
            raise BusinessError(f"查询上游更新失败: {exc}") from exc
        has_update = bool(latest) and bool(current_commit) and latest != current_commit
        return SkillUpdateCheckDTO(
            has_update=has_update,
            current_version=model.version or "",
            current_commit=current_commit,
            latest_commit=latest[:12],
            source_ref=model.source_ref,
            message="发现上游新提交，可重新导入升级" if has_update else "已是最新",
        )

    # ---------- 内部工具 ----------

    def _preview(
        self,
        parsed: ParsedSkill,
        *,
        source_type: str,
        source_ref: str = "",
        source_commit: str = "",
    ) -> SkillImportPreviewDTO:
        data = parsed.to_preview_dict()
        return SkillImportPreviewDTO(
            **{k: v for k, v in data.items() if k != "source_type"},
            source_type=source_type,
            source_ref=source_ref,
            source_commit=source_commit,
        )

    async def _exists(self, skill_id: str) -> bool:
        return await self._get_model(skill_id) is not None

    async def _installed_ids(self, skill_ids: list[str]) -> set[str]:
        if not skill_ids:
            return set()
        result = await self._db.execute(
            select(SkillModel.skill_id).where(SkillModel.skill_id.in_(skill_ids))
        )
        return {str(skill_id) for skill_id in result.scalars().all()}

    async def _get_model(self, skill_id: str) -> SkillModel | None:
        result = await self._db.execute(
            select(SkillModel).where(SkillModel.skill_id == skill_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _read_folder(folder: Path) -> ParsedSkill:
        files: dict[str, bytes] = {}
        total = 0
        base = folder.resolve()
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(base)).replace("\\", "/")
            size = path.stat().st_size
            total += size
            if total > MAX_ZIP_TOTAL_BYTES:
                raise SkillParseError("技能文件夹超过 4MB 上限")
            files[rel] = path.read_bytes()
        return parse_skill_folder(files)

    async def _fetch_github(
        self, url: str
    ) -> tuple[dict[str, bytes], str, str]:
        """拉取 GitHub 技能文件夹。返回 (files, source_ref, source_commit)"""
        info = _parse_github_url(url)
        if info is None:
            raise SkillParseError(
                "无法识别的 GitHub 链接，支持：仓库主页 / tree 分支或子目录 / blob 指向 SKILL.md / raw 文件"
            )
        owner, repo, branch, subpath = info
        source_ref = f"https://github.com/{owner}/{repo}"

        # 单文件：blob/raw 直指 SKILL.md
        if subpath and subpath.lower().endswith("skill.md"):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{subpath}"
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=GITHUB_HEADERS) as client:
                resp = await client.get(raw_url)
                if resp.status_code == 404:
                    raise SkillParseError(f"文件不存在: {raw_url}")
                resp.raise_for_status()
                content = resp.content
            commit = await self._latest_commit(owner, repo, branch)
            return {"SKILL.md": content}, source_ref, commit

        # 文件夹：codeload tar.gz 整仓解压后按子路径过滤
        use_branch = branch or await self._default_branch(owner, repo)
        tar_url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/heads/{use_branch}"
        async with httpx.AsyncClient(timeout=60.0, headers=GITHUB_HEADERS) as client:
            resp = await client.get(tar_url)
            if resp.status_code == 404:
                raise SkillParseError(f"仓库或分支不存在: {owner}/{repo}@{use_branch}")
            resp.raise_for_status()
            blob = resp.content

        files = _extract_tar_subdir(blob, subpath)
        if not files:
            where = f"{subpath}/" if subpath else "仓库根目录"
            raise SkillParseError(f"{where} 下未找到技能文件（需包含 SKILL.md）")
        commit = await self._latest_commit(owner, repo, use_branch)
        if subpath:
            source_ref = f"{source_ref}/tree/{use_branch}/{subpath}"
        return files, source_ref, commit

    @staticmethod
    async def _default_branch(owner: str, repo: str) -> str:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=GITHUB_HEADERS) as client:
            resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}")
            if resp.status_code == 404:
                raise SkillParseError(f"仓库不存在: {owner}/{repo}")
            resp.raise_for_status()
            return str(resp.json().get("default_branch") or "main")

    @staticmethod
    async def _latest_commit(owner: str, repo: str, branch: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=GITHUB_HEADERS) as client:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{owner}/{repo}/commits",
                    params={"sha": branch or "HEAD", "per_page": 1},
                )
                resp.raise_for_status()
                data = resp.json()
                return str((data or [{}])[0].get("sha", ""))[:12]
        except httpx.HTTPError:
            return ""


_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)"
    r"(?:\.git)?(?:/(?P<kind>tree|blob)/(?P<branch>[^/\s]+)(?P<sub>/[^\s]*)?)?/?$",
    re.IGNORECASE,
)
_RAW_URL_RE = re.compile(
    r"^(?:https?://)?raw\.githubusercontent\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)"
    r"/(?P<branch>[^/\s]+)(?P<sub>/[^\s]+)$",
    re.IGNORECASE,
)


def _parse_github_url(url: str) -> tuple[str, str, str, str] | None:
    """→ (owner, repo, branch, subpath)，branch/subpath 可能为空串"""
    url = url.strip().rstrip("/")
    m = _RAW_URL_RE.match(url)
    if m:
        return m["owner"], m["repo"], m["branch"], m["sub"].lstrip("/")
    m = _GITHUB_URL_RE.match(url + ("/" if url.endswith(".git") else ""))
    if not m:
        return None
    kind = (m["kind"] or "").lower()
    branch = m["branch"] or ""
    sub = (m["sub"] or "").strip("/")
    if kind == "" and (branch or sub):
        return None
    return m["owner"], m["repo"], branch, sub


def _extract_tar_subdir(blob: bytes, subpath: str) -> dict[str, bytes]:
    """从 codeload tar.gz 中提取 {repo}-{branch}/[subpath]/ 下的文件"""
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        root_prefix = ""
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name
            if ".." in name.split("/") or name.startswith("/"):
                continue
            if not root_prefix:
                root_prefix = name.split("/", 1)[0] + "/"
            rel = name[len(root_prefix):] if name.startswith(root_prefix) else name
            if subpath:
                if not rel.startswith(f"{subpath}/"):
                    continue
                rel = rel[len(subpath) + 1:]
            if not rel:
                continue
            total += member.size
            if total > MAX_ZIP_TOTAL_BYTES:
                raise SkillParseError("仓库目标目录超过 4MB 上限")
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[rel] = extracted.read()
    return files


# ---------- 阿里云官方源同步辅助 ----------


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, obj: dict) -> None:
    """原子写：先落临时文件再 rename，避免读到半截 manifest"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _builtin_category_map(market_dir: Path) -> dict[str, str]:
    """Recover the source taxonomy for bioSkills published as flat market folders."""
    source_root = market_dir.parents[2] / "skills" / "bio_skills"
    if not source_root.is_dir():
        return {}
    result: dict[str, str] = {}
    for skill_md in source_root.glob("*/*/SKILL.md"):
        skill_dir = skill_md.parent
        category = skill_dir.parent.name
        skill_id = f"bio-{category}-{skill_dir.name}"
        result[skill_id] = category
    return result


def _resolve_market_category(skill_id: str, fallback: str) -> str:
    """bio- 前缀的技能统一归入 analysis 类别（其余沿用原解析结果）。"""
    if skill_id.startswith("bio-"):
        return "analysis"
    return fallback


def _aliyun_category(manifest: dict, skill_id: str, fallback: str = "general") -> str:
    for item in manifest.get("items", []):
        if isinstance(item, dict) and str(item.get("skill_name") or "") == skill_id:
            return str(
                item.get("sub_category_name") or item.get("category_name") or fallback
            )
    return fallback


def _extract_aliyun_skills(blob: bytes) -> dict[str, dict[str, bytes]]:
    """扫描整仓 tar.gz，提取所有含 SKILL.md 的目录为技能文件夹。

    返回 {技能文件夹名: {相对路径: 内容}}。不假定仓库布局：
    支持任意嵌套层级的 <path>/<skill>/SKILL.md，不假定上游仓库目录布局。
    同名文件夹冲突保留先出现者；单技能超 4MB 跳过；整仓超 16MB 报错。
    """
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        root_prefix = ""
        entries: list[tuple[str, tarfile.TarInfo]] = []
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name
            if ".." in name.split("/") or name.startswith("/"):
                continue
            if not root_prefix:
                root_prefix = name.split("/", 1)[0] + "/"
            rel = name[len(root_prefix):] if name.startswith(root_prefix) else name
            if rel:
                entries.append((rel, member))

        skills: dict[str, dict[str, bytes]] = {}
        total = 0
        # 技能目录 = 含 SKILL.md 的目录（按出现顺序）
        skill_dirs: list[str] = []
        for rel, _ in entries:
            parts = rel.split("/")
            if parts[-1].lower() != "skill.md" or not parts[:-1]:
                continue
            prefix = "/".join(parts[:-1])
            if prefix not in skill_dirs:
                skill_dirs.append(prefix)
        for prefix in skill_dirs:
            folder_name = prefix.rsplit("/", 1)[-1]
            if folder_name in skills:
                continue  # 同名冲突：保留先出现者
            dir_prefix = prefix + "/"
            files: dict[str, bytes] = {}
            folder_total = 0
            oversized = False
            for rel, member in entries:
                if not rel.startswith(dir_prefix):
                    continue
                sub = rel[len(dir_prefix):]
                if not sub:
                    continue
                folder_total += member.size
                if folder_total > MAX_ZIP_TOTAL_BYTES:
                    oversized = True
                    break
                total += member.size
                if total > MAX_ALIYUN_SYNC_BYTES:
                    raise SkillParseError(
                        f"官方源仓库超过 {MAX_ALIYUN_SYNC_BYTES // 1024 // 1024}MB 同步上限"
                    )
                extracted = tar.extractfile(member)
                if extracted is not None:
                    files[sub] = extracted.read()
            if oversized:
                logger.warning("官方源技能 {} 超过单技能 4MB 上限，已跳过", folder_name)
                continue
            if files.get("SKILL.md"):
                skills[folder_name] = files
        return skills
