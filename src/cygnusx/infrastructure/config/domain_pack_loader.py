"""从 YAML 文件加载可热重载的 Domain Pack。"""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from pydantic import ValidationError

from cygnusx.core.config import get_settings
from cygnusx.domain.domains.schema import DomainPack


class DomainPackLoader:
    """目录级缓存；单个文件无效时保留其他有效 Domain Pack。"""

    def __init__(self, yaml_dir: Path | None = None) -> None:
        self._yaml_dir = yaml_dir or Path(get_settings().domains_yaml_dir)
        self._packs: dict[str, DomainPack] = {}
        self._errors: list[str] = []
        self._signature: tuple[tuple[str, int, int], ...] | None = None

    @property
    def packs(self) -> dict[str, DomainPack]:
        self.reload_if_changed()
        return dict(self._packs)

    @property
    def errors(self) -> list[str]:
        self.reload_if_changed()
        return list(self._errors)

    def reload_if_changed(self) -> bool:
        signature = self._directory_signature()
        if signature == self._signature:
            return False
        self._signature = signature
        self._packs = {}
        self._errors = []
        self._load_all()
        return True

    def reload(self) -> None:
        self._signature = None
        self.reload_if_changed()

    def _directory_signature(self) -> tuple[tuple[str, int, int], ...]:
        if not self._yaml_dir.exists():
            return ()
        entries: list[tuple[str, int, int]] = []
        for path in sorted((*self._yaml_dir.glob("*.yaml"), *self._yaml_dir.glob("*.yml"))):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    def _load_all(self) -> None:
        if not self._yaml_dir.exists():
            return
        for path in sorted((*self._yaml_dir.glob("*.yaml"), *self._yaml_dir.glob("*.yml"))):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("YAML 顶层必须是对象")
                pack = DomainPack.model_validate(payload)
                if pack.domain in self._packs:
                    raise ValueError(f"重复 domain: {pack.domain}")
                self._packs[pack.domain] = pack
            except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
                message = f"加载 Domain Pack 失败 {path.name}: {exc}"
                self._errors.append(message)
                logger.warning(message)
