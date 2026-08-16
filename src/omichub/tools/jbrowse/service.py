"""JBrowse 2 业务服务层 —— 配置生成 / 文件扫描 / 索引检查 / 上传资格校验。

设计要点：
- 服务无状态、不依赖 DB（用户身份由 API 层 JWT 注入，user_id 作为目录归属依据）；
- 所有文件系统操作（scan / stat / 索引检查）走 asyncio.to_thread，避免阻塞事件循环；
- 生成浏览器配置时，对用户提交的轨道路径做【归属校验】：只允许 /data/omichub/users/{user_id}/
  下的文件，拒绝越权读取他人数据（/tracks/ 虽由 nginx 静态暴露，但配置层不主动协助越权）；
- 轨道 URI 一律经 to_tracks_uri 换算，与 storage_config.data_root 保持单一数据源。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from omichub.core.exceptions import NotFoundError, ValidationError
from omichub.infrastructure.config.storage_config import get_storage_config
from omichub.tools.jbrowse.config import (
    AssemblyConfig,
    ConfigManager,
    TrackConfig,
    config_manager,
    to_tracks_uri,
)
from omichub.tools.jbrowse.schema import (
    AssemblyDetailDTO,
    AssemblyDTO,
    PresetTrackDTO,
    ScannedFileDTO,
)

# Nginx 暴露的数据路径前缀（与 nginx.conf 的 location /tracks/ 对应）
_TRACKS_PREFIX = "/tracks"


class JBrowseService:
    """JBrowse 业务服务"""

    # 文件类型 → JBrowse 2 adapter 映射
    ADAPTER_MAP: dict[str, dict[str, Any]] = {
        ".bam": {
            "type": "BamAdapter",
            "loc_key": "bamLocation",
            "index_type": "BAI",
            "index_ext": ".bai",
            "track_type": "AlignmentsTrack",
        },
        ".cram": {
            "type": "CramAdapter",
            "loc_key": "cramLocation",
            "index_type": "CRAI",
            "index_ext": ".crai",
            "track_type": "AlignmentsTrack",
            "needs_sequence": True,
        },
        ".bw": {
            "type": "BigWigAdapter",
            "loc_key": "bigWigLocation",
            "index_type": None,
            "index_ext": None,
            "track_type": "QuantitativeTrack",
        },
        ".bigwig": {
            "type": "BigWigAdapter",
            "loc_key": "bigWigLocation",
            "index_type": None,
            "index_ext": None,
            "track_type": "QuantitativeTrack",
        },
        ".vcf.gz": {
            "type": "VcfTabixAdapter",
            "loc_key": "vcfGzLocation",
            "index_type": "TBI",
            "index_ext": ".tbi",
            "track_type": "VariantTrack",
        },
        ".bed.gz": {
            "type": "BedTabixAdapter",
            "loc_key": "bedGzLocation",
            "index_type": "TBI",
            "index_ext": ".tbi",
            "track_type": "FeatureTrack",
        },
        ".gff3.gz": {
            "type": "Gff3TabixAdapter",
            "loc_key": "gffGzLocation",
            "index_type": "TBI",
            "index_ext": ".tbi",
            "track_type": "FeatureTrack",
        },
    }

    def __init__(self, manager: ConfigManager | None = None) -> None:
        self._manager = manager or config_manager

    # ------------------------------------------------------------------
    # 参考基因组
    # ------------------------------------------------------------------

    async def list_assemblies(self) -> list[AssemblyDTO]:
        """列出所有参考基因组（含 fasta/fai 存在性检查）。"""
        assemblies = self._manager.get_config().assemblies

        async def _to_dto(asm: AssemblyConfig) -> AssemblyDTO:
            fasta_exists, fai_exists = await asyncio.to_thread(
                self._pair_exists, asm.fasta, asm.fai
            )
            return self._assembly_to_dto(asm, fasta_exists, fai_exists)

        return await asyncio.gather(*(_to_dto(a) for a in assemblies))

    def _assembly_to_dto(
        self, asm: AssemblyConfig, fasta_exists: bool, fai_exists: bool
    ) -> AssemblyDTO:
        return AssemblyDTO(
            id=asm.id,
            name=asm.name,
            species=asm.species,
            common_name=asm.common_name,
            taxonomy_id=asm.taxonomy_id,
            version_id=asm.version_id or asm.id,
            version_name=asm.version_name,
            assembly_name=asm.assembly_name,
            category=asm.category,
            icon=asm.icon,
            is_default=asm.is_default,
            status=asm.status,
            release_date=asm.release_date,
            description=asm.description,
            stats=asm.stats or {},
            data_files={key: value.model_dump() for key, value in asm.data_files.items()},
            fasta_exists=fasta_exists,
            fai_exists=fai_exists,
            aliases=asm.aliases or [],
        )

    async def get_assembly_detail(self, assembly_id: str) -> AssemblyDetailDTO:
        asm = self._manager.get_assembly(assembly_id)
        if asm is None:
            raise NotFoundError(f"参考基因组不存在: {assembly_id}")
        fasta_exists, fai_exists = await asyncio.to_thread(self._pair_exists, asm.fasta, asm.fai)
        base = self._assembly_to_dto(asm, fasta_exists, fai_exists).model_dump()
        return AssemblyDetailDTO(**base, fasta=asm.fasta, fai=asm.fai)

    async def list_preset_tracks(self, assembly_id: str) -> list[PresetTrackDTO]:
        tracks = self._manager.get_preset_tracks(assembly_id)

        async def _to_dto(t: TrackConfig) -> PresetTrackDTO:
            exists = await asyncio.to_thread(Path(t.file).exists)
            return PresetTrackDTO(
                name=t.name, file=t.file, type=t.type, color=t.color, file_exists=exists
            )

        return await asyncio.gather(*(_to_dto(t) for t in tracks))

    # ------------------------------------------------------------------
    # 浏览器配置生成
    # ------------------------------------------------------------------

    async def generate_browser_config(
        self,
        assembly_id: str,
        user_tracks: list[str] | None = None,
        region: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """生成完整的 JBrowse 2 配置 JSON（前端拿到后写入 blob URL 交给 iframe）。"""
        assembly = self._manager.get_assembly(assembly_id)
        if assembly is None:
            raise NotFoundError(f"未知的参考基因组: {assembly_id}")

        config = self._manager.get_config()
        assemblies = [self._build_assembly_config(assembly)]
        tracks: list[dict[str, Any]] = []

        # 1. 预设轨道（YAML 声明，受信）
        for pt in self._manager.get_preset_tracks(assembly_id):
            track_cfg = self._build_track_config(pt, assembly)
            if track_cfg:
                tracks.append(track_cfg)

        # 2. 用户轨道（须归属校验，防越权）
        if user_tracks:
            if user_id is None:
                raise ValidationError("加载用户轨道需要登录")
            for track_path in user_tracks:
                self.ensure_user_owned(track_path, user_id)
                track_cfg = await asyncio.to_thread(self._build_user_track, track_path, assembly)
                if track_cfg:
                    tracks.append(track_cfg)

        default_region = region or config.defaults.default_region
        view_tracks = [
            {"id": t["trackId"], "type": t["type"], "configuration": t["trackId"]} for t in tracks
        ]

        return {
            "assemblies": assemblies,
            "tracks": tracks,
            "defaultSession": {
                "name": f"OmicHub-{assembly_id}",
                "view": {
                    "id": "linearGenomeView",
                    "type": "LinearGenomeView",
                    "tracks": view_tracks,
                    "location": self._parse_region(default_region),
                },
            },
            "configuration": {
                "theme": {
                    "palette": {
                        "primary": {"main": "#165DFF"},
                        "secondary": {"main": "#14C9C9"},
                        "tertiary": {"main": "#FFB800"},
                    }
                }
            },
        }

    def _build_assembly_config(self, assembly: AssemblyConfig) -> dict[str, Any]:
        """构建 JBrowse 2 参考基因组配置（IndexedFastaAdapter）。"""
        return {
            "name": assembly.id,
            "aliases": assembly.aliases or [],
            "sequence": {
                "type": "ReferenceSequenceTrack",
                "trackId": f"{assembly.id}-reference",
                "adapter": {
                    "type": "IndexedFastaAdapter",
                    "fastaLocation": {
                        "uri": to_tracks_uri(assembly.fasta),
                        "locationType": "UriLocation",
                    },
                    "faiLocation": {
                        "uri": to_tracks_uri(assembly.fai),
                        "locationType": "UriLocation",
                    },
                },
            },
        }

    def _build_track_config(
        self, track: TrackConfig, assembly: AssemblyConfig
    ) -> dict[str, Any] | None:
        """构建单个轨道配置。displays 字段省略，JBrowse 2 按 track_type 自动选默认展示。"""
        ext = self._ext_of(track.file)
        adapter_info = self.ADAPTER_MAP.get(ext)
        if not adapter_info:
            return None

        adapter: dict[str, Any] = {"type": adapter_info["type"]}
        adapter[adapter_info["loc_key"]] = {
            "uri": to_tracks_uri(track.file),
            "locationType": "UriLocation",
        }

        # 索引
        if adapter_info.get("index_ext"):
            index_uri: str | None = None
            if track.index:
                index_uri = to_tracks_uri(track.index)
            else:
                # 自动推断索引文件并换算
                idx_path = self._infer_index_path(track.file, adapter_info["index_ext"])
                if idx_path:
                    index_uri = to_tracks_uri(idx_path)
            if index_uri:
                adapter["index"] = {
                    "location": {"uri": index_uri, "locationType": "UriLocation"},
                    "indexType": adapter_info["index_type"],
                }

        # CRAM 需要参考序列适配器才能解码
        if adapter_info.get("needs_sequence"):
            adapter["sequenceAdapter"] = {
                "type": "IndexedFastaAdapter",
                "fastaLocation": {
                    "uri": to_tracks_uri(assembly.fasta),
                    "locationType": "UriLocation",
                },
                "faiLocation": {
                    "uri": to_tracks_uri(assembly.fai),
                    "locationType": "UriLocation",
                },
            }

        return {
            "type": adapter_info["track_type"],
            "trackId": f"{assembly.id}-{Path(track.file).stem}",
            "name": track.name,
            "assemblyNames": [assembly.id],
            "adapter": adapter,
        }

    def _build_user_track(self, file_path: str, assembly: AssemblyConfig) -> dict[str, Any] | None:
        """从文件路径构建用户轨道配置。"""
        path = Path(file_path)
        ext = self._ext_of(file_path)
        adapter_info = self.ADAPTER_MAP.get(ext)
        if not adapter_info:
            return None

        # 推断索引
        index_path = None
        if adapter_info.get("index_ext"):
            index_path = self._infer_index_path(file_path, adapter_info["index_ext"])

        # 轨道名：去双扩展
        name = path.name
        for _suf in reversed(path.suffixes):
            name = Path(name).stem

        track = TrackConfig(
            name=name,
            file=file_path,
            index=index_path,
            type=ext.lstrip("."),
            color="#1565C0",
        )
        return self._build_track_config(track, assembly)

    # ------------------------------------------------------------------
    # 用户目录扫描
    # ------------------------------------------------------------------

    async def scan_user_directory(self, user_id: str) -> list[ScannedFileDTO]:
        """扫描用户目录，发现可加载的轨道文件。"""
        config = self._manager.get_config()
        if not config.auto_scan.enabled:
            return []

        scan_paths = self._manager.get_user_scan_paths(user_id)
        extensions = config.auto_scan.extensions
        # 扩展名归一化小写，支持 .vcf.gz 等双扩展按后缀匹配
        ext_set = [e.lower() for e in extensions]

        def _scan() -> list[ScannedFileDTO]:
            items: list[ScannedFileDTO] = []
            for scan_path in scan_paths:
                if not scan_path.exists():
                    continue
                # 递归遍历整棵目录树。onerror 静默跳过无权访问/损坏的子目录，
                # 避免单个坏目录导致整次扫描失败（那会让「我的文件」又变空）。
                # 覆盖 raw/ 上传、results/{task}/ 分析产物、用户自定义子目录。
                for root, _dirs, files in os.walk(scan_path, onerror=lambda _e: None):
                    for fname in files:
                        name_lower = fname.lower()
                        matched = next((e for e in ext_set if name_lower.endswith(e)), None)
                        if not matched:
                            continue
                        path = Path(root) / fname
                        try:
                            stat = path.stat()
                        except OSError:
                            continue
                        index_status = self._check_index_status(path)
                        items.append(
                            ScannedFileDTO(
                                path=str(path),
                                name=path.name,
                                type=matched.lstrip("."),
                                size=stat.st_size,
                                size_human=self._human_readable_size(stat.st_size),
                                modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                indexed=index_status["indexed"],
                                index_file=index_status.get("index_file"),
                                can_load=index_status["indexed"],
                            )
                        )
            items.sort(key=lambda x: x.modified, reverse=True)
            return items

        return await asyncio.to_thread(_scan)

    # ------------------------------------------------------------------
    # 索引状态
    # ------------------------------------------------------------------

    async def check_index_status(self, file_path: str) -> dict[str, Any]:
        """检查文件索引状态（只读，允许任意 data_root 下路径）。"""
        self.ensure_under_data_root(file_path)

        def _work() -> dict[str, Any] | None:
            path = Path(file_path)
            if not path.exists():
                return None
            return self._check_index_status(path)

        result = await asyncio.to_thread(_work)
        if result is None:
            raise NotFoundError("文件不存在")
        return result

    def _check_index_status(self, file_path: Path) -> dict[str, Any]:
        """同步实现：根据扩展名判定索引文件是否存在。"""
        ext = self._ext_of(str(file_path))
        adapter_info = self.ADAPTER_MAP.get(ext)
        if not adapter_info:
            return {"indexed": False, "reason": "不支持的文件类型"}

        if not adapter_info.get("index_ext"):
            # BigWig 等无需索引
            return {"indexed": True, "reason": "无需索引"}

        index_file = self._infer_index_path(str(file_path), adapter_info["index_ext"])
        if index_file and Path(index_file).exists():
            return {
                "indexed": True,
                "index_file": index_file,
            }
        return {
            "indexed": False,
            "reason": f"缺少索引文件 ({adapter_info['index_ext']})",
            "expected_index": index_file or "",
        }

    # ------------------------------------------------------------------
    # 上传资格
    # ------------------------------------------------------------------

    def check_upload_eligibility(self, filename: str, file_size: int) -> dict[str, Any]:
        """检查上传文件是否合规（扩展名 + 大小）。"""
        upload_cfg = self._manager.get_config().upload
        ext = self._ext_of(filename)

        errors: list[str] = []
        if ext not in upload_cfg.allowed_types:
            errors.append(f"不支持的文件类型: {ext or '(无扩展名)'}")

        max_bytes = upload_cfg.max_file_size * 1024 * 1024 * 1024
        if file_size and file_size > max_bytes:
            errors.append(
                f"文件过大: {self._human_readable_size(file_size)} > {upload_cfg.max_file_size}GB"
            )

        return {"eligible": len(errors) == 0, "errors": errors, "warnings": []}

    # ------------------------------------------------------------------
    # 归属校验（安全）
    # ------------------------------------------------------------------

    def ensure_user_owned(self, file_path: str, user_id: str) -> None:
        """确保文件在当前用户目录下，拒绝越权读取他人数据。"""
        if not file_path:
            raise ValidationError("文件路径不能为空")
        try:
            resolved = Path(file_path).resolve(strict=False)
        except (OSError, ValueError):
            raise ValidationError("文件路径非法") from None
        user_root = (Path(get_storage_config().data_root) / "users" / str(user_id)).resolve(
            strict=False
        )
        try:
            resolved.relative_to(user_root)
        except ValueError:
            raise ValidationError("无权访问该文件：不在当前用户目录下") from None

    def ensure_under_data_root(self, file_path: str) -> None:
        """只读操作的下限校验：路径须在 data_root 下，禁止任意路径探测。"""
        if not file_path:
            raise ValidationError("文件路径不能为空")
        try:
            resolved = Path(file_path).resolve(strict=False)
        except (OSError, ValueError):
            raise ValidationError("文件路径非法") from None
        try:
            resolved.relative_to(Path(get_storage_config().data_root).resolve(strict=False))
        except ValueError:
            raise ValidationError("文件路径不在数据根目录下") from None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _ext_of(file_path: str) -> str:
        """归一化扩展名：.vcf.gz / .bed.gz / .gff3.gz 保留双扩展，其余取最后一段。"""
        suffixes = Path(file_path).suffixes
        if not suffixes:
            return ""
        joined = "".join(suffixes).lower()
        if joined.endswith(".gz") and len(suffixes) >= 2:
            return "".join(suffixes[-2:]).lower()
        return suffixes[-1].lower()

    @staticmethod
    def _infer_index_path(file_path: str, index_ext: str) -> str | None:
        """推断索引文件路径：优先 file.bam.bai，回退 file.bai。"""
        p = Path(file_path)
        candidates = [p.with_suffix(p.suffix + index_ext), Path(str(p) + index_ext)]
        for c in candidates:
            if c.exists():
                return str(c)
        # 不存在时返回首选候选，供 expected_index 展示
        return str(candidates[0])

    @staticmethod
    def _pair_exists(a: str, b: str) -> tuple[bool, bool]:
        return Path(a).exists(), Path(b).exists()

    @staticmethod
    def _human_readable_size(size_bytes: int) -> str:
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    @staticmethod
    def _parse_region(region: str) -> dict[str, Any]:
        """解析 Chr1:1000000-2000000 → {refName, start, end}。"""
        try:
            if ":" in region:
                chrom, coords = region.split(":", 1)
                if "-" in coords:
                    start, end = coords.split("-", 1)
                    return {
                        "refName": chrom.strip(),
                        "start": int(start.replace(",", "")),
                        "end": int(end.replace(",", "")),
                    }
        except (ValueError, AttributeError):
            pass
        return {"refName": "Chr1", "start": 1, "end": 100000}


# 服务单例
jbrowse_service = JBrowseService()
