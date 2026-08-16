"""文件域服务"""

import hashlib

from omichub.domain.file.repositories import (
    IFileRepository,
    IResultArchiveRepository,
    ISampleRepository,
)


class FileDomainService:
    """文件域服务"""

    def __init__(
        self,
        sample_repo: ISampleRepository,
        file_repo: IFileRepository,
        result_repo: IResultArchiveRepository,
    ):
        self._sample_repo = sample_repo
        self._file_repo = file_repo
        self._result_repo = result_repo

    async def calculate_checksum(self, file_path: str, algorithm: str = "sha256") -> str:
        """计算文件校验和"""
        hasher = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    async def cleanup_expired_archives(self) -> int:
        """清理过期结果归档"""
        return await self._result_repo.cleanup_expired()
