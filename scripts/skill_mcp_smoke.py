#!/usr/bin/env python3
"""Skill & MCP 多线程沙箱冒烟验证

按平台前端调用样式验证现阶段所有 skill 与 MCP 是否可运行：
- Skill：SKILL.md 指令约定脚本位于 /workspace/.skills/<skill_id>/，
  本脚本将技能目录物化到沙箱容器同一路径，再用与平台 sandbox_execute
  相同的解释器入口（python/r/bash）执行每个脚本的冒烟命令。
- MCP：在 omichub-web 容器内用平台自己的 MCPService/MCPClient 代码路径
  （等价于前端 POST /mcp/servers/{id}/test + invoke），并对 use_skill
  依赖的 skill_store 读取链路做全量验证。
- 镜像：对所有被调用的运行时镜像做包/工具清单盘点，并与各技能声明的
  运行环境需求交叉比对。

用法：
    python scripts/skill_mcp_smoke.py [--workers 8] [--only skills|mcp|inventory]
报告输出：logs/skill_mcp_smoke/<时间戳>/{report.md,result.json}
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = Path("/data/omichub/skills")
WEB_CONTAINER = "omichub-web"

# ---------------------------------------------------------------------------
# 镜像注册表：image + exec 前缀（与平台实际执行入口保持一致）
# ---------------------------------------------------------------------------
IMAGES: dict[str, dict] = {
    # Studio 默认运行时（micromamba base，等价 sandbox-agent 的 CMD 环境）
    "core": {
        "image": "omichub-analysis:core-2026.07",
        "prefix": ["micromamba", "run", "-n", "base"],
        "desc": "Studio 默认分析运行时",
    },
    "plot": {
        "image": "omichub-analysis:plot-2026.07",
        "prefix": ["micromamba", "run", "-n", "base"],
        "desc": "科研绘图运行时",
    },
    "scrna": {
        "image": "omichub-analysis:scrna-2026.07",
        "prefix": ["micromamba", "run", "-n", "base"],
        "desc": "单细胞分析运行时",
    },
    # 聊天沙箱池镜像（conda env 直接在 PATH）
    "base": {
        "image": "omichub/sandbox-base:latest",
        "prefix": [],
        "desc": "聊天沙箱池 sandbox-base",
    },
    # 工具箱专属镜像
    "deg": {
        "image": "omichub-r-deg:v1",
        "prefix": [],
        "desc": "DEG 工具箱镜像",
    },
    "enr": {
        "image": "omichub-r-enrichment:v1",
        "prefix": [],
        "desc": "富集工具箱镜像",
    },
    "term": {
        "image": "omichub/sandbox-terminal:latest",
        "prefix": [],
        "desc": "终端工具镜像",
    },
}

CONTAINERS: dict[str, str] = {}
_CONTAINER_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# 技能 → 主测镜像映射（依据各技能 references/environment.md 声明）
# ---------------------------------------------------------------------------
SKILL_PRIMARY_IMAGE: dict[str, str] = {
    "blast": "core",
    "gaf2go": "core",
    "gene-matrix": "core",
    "genome-tools": "core",
    "gffconvert": "core",
    "library-type": "core",
    "md5": "core",
    "rmats": "core",
    "software-manager": "core",
    "deg": "core",
    "enrichments": "core",
    "tissue-specific-genes": "core",
    "wgcna": "core",
    "maftools-gistic2": "core",
    "dotplot": "core",
    "r-plot-library": "core",
    "go-annotation": "core",
    "kegg-pull": "core",
    "scrna-annotation-ref": "scrna",
    "scrna-annotation-stats": "scrna",
    "scrna-deg-analysis": "scrna",
    "scrna-object-convert": "scrna",
    "scrna-recluster": "scrna",
    "scrna-seq": "scrna",
    "scrna-tcell-projectils": "scrna",
    "mutational-patterns": "scrna",
    "human-mouse-cell-annotation": "scrna",
    "plant-cell-annotation": "scrna",
    "scrna-pipeline-overview": "scrna",
    # 依赖平台生信工具链的技能：主测聊天沙箱池镜像，同时旁证 core
    "atac-tools": "base",
    "fastq-screen": "base",
    "data-deliver": "base",
    "logger-plugin": "base",
    # 纯提示词技能
    "omichub-frontend-design": None,
    "scrna-quarto-report": None,
}
# 额外旁证镜像（工具链技能顺带在 core 试一次；deg/enrichments 在工具箱镜像试一次）
SKILL_EXTRA_IMAGES: dict[str, list[str]] = {
    "atac-tools": ["core"],
    "fastq-screen": ["core"],
    "data-deliver": ["core"],
    "logger-plugin": ["core"],
    "deg": ["deg"],
    "enrichments": ["enr"],
}

# ---------------------------------------------------------------------------
# 各技能声明的运行环境需求（摘自 references/environment.md）
# ---------------------------------------------------------------------------
SKILL_REQUIREMENTS: dict[str, dict] = {
    "deg": {"r": ["optparse", "DESeq2", "ggplot2", "pheatmap", "RColorBrewer", "dplyr", "tidyr"],
            "py": ["pandas", "numpy", "scipy", "plotly", "rich", "loguru"], "cli": []},
    "enrichments": {"r": ["optparse", "ontologyIndex", "data.table", "dplyr"],
                    "py": ["pandas", "loguru"], "cli": []},
    "dotplot": {"r": ["optparse", "jsonlite", "tidyverse", "ggplot2"], "py": [], "cli": []},
    "maftools-gistic2": {"r": ["optparse", "jsonlite", "data.table", "dplyr", "tidyr"], "py": [], "cli": []},
    "mutational-patterns": {"r": ["optparse", "jsonlite", "MutationalPatterns", "NMF", "ggplot2",
                                  "patchwork", "ggpubr", "BSgenome.Hsapiens.UCSC.hg38"], "py": [], "cli": []},
    "r-plot-library": {"r": ["optparse", "jsonlite", "ggplot2", "ggVennDiagram", "patchwork",
                             "dplyr", "ggrepel", "ggpubr", "ggupset", "tidyverse"], "py": [], "cli": []},
    "tissue-specific-genes": {"r": ["optparse", "jsonlite", "data.table", "dplyr", "tidyr",
                                    "tibble", "stringr"], "py": [], "cli": []},
    "wgcna": {"r": ["optparse", "jsonlite", "WGCNA", "dplyr", "tibble", "readr", "ggplot2"],
              "py": [], "cli": []},
    "go-annotation": {"r": [], "py": ["requests"], "cli": []},
    "scrna-annotation-ref": {"r": ["optparse", "SingleR", "celldex", "CellID", "Seurat",
                                   "BiocParallel", "HGNChelper", "openxlsx", "qs"], "py": [], "cli": []},
    "scrna-annotation-stats": {"r": ["Seurat", "tidyverse", "ggplot2", "optparse", "jsonlite",
                                     "gt", "scCustomize", "ggrepel", "log4r", "crayon"], "py": [], "cli": []},
    "scrna-deg-analysis": {"r": ["Seurat", "tidyverse", "ggplot2", "ggrepel", "log4r", "crayon",
                                 "optparse", "jsonlite"], "py": ["pandas"], "cli": []},
    "scrna-object-convert": {"r": ["Seurat", "getopt", "log4r", "yaml", "stringr", "crayon",
                                   "praise", "reticulate"], "py": [], "cli": []},
    "scrna-recluster": {"r": ["Seurat", "log4r", "crayon", "ggplot2", "optparse", "jsonlite"],
                        "py": [], "cli": []},
    "scrna-seq": {"r": ["optparse", "jsonlite", "Seurat", "infercnv", "AnnoProbe", "dplyr",
                        "tibble", "ggplot2"], "py": [], "cli": []},
    "scrna-tcell-projectils": {"r": ["Seurat", "ProjecTILs", "scCustomize", "optparse", "jsonlite",
                                     "ggplot2", "patchwork", "viridis", "forcats", "dplyr"], "py": [], "cli": []},
    "scrna-pipeline-overview": {"r": ["Seurat", "harmony", "DoubletFinder", "celda", "SingleR",
                                      "celldex", "CellID", "scCustomize", "qs", "clustree"], "py": [], "cli": []},
    "atac-tools": {"r": [], "py": [], "cli": ["python3", "bedtools"]},
    "fastq-screen": {"r": [], "py": [], "cli": ["python3", "fastq_screen"]},
    "data-deliver": {"r": [], "py": [], "cli": ["python3", "rnaflow-cli"]},
    "kegg-pull": {"r": [], "py": [], "cli": ["python3"]},
    "logger-plugin": {"r": [], "py": ["snakemake_logger_plugin_rich_loguru"], "cli": ["snakemake"]},
    # 纯标准库 Python 技能
    **{k: {"r": [], "py": [], "cli": ["python3"]} for k in
       ["blast", "gaf2go", "gene-matrix", "genome-tools", "gffconvert", "library-type",
        "md5", "rmats", "software-manager"]},
}

R_BASE_PACKAGES = {
    "base", "stats", "utils", "grDevices", "graphics", "methods", "datasets", "tools",
    "parallel", "grid", "splines", "tcltk", "compiler", "MASS", "lattice", "nlme",
    "survival", "Matrix", "boot", "class", "cluster", "codetools", "foreign",
    "KernSmooth", "mgcv", "nnet", "rpart", "spatial", "stats4",
}


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return 124, out + err + "\n[TIMEOUT]"
    except Exception as e:  # noqa: BLE001
        return 125, str(e)


def docker_exec(container: str, cmd: list[str], timeout: int = 180, user: str | None = None) -> tuple[int, str]:
    full = ["docker", "exec"]
    if user:
        full += ["-u", user]
    full += [container, *cmd]
    return run(full, timeout=timeout)


def ensure_container(key: str) -> str:
    """为镜像启动（或复用）一个冒烟容器，返回容器名。"""
    with _CONTAINER_LOCK:
        if key in CONTAINERS:
            return CONTAINERS[key]
        name = f"smoke-{key}-{datetime.now().strftime('%H%M%S')}"
        spec = IMAGES[key]
        rc, out = run(
            ["docker", "run", "-d", "--name", name, "--entrypoint", "sleep",
             spec["image"], "infinity"],
            timeout=120,
        )
        if rc != 0:
            raise RuntimeError(f"启动容器失败 {spec['image']}: {out.strip()[:300]}")
        CONTAINERS[key] = name
        return name


# ---------------------------------------------------------------------------
# 脚本发现与依赖提取
# ---------------------------------------------------------------------------
def discover_scripts(skill_dir: Path) -> list[Path]:
    scripts = []
    sdir = skill_dir / "scripts"
    if not sdir.is_dir():
        return scripts
    for p in sorted(sdir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix in {".py", ".r", ".R", ".sh"}:
            scripts.append(p)
        elif p.suffix == "":
            head = p.read_bytes()[:64].decode(errors="replace")
            if "Rscript" in head or "python" in head or "bash" in head:
                scripts.append(p)
    return scripts


def classify_script(p: Path) -> str:
    if p.suffix == ".py":
        return "python"
    if p.suffix in {".r", ".R"}:
        return "r"
    if p.suffix == ".sh":
        return "bash"
    head = p.read_bytes()[:64].decode(errors="replace")
    if "Rscript" in head:
        return "r"
    if "python" in head:
        return "python"
    return "bash"


_LIB_RE = re.compile(r"\b(?:library|require)\(\s*[\"']?([A-Za-z][A-Za-z0-9._]*)[\"']?\s*[,)]")
_REQNS_RE = re.compile(r"requireNamespace\(\s*[\"']([A-Za-z][A-Za-z0-9._]*)[\"']")
_COLON_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9._]*)::")


def extract_r_packages(script: Path) -> set[str]:
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    pkgs = set(_LIB_RE.findall(text)) | set(_REQNS_RE.findall(text)) | set(_COLON_RE.findall(text))
    # 过滤误匹配：常见非包名 token
    junk = {"function", "if", "for", "while", "return", "NULL", "TRUE", "FALSE", "c", "list",
            "package_name", "pkg", "p", "x", "i", "n", "X", "df", "env", "self"}
    return {p for p in pkgs if p not in junk and p not in R_BASE_PACKAGES}


# ---------------------------------------------------------------------------
# 单技能冒烟（平台样式：/workspace/.skills/<id> + python/r/bash 执行）
# ---------------------------------------------------------------------------
MISSING_PATTERNS = re.compile(
    r"ModuleNotFoundError|ImportError|there is no package called|"
    r"Error in library|could not be loaded|command not found|"
    r"Missing required command|No such file or directory|not found",
    re.IGNORECASE,
)
HELP_PATTERNS = re.compile(r"usage:|Usage:|--help|options:|Options:|选项", re.IGNORECASE)


def materialize_skill(container: str, skill_id: str, prefix: list[str]) -> tuple[bool, str]:
    src = SKILLS_DIR / skill_id
    # 平台约定路径：/workspace/.skills/<skill_id>
    rc, out = docker_exec(container, ["mkdir", "-p", "/workspace/.skills"], user="root", timeout=30)
    if rc != 0:
        return False, f"mkdir 失败: {out[:200]}"
    rc, out = run(["docker", "cp", str(src), f"{container}:/workspace/.skills/{skill_id}"], timeout=120)
    if rc != 0:
        return False, f"docker cp 失败: {out[:200]}"
    rc, out = docker_exec(
        container, ["chown", "-R", "10001:10001", f"/workspace/.skills/{skill_id}"],
        user="root", timeout=60,
    )
    if rc != 0:
        # 非 root 镜像（如 conda root 用户）chown 失败可忽略
        pass
    return True, ""


def smoke_skill_on_image(skill_id: str, image_key: str) -> dict:
    spec = IMAGES[image_key]
    prefix = spec["prefix"]
    result = {
        "skill": skill_id,
        "image_key": image_key,
        "image": spec["image"],
        "scripts": [],
        "status": "PASS",
        "notes": [],
    }
    try:
        container = ensure_container(image_key)
    except Exception as e:  # noqa: BLE001
        result["status"] = "ERROR"
        result["notes"].append(f"容器启动失败: {e}")
        return result

    ok, msg = materialize_skill(container, skill_id, prefix)
    if not ok:
        result["status"] = "ERROR"
        result["notes"].append(msg)
        return result

    scripts = discover_scripts(SKILLS_DIR / skill_id)
    if not scripts:
        result["status"] = "SKIP"
        result["notes"].append("无 scripts（纯提示词技能）")
        return result

    # R 包依赖一次性预检（并集）
    r_pkgs: set[str] = set()
    for p in scripts:
        if classify_script(p) == "r":
            r_pkgs |= extract_r_packages(p)
    if r_pkgs:
        check_code = (
            "pkgs <- strsplit('" + ",".join(sorted(r_pkgs)) + "', ',')[[1]];"
            "miss <- pkgs[!vapply(pkgs, function(p) requireNamespace(p, quietly=TRUE), logical(1))];"
            "if (length(miss)) { cat('MISSING:', paste(miss, collapse=','), '\\n') } else { cat('ALL_OK\\n') }"
        )
        rc, out = docker_exec(container, prefix + ["Rscript", "-e", check_code], timeout=180)
        missing = []
        for line in out.splitlines():
            if line.startswith("MISSING:"):
                missing = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
        if missing:
            result["notes"].append(f"R 包缺失: {', '.join(missing)}")

    for p in scripts:
        kind = classify_script(p)
        rel = f"/workspace/.skills/{skill_id}/scripts/{p.relative_to(SKILLS_DIR / skill_id / 'scripts')}"
        entry = {"skill": skill_id, "script": p.name, "kind": kind, "verdict": "?", "detail": ""}
        if kind == "python":
            rc, out = docker_exec(container, prefix + ["python", rel, "--help"], timeout=180)
        elif kind == "r":
            rc, out = docker_exec(container, prefix + ["Rscript", rel, "--help"], timeout=300)
        else:
            if p.name == "check_env.sh":
                rc, out = docker_exec(container, prefix + ["bash", rel], timeout=180)
            else:
                rc, out = docker_exec(container, ["bash", "-n", rel], timeout=60)
                if rc == 0:
                    entry["verdict"] = "SYNTAX_OK"
                    result["scripts"].append(entry)
                    continue
        out_tail = out.strip()[-800:]
        if rc == 0:
            entry["verdict"] = "PASS"
        elif HELP_PATTERNS.search(out) and ("--help" in out or "usage" in out.lower()):
            # 非 argparse/optparse 脚本对 --help 报错但解释器与依赖正常
            entry["verdict"] = "PASS(help)" if rc in (0, 1, 2) else "WARN"
        elif MISSING_PATTERNS.search(out):
            entry["verdict"] = "FAIL"
            result["status"] = "FAIL"
        elif rc == 124:
            entry["verdict"] = "TIMEOUT"
            result["status"] = "FAIL" if result["status"] == "PASS" else result["status"]
        else:
            entry["verdict"] = "WARN"
        entry["detail"] = " | ".join(
            ln.strip() for ln in out_tail.splitlines() if ln.strip()
        )[-400:]
        result["scripts"].append(entry)
        if entry["verdict"] == "FAIL" and result["status"] == "PASS":
            result["status"] = "FAIL"
    if result["status"] == "PASS" and any(
        s["verdict"].startswith("WARN") for s in result["scripts"]
    ):
        result["status"] = "WARN"
    return result


# ---------------------------------------------------------------------------
# MCP 验证（平台代码路径：omichub-web 容器内 MCPService/MCPClient）
# ---------------------------------------------------------------------------
MCP_SAFE_CALLS = {
    "omichub-platform": ("platform_list_flows", {}),
    "omichub-pipelines": ("list_available_pipelines", {}),
    "omichub-tools": ("omichub_search_memory", {"query": "smoke-test"}),
    "ensmbl": ("translate_sequence", {"sequence": "ATGGCC", "genetic_code": 1}),
    "go-server": ("get_go_term", {"id": "GO:0008150"}),
}

MCP_SNIPPET = r"""
import asyncio, json, sys

NAME = sys.argv[1]
TOOL = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ""
ARGS = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

async def main():
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.application.services.mcp_service import MCPService
    out = {"server": NAME}
    factory = get_session_factory()
    async with factory() as db:
        svc = MCPService(db)
        server = await svc._repo.get_by_name(NAME)
        if server is None:
            out["ok"] = False; out["error"] = "server not found"; print(json.dumps(out, ensure_ascii=False)); return
        out["transport"] = str(server.transport)
        try:
            tools = await svc.list_tools(server.id)
            out["ok"] = True
            out["tool_count"] = len(tools)
            out["tools"] = [t.name for t in tools][:60]
        except Exception as e:
            out["ok"] = False; out["error"] = f"list_tools: {e}"
            print(json.dumps(out, ensure_ascii=False)); return
        if TOOL:
            try:
                res = await svc._client.call_tool(server, TOOL, ARGS, user_id="smoke-test")
                payload = res.get("result") if isinstance(res, dict) else None
                out["call_ok"] = bool(
                    isinstance(res, dict)
                    and res.get("success")
                    and not (isinstance(payload, dict) and payload.get("isError"))
                )
                out["call_result"] = json.dumps(res, ensure_ascii=False)[:1200]
            except Exception as e:
                out["call_ok"] = False
                out["call_error"] = str(e)[:600]
    print(json.dumps(out, ensure_ascii=False))

asyncio.run(main())
"""

USE_SKILL_SNIPPET = r"""
import json
from omichub.infrastructure.skills import skill_store
from omichub.core.config import get_settings
from pathlib import Path

settings = get_settings()
skills_dir = Path(settings.skills_dir)
if not skills_dir.is_absolute():
    skills_dir = Path("/app") / settings.skills_dir
disk_names = sorted(p.name for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
rows = []
for name in disk_names:
    body = skill_store.read_skill_body(name)
    files = skill_store.list_skill_files(name)
    rows.append({
        "skill_id": name,
        "body_ok": bool(body and body.strip()),
        "body_len": len(body or ""),
        "resource_count": len(files or []),
    })
print(json.dumps({"skills_dir": str(skills_dir), "rows": rows}, ensure_ascii=False))
"""


def mcp_test_one(name: str, tool: str = "", args: dict | None = None) -> dict:
    cmd = [
        "docker", "exec", WEB_CONTAINER,
        "/app/.venv/bin/python", "-c", MCP_SNIPPET, name, tool, json.dumps(args or {}),
    ]
    rc, out = run(cmd, timeout=180)
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                parsed["rc"] = rc
                return parsed
            except json.JSONDecodeError:
                continue
    return {"server": name, "ok": False, "error": f"无法解析输出 rc={rc}: {out.strip()[-400:]}"}


def use_skill_chain_test() -> dict:
    rc, out = run(
        ["docker", "exec", WEB_CONTAINER, "/app/.venv/bin/python", "-c", USE_SKILL_SNIPPET],
        timeout=120,
    )
    for line in reversed(out.strip().splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"error": f"rc={rc}: {out.strip()[-300:]}"}


def mcp_servers_from_db() -> list[str]:
    rc, out = run(
        ["docker", "exec", "omichub-db", "psql", "-U", "omichub", "-d", "omichub",
         "-t", "-A", "-c", "SELECT name FROM mcp_servers WHERE is_enabled ORDER BY name;"],
        timeout=30,
    )
    if rc != 0:
        return list(MCP_SAFE_CALLS.keys())
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# 镜像清单盘点
# ---------------------------------------------------------------------------
INVENTORY_SNIPPET = r"""
import json, shutil, subprocess, sys

def sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr or "").strip()
    except Exception as e:
        return f"ERR:{e}"

out = {}
out["python"] = sh("python --version 2>&1") or sh("python3 --version 2>&1")
out["r"] = sh("Rscript --version 2>&1")
pip_raw = sh("pip list --format=freeze 2>/dev/null")
if "==" not in pip_raw:
    pip_raw = sh("pip3 list --format=freeze 2>/dev/null")
out["pip"] = sorted(
    ln.split("==")[0].lower()
    for ln in pip_raw.splitlines()
    if "==" in ln
)
rp = sh("Rscript -e 'cat(rownames(installed.packages()), sep=\"\\n\")' 2>/dev/null")
out["r_packages"] = sorted(x for x in rp.splitlines() if x.strip())
clis = ["bedtools", "fastq_screen", "bowtie", "bowtie2", "bwa", "minimap2", "samtools",
        "fastp", "STAR", "hisat2", "snakemake", "rnaflow-cli", "quarto", "node",
        "pandoc", "cellranger", "iqtree", "mafft", "fasttree", "raxmlHPC",
        "micromamba", "uv", "Rscript", "bash"]
out["cli"] = {c: bool(shutil.which(c)) for c in clis}
print("JSONINVENTORY" + json.dumps(out, ensure_ascii=False))
"""


def inventory_image(image_key: str) -> dict:
    spec = IMAGES[image_key]
    try:
        container = ensure_container(image_key)
    except Exception as e:  # noqa: BLE001
        return {"image_key": image_key, "image": spec["image"], "error": str(e)}
    # 解释器探测：micromamba 镜像 login shell 不继承 env PATH，直接试跑 --version
    pybin = ""
    for cand in ("python", "python3"):
        rc0, _ = docker_exec(container, spec["prefix"] + [cand, "--version"], timeout=30)
        if rc0 == 0:
            pybin = cand
            break
    if pybin:
        runner = spec["prefix"] + [pybin, "-c", INVENTORY_SNIPPET]
    else:
        runner = spec["prefix"] + ["bash", "-c", "echo NOPYTHON"]
    rc, out = docker_exec(container, runner, timeout=300)
    if "NOPYTHON" in out:
        rc2, out2 = docker_exec(
            container,
            ["bash", "-lc",
             "echo PY=$(python3 --version 2>&1||true); "
             "for t in bash python3 Rscript node samtools bedtools; do "
             "command -v $t >/dev/null && echo HAVE:$t; done"],
            timeout=60,
        )
        return {
            "image_key": image_key, "image": spec["image"], "desc": spec["desc"],
            "python": "无 python（终端镜像）", "r": "无 R", "pip": [], "r_packages": [],
            "cli": {t.split(":")[1]: True for t in out2.splitlines() if t.startswith("HAVE:")},
            "raw": out2.strip()[:200],
        }
    for line in out.splitlines():
        if line.startswith("JSONINVENTORY"):
            try:
                data = json.loads(line[len("JSONINVENTORY"):])
                data["image_key"] = image_key
                data["image"] = spec["image"]
                data["desc"] = spec["desc"]
                return data
            except json.JSONDecodeError:
                pass
    # 无 python 的镜像（如 terminal）退化到 bash 盘点
    rc2, out2 = docker_exec(
        container,
        ["bash", "-lc", "echo PY=$(python --version 2>&1||true); echo R=$(Rscript --version 2>&1||true); "
                        "for t in bash python python3 Rscript node; do command -v $t >/dev/null && echo HAVE:$t; done"],
        timeout=60,
    )
    return {
        "image_key": image_key, "image": spec["image"], "desc": spec["desc"],
        "error": f"inventory 解析失败 rc={rc}", "raw": (out + out2)[-500:],
    }


def gap_analysis(inventories: dict[str, dict]) -> list[dict]:
    """技能需求 × 主测镜像清单 交叉比对"""
    gaps = []
    for skill_id, req in SKILL_REQUIREMENTS.items():
        image_key = SKILL_PRIMARY_IMAGE.get(skill_id)
        if image_key is None:
            continue
        inv = inventories.get(image_key) or {}
        if inv.get("error") and "pip" not in inv:
            gaps.append({"skill": skill_id, "image": IMAGES[image_key]["image"],
                         "missing": ["<清单获取失败>"]})
            continue
        pip_set = set(inv.get("pip", []))
        r_set = set(inv.get("r_packages", []))
        cli_map = inv.get("cli", {})
        missing = []
        for p in req.get("py", []):
            if p.lower() not in pip_set:
                missing.append(f"py:{p}")
        for p in req.get("r", []):
            if p not in r_set:
                missing.append(f"R:{p}")
        for c in req.get("cli", []):
            if c == "python3":
                continue
            if not cli_map.get(c, False):
                missing.append(f"cli:{c}")
        gaps.append({
            "skill": skill_id,
            "image": IMAGES[image_key]["image"],
            "missing": missing,
        })
    return gaps


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def render_report(skill_results: list[dict], mcp_results: list[dict],
                  use_skill: dict, inventories: dict[str, dict],
                  gaps: list[dict], workers: int) -> str:
    lines = ["# Skill & MCP 沙箱冒烟报告", ""]
    lines.append(f"- 时间：{datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- 并发线程数：{workers}")
    lines.append(f"- 技能目录：{SKILLS_DIR}（前端样式路径 /workspace/.skills/<id>）")
    lines.append("")

    # 汇总
    total = len(skill_results)
    ok = sum(1 for r in skill_results if r["status"] in ("PASS", "SKIP"))
    warn = sum(1 for r in skill_results if r["status"] == "WARN")
    fail = sum(1 for r in skill_results if r["status"] in ("FAIL", "ERROR"))
    lines.append(f"## 汇总（技能执行单元 {total}：通过 {ok} / 告警 {warn} / 失败 {fail}）")
    lines.append("")

    lines.append("## 一、Skill 沙箱执行（平台样式）")
    lines.append("")
    lines.append("| 技能 | 镜像 | 结论 | 脚本明细 |")
    lines.append("|---|---|---|---|")
    for r in sorted(skill_results, key=lambda x: (x["skill"], x["image_key"])):
        detail = []
        for s in r["scripts"]:
            detail.append(f"{s['script']}:{s['verdict']}")
        notes = "；".join(r["notes"]) if r["notes"] else ""
        det = " ".join(detail) or notes
        lines.append(f"| {r['skill']} | `{r['image_key']}` {r['image']} | **{r['status']}** | {det} |")
    lines.append("")

    fail_details = [r for r in skill_results if r["status"] in ("FAIL", "ERROR", "WARN")]
    if fail_details:
        lines.append("### 需关注明细")
        lines.append("")
        for r in fail_details:
            lines.append(f"- **{r['skill']}** @ `{r['image']}` [{r['status']}]")
            for n in r["notes"]:
                lines.append(f"  - {n}")
            for s in r["scripts"]:
                if s["verdict"] not in ("PASS", "PASS(help)", "SYNTAX_OK"):
                    lines.append(f"  - {s['script']} [{s['verdict']}] {s['detail'][:220]}")
        lines.append("")

    lines.append("## 二、MCP 验证（平台 MCPService/MCPClient 代码路径）")
    lines.append("")
    lines.append("| Server | transport | 连接/发现 | 工具数 | 调用冒烟 |")
    lines.append("|---|---|---|---|---|")
    for m in mcp_results:
        conn = "✅" if m.get("ok") else f"❌ {str(m.get('error', ''))[:80]}"
        if "call_ok" in m:
            call = "✅" if m["call_ok"] else f"⚠️ {str(m.get('call_error', ''))[:80]}"
        elif m.get("ok"):
            call = "—（list_tools 通过）"
        else:
            call = "—"
        lines.append(
            f"| {m.get('server')} | {m.get('transport', '?')} | {conn} | "
            f"{m.get('tool_count', 0)} | {call} |"
        )
    lines.append("")

    lines.append("## 三、use_skill 读取链路（skill_store，全量技能）")
    lines.append("")
    rows = use_skill.get("rows", [])
    bad = [r for r in rows if not r["body_ok"]]
    lines.append(f"- skills_dir（web 容器内）：{use_skill.get('skills_dir', '?')}")
    lines.append(f"- 技能数：{len(rows)}；正文缺失：{len(bad)}")
    if bad:
        for r in bad:
            lines.append(f"  - ❌ {r['skill_id']} body_len={r['body_len']}")
    lines.append("")

    lines.append("## 四、调用镜像包/工具盘点")
    lines.append("")
    for key, inv in inventories.items():
        if inv.get("error") and "pip" not in inv:
            lines.append(f"### {key} — {inv['image']}（{inv.get('desc', '')}）")
            lines.append(f"- ❌ 清单获取失败：{inv.get('error')}")
            if inv.get("raw"):
                lines.append(f"- raw: `{inv['raw'][:200]}`")
            lines.append("")
            continue
        cli_ok = [c for c, v in inv.get("cli", {}).items() if v]
        cli_no = [c for c, v in inv.get("cli", {}).items() if not v]
        lines.append(f"### {key} — {inv['image']}（{inv.get('desc', '')}）")
        lines.append(f"- {inv.get('python', '?')} / {inv.get('r', '?')}")
        lines.append(f"- pip 包数：{len(inv.get('pip', []))}；R 包数：{len(inv.get('r_packages', []))}")
        lines.append(f"- CLI 可用：{', '.join(cli_ok) or '无'}")
        lines.append(f"- CLI 缺失：{', '.join(cli_no) or '无'}")
        lines.append("")

    lines.append("## 五、技能需求 × 镜像清单 缺口矩阵")
    lines.append("")
    lines.append("| 技能 | 主测镜像 | 缺失项 |")
    lines.append("|---|---|---|")
    for g in sorted(gaps, key=lambda x: x["skill"]):
        miss = ", ".join(g["missing"]) if g["missing"] else "✅ 无"
        lines.append(f"| {g['skill']} | `{g['image']}` | {miss} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", choices=["skills", "mcp", "inventory"], default=None)
    ap.add_argument("--filter", default=None, help="技能名正则过滤（调试用）")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = REPO / "logs" / "skill_mcp_smoke" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    skill_results: list[dict] = []
    mcp_results: list[dict] = []
    use_skill: dict = {}
    inventories: dict[str, dict] = {}

    print(f"[smoke] 输出目录: {out_dir}  workers={args.workers}")

    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="smoke") as pool:
        futures = {}

        # ---- 镜像盘点（先行，供缺口矩阵使用）----
        if args.only in (None, "inventory", "skills"):
            for key in IMAGES:
                futures[pool.submit(inventory_image, key)] = ("inventory", key)

        # ---- 技能冒烟 ----
        if args.only in (None, "skills"):
            pairs: list[tuple[str, str]] = []
            for skill_dir in sorted(SKILLS_DIR.iterdir()):
                if not skill_dir.is_dir():
                    continue
                sid = skill_dir.name
                if args.filter and not re.search(args.filter, sid):
                    continue
                primary = SKILL_PRIMARY_IMAGE.get(sid, "core")
                if primary:
                    pairs.append((sid, primary))
                for extra in SKILL_EXTRA_IMAGES.get(sid, []):
                    pairs.append((sid, extra))
            for sid, img in pairs:
                futures[pool.submit(smoke_skill_on_image, sid, img)] = ("skill", f"{sid}@{img}")

        # ---- MCP ----
        if args.only in (None, "mcp"):
            servers = mcp_servers_from_db()
            for name in servers:
                tool, targs = MCP_SAFE_CALLS.get(name, ("", {}))
                futures[pool.submit(mcp_test_one, name, tool, targs)] = ("mcp", name)
            futures[pool.submit(use_skill_chain_test)] = ("use_skill", "chain")

        done = 0
        for fut in as_completed(futures):
            kind, label = futures[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e), "label": label}
                print(f"[{done}] {kind}:{label} 异常: {e}")
            if kind == "inventory":
                inventories[label] = res
                n_py, n_r = len(res.get("pip", [])), len(res.get("r_packages", []))
                print(f"[{done}] 盘点 {label}: pip={n_py} R={n_r} err={res.get('error', '')[:60]}")
            elif kind == "skill":
                skill_results.append(res)
                print(f"[{done}] 技能 {res['skill']}@{res['image_key']}: {res['status']}")
            elif kind == "mcp":
                mcp_results.append(res)
                print(f"[{done}] MCP {res.get('server')}: ok={res.get('ok')} "
                      f"tools={res.get('tool_count')} call_ok={res.get('call_ok')}")
            elif kind == "use_skill":
                use_skill = res
                rows = res.get("rows", [])
                print(f"[{done}] use_skill 链路: {len(rows)} 技能, "
                      f"正文缺失 {sum(1 for r in rows if not r.get('body_ok'))}")

    gaps = gap_analysis(inventories) if inventories else []
    report = render_report(skill_results, sorted(mcp_results, key=lambda x: str(x.get('server'))),
                           use_skill, inventories, gaps, args.workers)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "result.json").write_text(
        json.dumps({
            "skills": skill_results,
            "mcp": mcp_results,
            "use_skill_chain": use_skill,
            "inventories": inventories,
            "gaps": gaps,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[smoke] 报告: {out_dir / 'report.md'}")

    # 清理冒烟容器
    for name in CONTAINERS.values():
        run(["docker", "rm", "-f", name], timeout=60)
    print("[smoke] 冒烟容器已清理")

    failed = [r for r in skill_results if r["status"] in ("FAIL", "ERROR")]
    failed_mcp = [m for m in mcp_results if not m.get("ok")]
    return 1 if (failed or failed_mcp) else 0


if __name__ == "__main__":
    sys.exit(main())
