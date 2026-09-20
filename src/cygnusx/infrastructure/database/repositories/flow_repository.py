"""流程仓储的文件系统实现 — YAML 配置中心。

从指定目录扫描 *.yaml/*.yml 文件，加载为 FlowConfig。
支持热重载（重新扫描目录）。
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from loguru import logger

from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import YAMLConfigError
from cygnusx.domain.flow.entities import FlowConfig
from cygnusx.domain.flow.services import FlowDomainService


class FileSystemFlowRepository:
    """文件系统流程仓储 — 从 YAML 目录加载流程配置。

    线程安全：使用 RLock 保护 _cache 字典。
    支持基于目录 mtime 的自动热重载。
    """

    def __init__(self, yaml_dir: Path | None = None):
        """初始化仓储。

        Args:
            yaml_dir: YAML 文件目录，默认从配置读取 flow_yaml_dir
        """
        if yaml_dir is None:
            settings = get_settings()
            yaml_dir = Path(settings.flow_yaml_dir)
        self._yaml_dir = yaml_dir
        self._service = FlowDomainService()
        self._cache: dict[str, FlowConfig] = {}
        self._lock = RLock()
        self._mtime: float = 0.0

    def get_by_flow_id(self, flow_id: str) -> FlowConfig | None:
        """根据流程 ID（meta.id）获取流程配置"""
        with self._lock:
            self._auto_reload_if_needed()
            return self._cache.get(flow_id)

    def list_flows(self, category: str | None = None) -> list[FlowConfig]:
        """列出所有流程配置，可按分类过滤"""
        with self._lock:
            self._auto_reload_if_needed()
            flows = list(self._cache.values())
            if category:
                flows = [f for f in flows if f.meta.category == category]
            return flows

    def reload(self) -> int:
        """重新加载所有流程配置（热重载），返回加载数量"""
        with self._lock:
            self._cache.clear()
            self._load_all()
            return len(self._cache)

    def _auto_reload_if_needed(self) -> None:
        """检测 YAML 目录 mtime 变化并自动重载。"""
        if not self._yaml_dir.exists():
            return
        try:
            current_mtime = max(
                (f.stat().st_mtime for f in self._yaml_dir.glob("*.yaml")),
                default=self._mtime,
            )
            current_mtime = max(
                current_mtime,
                max(
                    (f.stat().st_mtime for f in self._yaml_dir.glob("*.yml")),
                    default=self._mtime,
                ),
            )
        except OSError:
            return

        if self._cache and current_mtime <= self._mtime:
            return

        self._cache.clear()
        self._load_all()
        self._mtime = current_mtime

    def _load_all(self) -> None:
        """扫描 YAML 目录并加载所有流程配置（不加锁，调用方负责）"""
        if not self._yaml_dir.exists():
            logger.warning(f"流程 YAML 目录不存在: {self._yaml_dir}")
            return

        yaml_files = sorted(
            list(self._yaml_dir.glob("*.yaml")) + list(self._yaml_dir.glob("*.yml"))
        )
        for yaml_file in yaml_files:
            try:
                flow_config = self._service.load_from_yaml(yaml_file)
                if flow_config.meta.id in self._cache:
                    logger.warning(
                        f"流程 ID '{flow_config.meta.id}' 重复定义，"
                        f"文件 {yaml_file.name} 覆盖之前的加载"
                    )
                self._cache[flow_config.meta.id] = flow_config
                logger.info(f"已加载流程: {flow_config.meta.id} (v{flow_config.meta.version})")
            except YAMLConfigError as e:
                logger.error(f"加载流程配置失败 {yaml_file.name}: {e}")
            except Exception as e:
                logger.exception(f"加载流程配置异常 {yaml_file.name}: {e}")
