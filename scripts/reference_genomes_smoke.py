"""参考基因组模块冒烟脚本 —— TestClient 本地验证全部关键端点（覆盖鉴权）。

用法：
    cd <repo> && PYTHONPATH=src .venv/bin/python scripts/reference_genomes_smoke.py

依赖 tair10 索引已构建（python -m omichub.reference_genomes.indexer build --version tair10）。
不起 PostgreSQL：仅挂载 reference_genomes router，鉴权依赖被 override。
"""

from __future__ import annotations

import sys
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omichub.api.deps import get_current_user_id
from omichub.middleware.rbac import require_admin
from omichub.reference_genomes.api import router

VERSION = "tair10"


def build_client() -> TestClient:
    from fastapi.responses import JSONResponse

    from omichub.core.exceptions import OmicHubError

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/reference-genomes")

    # 复现 main.py 的全局异常处理（OmicHubError → status_code/detail）
    @app.exception_handler(OmicHubError)
    async def _omic_error_handler(request, exc):  # noqa: ANN001
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.dependency_overrides[get_current_user_id] = lambda: "smoke-user"
    try:
        from omichub.api.deps import require_admin as deps_require_admin

        app.dependency_overrides[deps_require_admin] = lambda: "smoke-admin"
    except Exception:
        pass
    app.dependency_overrides[require_admin] = lambda: "smoke-admin"
    return TestClient(app)


PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name} {detail}")
    (PASSED if cond else FAILED).append(name)


def main() -> int:
    c = build_client()
    base = "/api/v1/reference-genomes"

    # 1. species
    r = c.get(f"{base}/species")
    check("GET /species 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        sp = r.json()["species"]
        ids = [s["id"] for s in sp]
        check("species 含 arabidopsis", "arabidopsis" in ids, f"ids={ids}")
        ath = next((s for s in sp if s["id"] == "arabidopsis"), None)
        ver = ath["genomeVersions"][0] if ath else {}
        files = ver.get("dataFiles", {})
        check(
            "tair10 dataFiles fasta/gff ready",
            files.get("fasta", {}).get("buildStatus") == "ready"
            and files.get("gff", {}).get("buildStatus") == "ready",
            f"fasta={files.get('fasta', {}).get('buildStatus')} gff={files.get('gff', {}).get('buildStatus')}",
        )

    # 2. version detail
    r = c.get(f"{base}/versions/{VERSION}")
    check("GET /versions/tair10 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        d = r.json()
        check("版本详情 buildStatus=ready", d.get("buildStatus") == "ready", f"={d.get('buildStatus')}")
        check("版本详情 染色体=7", len(d.get("chromosomes", [])) == 7, f"={len(d.get('chromosomes', []))}")
        check("版本详情 geneCount=28775", d.get("geneCount") == 28775, f"={d.get('geneCount')}")

    # 3. gene search by id
    t0 = time.perf_counter()
    r = c.get(f"{base}/versions/{VERSION}/genes", params={"field": "gene_id", "q": "AT1G01010"})
    ms = (time.perf_counter() - t0) * 1000
    check("genes?field=gene_id&q=AT1G01010 200", r.status_code == 200, f"{ms:.0f}ms")
    if r.status_code == 200:
        items = r.json()["items"]
        ok = bool(items) and items[0]["chromosome"] == "Chr1" and items[0]["start"] == 3631 \
            and items[0]["end"] == 5899 and items[0]["strand"] == "+" \
            and items[0]["annotation"] == "NAC domain containing protein 1"
        check("AT1G01010 Chr1:3631-5899(+) NAC annotation", ok, f"item={items[0] if items else None}")
        check("搜索毫秒级(<200ms)", ms < 200, f"{ms:.0f}ms")

    # 4. gene detail aggregate
    r = c.get(f"{base}/versions/{VERSION}/genes/AT1G01010")
    check("genes/AT1G01010 聚合 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        d = r.json()
        check("聚合 GO 非空", len(d.get("go", [])) > 0, f"go={len(d.get('go', []))}")
        kos = [k["koId"] for k in d.get("kegg", {}).get("kos", [])]
        check("聚合 KEGG 含 K28554", "K28554" in kos, f"kos={kos}")
        check("聚合 sequenceAvailable.genomic", d.get("sequenceAvailable", {}).get("genomic") is True)

    # 5. sequences
    r = c.get(f"{base}/versions/{VERSION}/genes/AT1G51370/sequence", params={"type": "cds"})
    check("AT1G51370 cds 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        seq = r.json()["sequence"]
        check("cds 以 ATGGTGGGTGGCAAGAAG 开头", seq.startswith("ATGGTGGGTGGCAAGAAG"), f"head={seq[:24]}")
    r = c.get(f"{base}/versions/{VERSION}/genes/AT1G51370/sequence", params={"type": "protein"})
    if r.status_code == 200:
        seq = r.json()["sequence"]
        check("protein 以 MVGGKKKTKICDKVSHEE 开头", seq.startswith("MVGGKKKTKICDKVSHEE"), f"head={seq[:20]}")
    else:
        check("AT1G51370 protein 200", False, f"status={r.status_code}")
    r = c.get(
        f"{base}/versions/{VERSION}/sequence",
        params={"chrom": "Chr1", "start": 3631, "end": 3730},
    )
    check("区间序列 Chr1:3631-3730 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        seq = r.json()["sequence"]
        check("区间长度=100", len(seq) == 100, f"len={len(seq)}")
        print(f"    seq head: {seq[:60]}")
    r = c.get(
        f"{base}/versions/{VERSION}/sequence",
        params={"chrom": "Chr1", "start": 1, "end": 2_000_000},
    )
    check("区间 >1Mb → 400", r.status_code == 400, f"status={r.status_code}")

    # 负链反向互补一致性：AT1G01020 (-)
    r = c.get(f"{base}/versions/{VERSION}/genes/AT1G01020")
    if r.status_code == 200:
        g = r.json()["gene"]
        if g.get("strand") == "-":
            r1 = c.get(
                f"{base}/versions/{VERSION}/sequence",
                params={"chrom": g["chromosome"], "start": g["start"], "end": g["end"], "strand": "-"},
            )
            r2 = c.get(
                f"{base}/versions/{VERSION}/sequence",
                params={"chrom": g["chromosome"], "start": g["start"], "end": g["end"], "strand": "+"},
            )
            if r1.status_code == 200 and r2.status_code == 200:
                from omichub.reference_genomes.sequence import reverse_complement

                check(
                    "负链=正链反向互补",
                    r1.json()["sequence"] == reverse_complement(r2.json()["sequence"]),
                )

    # 6. GO/KEGG reverse lookup
    r = c.get(f"{base}/versions/{VERSION}/genes", params={"field": "go", "q": "GO:0003700"})
    check("field=go&q=GO:0003700 反查非空", r.status_code == 200 and r.json()["total"] > 0,
          f"total={r.json().get('total') if r.status_code == 200 else r.status_code}")
    r = c.get(f"{base}/versions/{VERSION}/genes", params={"field": "kegg", "q": "glycolysis"})
    check("field=kegg&q=glycolysis 反查非空", r.status_code == 200 and r.json()["total"] > 0,
          f"total={r.json().get('total') if r.status_code == 200 else r.status_code}")

    # 7. unified search
    r = c.get(f"{base}/search", params={"q": "NAC"})
    check("GET /search?q=NAC 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        d = r.json()
        check("search NAC 命中 genes", len(d.get("genes", [])) > 0, f"={len(d.get('genes', []))}")
        check("search NAC 命中 goTerms", len(d.get("goTerms", [])) > 0, f"={len(d.get('goTerms', []))}")

    # 8. GO/KEGG browse + reverse gene list
    r = c.get(f"{base}/versions/{VERSION}/go", params={"q": "kinase"})
    check("go?q=kinase 200", r.status_code == 200, f"status={r.status_code}")
    r = c.get(f"{base}/versions/{VERSION}/kegg/pathways", params={"q": "Glycolysis"})
    check("kegg/pathways?q=Glycolysis 200", r.status_code == 200, f"status={r.status_code}")
    r = c.get(f"{base}/versions/{VERSION}/go/GO:0003700/genes")
    check("go/GO:0003700/genes 200", r.status_code == 200, f"status={r.status_code}")

    # 9. batch annotation
    r = c.post(f"{base}/versions/{VERSION}/genes/batch", json={"gene_ids": ["AT1G01010", "AT1G01020", "NOPE"]})
    check("batch 注释 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        d = r.json()
        check("batch found=2", d.get("found") == 2, f"found={d.get('found')}")

    # 10. reload（管理员覆盖）
    r = c.post(f"{base}/reload")
    check("POST /reload 200", r.status_code == 200, f"status={r.status_code}")

    print(f"\n==== 冒烟结果：{len(PASSED)} passed, {len(FAILED)} failed ====")
    if FAILED:
        print("失败项：", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
