"""远程执行器 - 通过 HTTP 调用集群头节点上的 Snakemake Executor"""

from typing import Any

import httpx


class RemoteSnakemakeExecutor:
    """远程 Snakemake 执行器

    适用于 HPC 集群（Slurm/SGE），通过 HTTP 调用部署在集群头节点的
    Snakemake Executor 服务（轻量 FastAPI 副进程）。
    """

    def __init__(self, executor_url: str, api_key: str = "") -> None:
        self.executor_url = executor_url.rstrip("/")
        self.api_key = api_key

    async def execute(
        self,
        snakefile: str,
        config: dict[str, Any],
        cores: int = 4,
        work_dir: str = "",
        targets: list[str] | None = None,
    ) -> dict[str, Any]:
        """提交作业到远程集群"""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.executor_url}/api/v1/execute",
                headers=headers,
                json={
                    "snakefile": snakefile,
                    "config": config,
                    "cores": cores,
                    "work_dir": work_dir,
                    "targets": targets or [],
                },
                timeout=300,
            )
            response.raise_for_status()
            return response.json()

    async def get_status(self, job_id: str) -> dict[str, Any]:
        """查询作业状态"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.executor_url}/api/v1/jobs/{job_id}",
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            )
            response.raise_for_status()
            return response.json()

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """取消作业"""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.executor_url}/api/v1/jobs/{job_id}",
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            )
            response.raise_for_status()
            return response.json()
