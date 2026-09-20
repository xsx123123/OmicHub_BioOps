"""统一路径工厂 — 所有磁盘路径的唯一生成点。

设计目标：替代分散在各 Service 中的路径拼接逻辑（TaskService._make_work_dir、
BlastService._result_dir、EnrichmentService._work_dir 等），确保全平台路径约定一致。

所有需要构建数据路径的代码都应通过 get_path_factory() 获取实例，而非自行拼接。
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from cygnusx.infrastructure.config.storage_config import StorageConfig, get_storage_config

_PATH_SEGMENT_RE = re.compile(r"[^\w\u4e00-\u9fff.-]+", re.UNICODE)


def project_slug(project_name: str, *, fallback: str = "untitled-project") -> str:
    """将项目名称规范为可读、安全的目录名。"""
    normalized = " ".join(str(project_name or "").strip().split())
    slug = _PATH_SEGMENT_RE.sub("_", normalized).strip("._")[:80]
    return slug or fallback


class StoragePathFactory:
    """统一路径工厂。"""

    def __init__(self, config: StorageConfig | None = None):
        self._config = config or get_storage_config()
        self._root = Path(self._config.data_root)
        self._users_subdir = self._config.users_subdir
        self._shared_subdir = self._config.shared_subdir
        self._system_subdir = self._config.system_subdir

    @property
    def data_root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # 用户区
    # ------------------------------------------------------------------

    def user_root(self, user_id: str) -> Path:
        return self._root / self._users_subdir / str(user_id)

    def remove_user_root(self, user_id: str) -> bool:
        """删除指定用户的完整存储目录，且只允许删除 users/{user_id}。"""
        user_root = self.user_root(user_id).resolve()
        users_root = (self._root / self._users_subdir).resolve()
        try:
            user_root.relative_to(users_root)
        except ValueError as exc:
            raise ValueError("用户存储路径越权") from exc
        if user_root == users_root or not user_root.exists():
            return False
        shutil.rmtree(user_root)
        return True

    def inbox_dir(self, user_id: str) -> Path:
        """用户上传入口（原 raw/）。"""
        return self.user_root(user_id) / "inbox"

    def inbox_subdir(self, user_id: str, directory: str) -> Path:
        """用户自建子目录。"""
        return self.inbox_dir(user_id) / directory

    def tasks_dir(self, user_id: str) -> Path:
        """用户所有计算任务的根目录。"""
        return self.user_root(user_id) / "tasks"

    def task_dir(self, user_id: str, task_id: str) -> Path:
        """单个任务目录。"""
        return self.tasks_dir(user_id) / str(task_id)

    def task_input_dir(self, user_id: str, task_id: str) -> Path:
        return self.task_dir(user_id, task_id) / "input"

    def task_output_dir(self, user_id: str, task_id: str) -> Path:
        return self.task_dir(user_id, task_id) / "output"

    def task_work_dir(self, user_id: str, task_id: str) -> Path:
        """任务工作区（Pipeline 执行目录、中间产物）。"""
        return self.task_dir(user_id, task_id) / "work"

    def task_logs_dir(self, user_id: str, task_id: str) -> Path:
        return self.task_dir(user_id, task_id) / "logs"

    def task_meta_path(self, user_id: str, task_id: str) -> Path:
        return self.task_dir(user_id, task_id) / "meta.json"

    def projects_dir(self, user_id: str) -> Path:
        return self.user_root(user_id) / "projects"

    def project_dir(self, user_id: str, project_slug: str) -> Path:
        return self.projects_dir(user_id) / project_slug

    def create_project_run_dir(
        self, user_id: str, project_name: str, analysis_name: str
    ) -> Path:
        """创建用户可见的项目运行目录。

        UUID 继续作为数据库主键与审计标识，不再作为用户工作区的目录名。重复运行以
        ``分析名-时间戳[-序号]`` 区分，避免覆盖已有结果。
        """
        project = project_slug(project_name)
        analysis = project_slug(analysis_name, fallback="analysis")
        base = self.project_dir(user_id, project) / "runs"
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        for sequence in range(1, 10_000):
            suffix = "" if sequence == 1 else f"-{sequence}"
            candidate = base / f"{analysis}-{stamp}{suffix}"
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                for directory_name in ("input", "output", "work", "logs"):
                    (candidate / directory_name).mkdir(exist_ok=True)
                return candidate
            except FileExistsError:
                continue
        raise RuntimeError("无法创建唯一的项目运行目录")

    def workspace_dir(self, user_id: str) -> Path:
        return self.user_root(user_id) / "workspace"

    def chat_uploads_dir(self, user_id: str) -> Path:
        return self.workspace_dir(user_id) / "chat-uploads"

    def sandbox_dir(self, user_id: str) -> Path:
        return self.workspace_dir(user_id) / "sandbox"

    def downloads_dir(self, user_id: str) -> Path:
        return self.user_root(user_id) / "downloads"

    # ------------------------------------------------------------------
    # 兼容旧路径（过渡期使用，新代码不应调用）
    # ------------------------------------------------------------------

    def legacy_raw_dir(self, user_id: str) -> Path:
        """旧版上传目录 raw/（兼容读取）。"""
        return self.user_root(user_id) / "raw"

    def legacy_results_dir(self, user_id: str, flow_id: str, task_id: str) -> Path:
        """旧版流程结果目录 results/{flow_id}/{task_id}/。"""
        return self.user_root(user_id) / "results" / flow_id / str(task_id)

    def legacy_raw_data_dir(self, user_id: str, accession: str = "") -> Path:
        """旧版数据下载目录 raw_data/。"""
        base = self.user_root(user_id) / "raw_data"
        return base / accession if accession else base

    # ------------------------------------------------------------------
    # 共享区（不计入用户配额）
    # ------------------------------------------------------------------

    def shared_root(self) -> Path:
        return self._root / self._shared_subdir

    def references_dir(self, genome: str = "") -> Path:
        base = self.shared_root() / "references"
        return base / genome if genome else base

    def blast_db_dir(self) -> Path:
        return self.shared_root() / "blast_db"

    def annotations_dir(self) -> Path:
        return self.shared_root() / "annotations"

    def bin_dir(self) -> Path:
        return self.shared_root() / "bin"

    # ------------------------------------------------------------------
    # 系统区
    # ------------------------------------------------------------------

    def tmp_dir(self, upload_id: str = "") -> Path:
        base = self._root / self._system_subdir / ".tmp"
        return base / upload_id if upload_id else base

    def conda_envs_dir(self) -> Path:
        return self._root / self._system_subdir / ".conda_envs"

    def archive_dir(self, user_id: str = "") -> Path:
        base = self._root / self._system_subdir / "archive"
        return base / str(user_id) if user_id else base

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def ensure_dir(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_task_dirs(self, user_id: str, task_id: str) -> Path:
        """创建任务完整目录结构并返回任务根目录。"""
        task_root = self.task_dir(user_id, task_id)
        for sub in ("input", "output", "work", "logs"):
            (task_root / sub).mkdir(parents=True, exist_ok=True)
        return task_root

    def relative_to_root(self, path: Path) -> str:
        """将绝对路径转为相对于 data_root 的路径字符串（用于 DB 存储）。"""
        return str(path.resolve().relative_to(self._root.resolve()))

    def is_within_root(self, path: Path) -> bool:
        """校验路径是否在 data_root 内（防路径遍历）。"""
        try:
            path.resolve().relative_to(self._root.resolve())
            return True
        except ValueError:
            return False


@lru_cache(maxsize=1)
def get_path_factory() -> StoragePathFactory:
    """获取全局单例路径工厂。"""
    return StoragePathFactory()
