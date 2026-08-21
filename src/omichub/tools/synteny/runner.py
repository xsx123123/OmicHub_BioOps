from __future__ import annotations

import asyncio
from dataclasses import dataclass

from omichub.core.config import get_settings


@dataclass
class SyntenyRunResult:
    returncode: int
    stdout: str
    stderr: str


class SyntenyDockerRunner:
    def build_command(self, gff3: str, blastp: str, output: str, container_name: str) -> list[str]:
        settings = get_settings()
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{settings.enrichment_data_mount}:/data/omichub",
            "omichub-synteny:v1",
            "--gff3",
            gff3,
            "--blastp",
            blastp,
            "--output",
            output,
        ]

    async def run(
        self, gff3: str, blastp: str, output: str, container_name: str
    ) -> SyntenyRunResult:
        process = await asyncio.create_subprocess_exec(
            *self.build_command(gff3, blastp, output, container_name),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return SyntenyRunResult(process.returncode or 0, stdout.decode(), stderr.decode())
