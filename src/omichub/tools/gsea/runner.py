from __future__ import annotations

from dataclasses import dataclass

from omichub.tools.enrichments.runner import EnrichmentDockerRunner, EnrichmentRunResult


@dataclass
class GseaRunParams:
    input_path: str
    output_path: str
    gene_set: str
    go_annotation: str | None
    p_value_cutoff: float
    q_value_cutoff: float


class GseaDockerRunner(EnrichmentDockerRunner):
    def build_command(self, params: GseaRunParams, container_name: str) -> list[str]:
        settings = self._settings
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{settings.enrichment_data_mount}:/data/omichub",
            "--memory",
            settings.enrichment_memory,
            "--cpus",
            str(settings.enrichment_cpus),
            settings.enrichment_docker_image,
            "Rscript",
            "/app/run_gsea.R",
            "--input",
            params.input_path,
            "--output",
            params.output_path,
            "--gene_set",
            params.gene_set,
            "--p_value_cutoff",
            str(params.p_value_cutoff),
            "--q_value_cutoff",
            str(params.q_value_cutoff),
        ]
        if params.go_annotation:
            command.extend(["--go_annotation", params.go_annotation])
        return command

    async def run(self, params: GseaRunParams, container_name: str) -> EnrichmentRunResult:
        return await super().run(params, container_name)  # type: ignore[arg-type]
