# Supplementary Materials README — CygnusX

Primary language: English. Chinese notes are added only where they clarify local context.

## 1. Package Overview

Project title: `CygnusX: Auditable Agent × Skill Infrastructure for Controlled Omics Analysis Delivery`

Team name: `CygnusX` | Team ID: `IBEC26-35` | Institution: `Huazhong Agricultural University` | Track: `Bioinformatics Platform`

This package contains `code / de-identified demo data / run results / interface screenshots / demo walkthroughs` and supports the claims made in the project report and technical abstract. 本包用于支撑项目报告与技术摘要中的全部量化结论。

## 2. Directory Structure

```text
submission_package/
  report.pdf
  technical_abstract.pdf
  supplementary_materials.pdf
  code/            # CygnusX repository (src/cygnusx, frontend, pipelines)
  data/            # de-identified demo inputs (samples.csv, contrasts.csv, test FASTQ)
  results/         # run archives: projects/<slug>/runs/<task>-<timestamp>/
  figures/         # F1 form submission, F2 Skill library, F3 agent workspace, F4 project history
  demo/            # walkthrough scripts for chains A (pass) / B (preflight-blocked) / C (manual review)
  README.md
```

## 3. Runtime Environment

- Operating system: `Linux (Ubuntu 22.04+); containerized pipeline execution via Apptainer/Singularity`
- Language and version: `Python >= 3.11 (FastAPI, SQLAlchemy 2 async, LangGraph); Node.js 20+ / Vue 3.4; PostgreSQL 15 + pgvector; Redis 7`
- Dependencies: `pyproject.toml + uv.lock (backend), frontend/package.json`
- Hardware: `8-core CPU / 16 GB RAM for platform services; pipeline runs containerized`

## 4. How to Run

```bash
# backend platform
uv sync
uv run uvicorn cygnusx.api.main:app --host 0.0.0.0 --port 8000

# frontend
cd frontend && npm ci && npm run dev

# tests (unit + contract)
uv run pytest tests/unit/domain/mas/ -q
uv run pytest tests/unit/test_agent_config_consistency.py -q

# delivery-package integrity check (built-in md5 Skill)
python pipelines/tools/skills/md5/scripts/verify_manifest.py \
  --input results/projects/<slug>/runs/<task>-<timestamp>/MD5SUMS \
  --output results/projects/<slug>/runs/<task>-<timestamp>/verification/
```

Expected output:

```text
- Web workbench reachable; form-based RNA-seq submission demo project loads.
- pytest pass summary for MAS domain tests and agent-config consistency.
- verification.tsv: one row per delivered file, status SUCCESS / MISSING / FAIL / ERROR;
  a valid delivery package returns all SUCCESS.
```

## 5. Data Description

- Source: `De-identified transcriptomic data from the HZAU genomics laboratory plant-genomics demo projects; reference genome/annotation from MSU/RAP-DB (academic use)`
- License / permission: `Demo subset only; original lab data not redistributed; no human genetic resources included`
- Format: `FASTQ (paired-end subset), CSV metadata (samples/contrasts), TSV count & DEG tables, Markdown delivery README`
- Size: `[confirm exact sample count / feature count / file size at packaging]`
- Preprocessing: `fastp QC; quality gates mapping rate >= 0.70, Q30 >= 0.80; reference version pinned in environment.json`

## 6. Results and Demo Links

- Main result file: `results/projects/<slug>/runs/<task>-<timestamp>/` (pipeline YAML version, parameters, logs, artifacts, environment.json, delivery README.md, verification/verification.tsv)
- Figures or screenshots: `figures/` (F1–F4 as listed in Section 2)
- Repository link: `[private during review; community edition URL once published]`
- Platform link: `[on-premise demo URL + reviewer credentials]`
- Demo video link: `[URL]`

## 7. Consistency Statement

All supplementary files are consistent with the project report and technical abstract. Any differences, updates, or limitations are listed here:

- `Efficiency figures (-75% / -90% / -80%) are measured as human operation + waiting time, excluding compute runtime; pilot-measured calibration is planned.`
- `The multi-role collaboration layer is an experimental preview, disabled by default (MAS_ENABLED off in production), and is not part of the claimed core path.`
- `The platform vision starts from research phenomena and progressively organizes verifiable computational experiments: research question -> computational experiment -> evidence chain -> experimental validation. Goal-oriented discovery is a research roadmap, not a current delivery claim; model-generated hypotheses do not replace expert judgment or experimental validation.`
- `[Add: exact demo species/sample set once packaged; repository/platform URLs before submission.]`
