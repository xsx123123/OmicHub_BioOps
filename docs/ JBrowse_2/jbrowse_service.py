"""
src/backend/services/jbrowse_service.py
JBrowse 2 业务服务层
处理配置生成、文件扫描、索引检查等逻辑
"""

import os
import glob
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from core.jbrowse_config import config_manager, JBrowseConfig, AssemblyConfig, TrackConfig


class JBrowseService:
    """JBrowse 业务服务"""

    # 文件类型到 JBrowse 2 adapter 的映射
    ADAPTER_MAP = {
        ".bam": {
            "type": "BamAdapter",
            "index_type": "BAI",
            "index_ext": ".bai",
            "track_type": "AlignmentsTrack"
        },
        ".cram": {
            "type": "CramAdapter",
            "index_type": "CRAI",
            "index_ext": ".crai",
            "track_type": "AlignmentsTrack"
        },
        ".bw": {
            "type": "BigWigAdapter",
            "index_ext": None,
            "track_type": "QuantitativeTrack"
        },
        ".bigwig": {
            "type": "BigWigAdapter",
            "index_ext": None,
            "track_type": "QuantitativeTrack"
        },
        ".vcf.gz": {
            "type": "VcfTabixAdapter",
            "index_type": "TBI",
            "index_ext": ".tbi",
            "track_type": "VariantTrack"
        },
        ".bed.gz": {
            "type": "BedTabixAdapter",
            "index_type": "TBI",
            "index_ext": ".tbi",
            "track_type": "FeatureTrack"
        },
        ".gff3.gz": {
            "type": "Gff3TabixAdapter",
            "index_type": "TBI",
            "index_ext": ".tbi",
            "track_type": "FeatureTrack"
        }
    }

    def __init__(self):
        self.base_url = "/tracks"  # Nginx 暴露的数据路径前缀

    def build_assembly_config(self, assembly: AssemblyConfig) -> dict:
        """构建 JBrowse 2 参考基因组配置"""
        return {
            "name": assembly.id,
            "sequence": {
                "type": "ReferenceSequenceTrack",
                "trackId": f"{assembly.id}-reference",
                "adapter": {
                    "type": "IndexedFastaAdapter",
                    "fastaLocation": {
                        "uri": f"{self.base_url}{assembly.fasta.replace('/data/omichub', '')}",
                        "locationType": "UriLocation"
                    },
                    "faiLocation": {
                        "uri": f"{self.base_url}{assembly.fai.replace('/data/omichub', '')}",
                        "locationType": "UriLocation"
                    }
                }
            }
        }

    def build_track_config(self, track: TrackConfig, assembly_id: str) -> dict:
        """构建单个轨道配置"""
        ext = Path(track.file).suffix.lower()
        if ext == ".gz":
            # 处理 .vcf.gz 这种双扩展名
            ext = "".join(Path(track.file).suffixes[-2:]).lower()

        adapter_info = self.ADAPTER_MAP.get(ext)
        if not adapter_info:
            return None

        # 构建 adapter
        adapter = {"type": adapter_info["type"]}

        if adapter_info["type"] == "BamAdapter":
            adapter["bamLocation"] = {
                "uri": f"{self.base_url}{track.file.replace('/data/omichub', '')}",
                "locationType": "UriLocation"
            }
            if track.index:
                adapter["index"] = {
                    "location": {
                        "uri": f"{self.base_url}{track.index.replace('/data/omichub', '')}",
                        "locationType": "UriLocation"
                    },
                    "indexType": adapter_info["index_type"]
                }

        elif adapter_info["type"] == "BigWigAdapter":
            adapter["bigWigLocation"] = {
                "uri": f"{self.base_url}{track.file.replace('/data/omichub', '')}",
                "locationType": "UriLocation"
            }

        elif adapter_info["type"] in ["VcfTabixAdapter", "BedTabixAdapter", "Gff3TabixAdapter"]:
            loc_key = "vcfGzLocation" if "Vcf" in adapter_info["type"] else                       "bedGzLocation" if "Bed" in adapter_info["type"] else "gffGzLocation"
            adapter[loc_key] = {
                "uri": f"{self.base_url}{track.file.replace('/data/omichub', '')}",
                "locationType": "UriLocation"
            }
            if track.index:
                adapter["index"] = {
                    "location": {
                        "uri": f"{self.base_url}{track.index.replace('/data/omichub', '')}",
                        "locationType": "UriLocation"
                    },
                    "indexType": adapter_info["index_type"]
                }

        return {
            "type": adapter_info["track_type"],
            "trackId": f"{assembly_id}-{track.name}",
            "name": track.name,
            "assemblyNames": [assembly_id],
            "adapter": adapter,
            "displays": [{
                "type": "LinearBasicDisplay" if "Feature" in adapter_info["track_type"] else "LinearPileupDisplay",
                "displayId": f"{assembly_id}-{track.name}-display",
                "renderer": {
                    "type": "SvgFeatureRenderer" if "Feature" in adapter_info["track_type"] else "PileupRenderer"
                }
            }]
        }

    def generate_browser_config(
        self,
        assembly_id: str,
        user_tracks: List[str] = None,
        region: str = None
    ) -> dict:
        """
        生成完整的 JBrowse 2 配置

        Args:
            assembly_id: 参考基因组 ID
            user_tracks: 用户选择的轨道文件路径列表
            region: 初始视图区域，如 "Chr1:1000000-2000000"

        Returns:
            JBrowse 2 配置 JSON
        """
        assembly = config_manager.get_assembly(assembly_id)
        if not assembly:
            raise ValueError(f"未知的参考基因组: {assembly_id}")

        config = config_manager.get_config()

        # 构建 assemblies
        assemblies = [self.build_assembly_config(assembly)]

        # 构建 tracks
        tracks = []

        # 1. 预设轨道
        preset_tracks = config_manager.get_preset_tracks(assembly_id)
        for pt in preset_tracks:
            track_cfg = self.build_track_config(pt, assembly_id)
            if track_cfg:
                tracks.append(track_cfg)

        # 2. 用户轨道
        if user_tracks:
            for track_path in user_tracks:
                track_cfg = self._build_user_track(track_path, assembly_id)
                if track_cfg:
                    tracks.append(track_cfg)

        # 构建 defaultSession
        default_region = region or config.defaults.default_region
        view_tracks = [{"id": t["trackId"], "type": t["type"], "configuration": t["trackId"]} for t in tracks]

        result = {
            "assemblies": assemblies,
            "tracks": tracks,
            "defaultSession": {
                "name": f"OmicHub-{assembly_id}",
                "view": {
                    "id": "linearGenomeView",
                    "type": "LinearGenomeView",
                    "tracks": view_tracks,
                    "location": self._parse_region(default_region, assembly)
                }
            },
            "configuration": {
                "theme": {
                    "palette": {
                        "primary": {"main": "#165DFF"},
                        "secondary": {"main": "#14C9C9"},
                        "tertiary": {"main": "#FFB800"}
                    }
                }
            }
        }

        return result

    def _build_user_track(self, file_path: str, assembly_id: str) -> Optional[dict]:
        """从文件路径构建用户轨道配置"""
        path = Path(file_path)
        ext = "".join(path.suffixes).lower()

        # 提取基础扩展名
        if ext.endswith(".gz"):
            base_ext = ext[:-3]
        else:
            base_ext = ext

        adapter_info = self.ADAPTER_MAP.get(ext) or self.ADAPTER_MAP.get(base_ext)
        if not adapter_info:
            return None

        track_name = path.stem
        if track_name.endswith(".gz"):
            track_name = track_name[:-3]

        # 检查索引
        index_path = None
        if adapter_info.get("index_ext"):
            possible_index = path.with_suffix(path.suffix + adapter_info["index_ext"])
            if not possible_index.exists():
                possible_index = Path(str(path) + adapter_info["index_ext"])
            if possible_index.exists():
                index_path = str(possible_index)

        track = TrackConfig(
            name=track_name,
            file=file_path,
            index=index_path,
            type=ext.lstrip(".").replace(".gz", ""),
            color="#1565C0"
        )

        return self.build_track_config(track, assembly_id)

    def _parse_region(self, region: str, assembly: AssemblyConfig) -> dict:
        """解析 region 字符串为 JBrowse 2 location 格式"""
        try:
            if ":" in region:
                chrom, coords = region.split(":", 1)
                if "-" in coords:
                    start, end = coords.split("-", 1)
                    return {
                        "refName": chrom,
                        "start": int(start.replace(",", "")),
                        "end": int(end.replace(",", ""))
                    }
            # 默认返回第一个染色体
            return {"refName": "Chr1", "start": 1, "end": 100000}
        except Exception:
            return {"refName": "Chr1", "start": 1, "end": 100000}

    def scan_user_directory(self, user_id: str) -> List[Dict[str, Any]]:
        """
        扫描用户目录，发现可加载的轨道文件

        Returns:
            文件列表，包含路径、类型、大小、索引状态等
        """
        config = config_manager.get_config()
        if not config.auto_scan.enabled:
            return []

        scan_paths = config_manager.get_user_scan_paths(user_id)
        extensions = config.auto_scan.extensions
        results = []

        for scan_path in scan_paths:
            if not scan_path.exists():
                continue

            for ext in extensions:
                pattern = str(scan_path / f"*{ext}")
                for file_path in glob.glob(pattern):
                    path = Path(file_path)

                    # 检查索引状态
                    index_status = self._check_index_status(path)

                    results.append({
                        "path": file_path,
                        "name": path.name,
                        "type": ext.lstrip("."),
                        "size": path.stat().st_size,
                        "size_human": self._human_readable_size(path.stat().st_size),
                        "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                        "indexed": index_status["indexed"],
                        "index_file": index_status.get("index_file"),
                        "can_load": index_status["indexed"]  # 有索引才能加载
                    })

        return sorted(results, key=lambda x: x["modified"], reverse=True)

    def _check_index_status(self, file_path: Path) -> dict:
        """检查文件的索引状态"""
        ext = "".join(file_path.suffixes).lower()

        adapter_info = self.ADAPTER_MAP.get(ext)
        if not adapter_info:
            return {"indexed": False, "reason": "不支持的文件类型"}

        if not adapter_info.get("index_ext"):
            # 不需要索引的文件类型 (BigWig)
            return {"indexed": True, "reason": "无需索引"}

        index_ext = adapter_info["index_ext"]
        index_file = file_path.with_suffix(file_path.suffix + index_ext)

        if not index_file.exists():
            index_file = Path(str(file_path) + index_ext)

        if index_file.exists():
            return {
                "indexed": True,
                "index_file": str(index_file),
                "index_mtime": datetime.fromtimestamp(index_file.stat().st_mtime).isoformat()
            }

        return {
            "indexed": False,
            "reason": f"缺少索引文件 ({index_ext})",
            "expected_index": str(index_file)
        }

    def check_upload_eligibility(self, filename: str, file_size: int) -> dict:
        """检查上传文件是否合规"""
        config = config_manager.get_config()
        upload_cfg = config.upload

        ext = Path(filename).suffix.lower()
        if ext == ".gz":
            ext = "".join(Path(filename).suffixes[-2:]).lower()

        errors = []

        if ext not in upload_cfg.allowed_types:
            errors.append(f"不支持的文件类型: {ext}")

        max_bytes = upload_cfg.max_file_size * 1024 * 1024 * 1024
        if file_size > max_bytes:
            errors.append(f"文件过大: {self._human_readable_size(file_size)} > {upload_cfg.max_file_size}GB")

        return {
            "eligible": len(errors) == 0,
            "errors": errors,
            "warnings": []
        }

    @staticmethod
    def _human_readable_size(size_bytes: int) -> str:
        """转换为人类可读的文件大小"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"


# 服务单例
jbrowse_service = JBrowseService()
