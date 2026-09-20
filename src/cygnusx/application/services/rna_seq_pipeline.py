"""RNA-seq MCP 流水线薄适配器。"""

from __future__ import annotations

from typing import Any

from cygnusx.application.schemas.pipeline import PipelinePrepareRequest


class RNASeqPipeline:
    flow_id = "rna_seq"
    pipeline_type = "rna_seq"

    def build_prepare_arguments(self, request: PipelinePrepareRequest) -> dict[str, Any]:
        parameters = {
            "raw_data_path": request.raw_data_path,
            "species": request.species,
            "Genome_Version": request.genome_version,
            "Library_Types": request.library_type,
            "project_name": request.project_name,
            "client": request.extra_parameters.get("client", "AI MCP"),
            "execution_mode": request.extra_parameters.get("execution_mode", "local"),
            "queue_id": request.extra_parameters.get("queue_id", "default"),
            **request.extra_parameters,
        }
        return {
            "name": request.task_name,
            "parameters": parameters,
            "sample_sheet": request.sample_sheet,
            "comparisons": request.comparisons,
            "execution_mode": parameters["execution_mode"],
        }
