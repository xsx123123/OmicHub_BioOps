"""GO / KEGG 富集 R 容器执行器 —— 拼接并运行 `docker run` 调用 R 计算镜像。

镜像本身由用户构建（契约见 tool_configs/enrichments/KEGG_Docker_契约.md），本模块只负责：
- 按 settings 拼接 docker run 命令（网络 / 代理 / 挂载 / 资源 / 超时）；
- asyncio.create_subprocess_exec 执行，事件循环不阻塞；
- 捕获 stdout / stderr，超时则 kill 容器进程。

路径约定：宿主 /data/omichub 与容器内 /data/omichub 同路径挂载，故 input/output
直接用宿主绝对路径即可，容器内所见一致。基因列表与结果 CSV 经此挂载交换。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from omichub.core.config import get_settings
from omichub.core.telemetry import get_tracer

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentRunResult:
    """容器执行结果。"""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class EnrichmentRunParams:
    """单次富集分析的容器入参（已落到宿主磁盘的路径）。"""

    input_path: str  # gene_list.txt 宿主绝对路径（== 容器内路径）
    output_path: str  # enrichment_result.csv 宿主绝对路径（== 容器内路径）
    kegg_code: str
    id_type: str
    go_obo: str | None = None
    go_annotation: str | None = None
    kegg_id_map: str | None = None
    kegg_key_type: str = "kegg"
    p_value_cutoff: float = 0.05
    q_value_cutoff: float = 0.1


class EnrichmentDockerRunner:
    """R 富集分析容器执行器。"""

    def __init__(self) -> None:
        self._settings = get_settings()

    def build_command(self, params: EnrichmentRunParams, container_name: str) -> list[str]:
        """构造 `docker run` 命令行参数列表。"""
        s = self._settings
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
        ]
        if s.enrichment_docker_network:
            command.extend(["--network", s.enrichment_docker_network])
        if s.enrichment_proxy_url:
            command.extend(
                [
                    "-e",
                    f"http_proxy={s.enrichment_proxy_url}",
                    "-e",
                    f"https_proxy={s.enrichment_proxy_url}",
                    "-e",
                    "no_proxy=localhost,127.0.0.1",
                ]
            )
        command.extend(
            [
            "-v",
            f"{s.enrichment_data_mount}:/data/omichub",
            "--memory",
            s.enrichment_memory,
            "--cpus",
            str(s.enrichment_cpus),
            s.enrichment_docker_image,
            "Rscript",
            "/app/run_enrichment.R",
            "--input",
            params.input_path,
            "--output",
            params.output_path,
            "--kegg_code",
            params.kegg_code,
            "--id_type",
            params.id_type,
            "--kegg_key_type",
            params.kegg_key_type,
            "--p_value_cutoff",
            str(params.p_value_cutoff),
            "--q_value_cutoff",
            str(params.q_value_cutoff),
            ]
        )
        if params.go_obo:
            command.extend(["--go_obo", params.go_obo])
        if params.go_annotation:
            command.extend(["--go_annotation", params.go_annotation])
        if params.kegg_id_map:
            command.extend(["--kegg_id_map", params.kegg_id_map])
        return command

    async def run(self, params: EnrichmentRunParams, container_name: str) -> EnrichmentRunResult:
        """执行容器，返回 stdout/stderr/returncode；超时 kill。

        docker run --rm 退出后容器自动清理；kill 主进程会连带终止容器。
        """
        cmd = self.build_command(params, container_name)
        logger.info("enrichment docker run: %s", " ".join(cmd))

        tracer = get_tracer("omichub.toolbox")
        with tracer.start_as_current_span(
            "toolbox.runner",
            attributes={"toolbox.runner": "enrichment", "toolbox.command": " ".join(cmd)[:1000]},
        ) as span:
            start = time.perf_counter()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                timeout = self._settings.enrichment_exec_timeout
                try:
                    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                except TimeoutError:
                    # 超时：杀掉 docker run 主进程（--rm 会清理容器）
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    # 给被杀进程一点时间回收 stdout/stderr，收不到也无所谓
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(proc.communicate(), timeout=10)
                    span.set_attribute("toolbox.returncode", -1)
                    span.set_attribute("toolbox.timed_out", True)
                    return EnrichmentRunResult(
                        returncode=-1,
                        stdout="",
                        stderr=f"富集分析执行超时（>{timeout}s）",
                        timed_out=True,
                    )

                returncode = proc.returncode if proc.returncode is not None else -1
                span.set_attribute("toolbox.returncode", returncode)
                return EnrichmentRunResult(
                    returncode=returncode,
                    stdout=stdout_b.decode("utf-8", errors="replace"),
                    stderr=stderr_b.decode("utf-8", errors="replace"),
                )
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("toolbox.duration_ms", round(duration_ms, 2))
                logger.info("enrichment runner finished in %.2f ms", duration_ms)


# 模块级单例
enrichment_runner = EnrichmentDockerRunner()
