"""reference_genomes API 层测试 —— TestClient + 鉴权覆盖 + 迷你真实构建。

数据：在 tmp_path 用 fixture 跑一次 indexer.build_index 迷你全量构建，
monkeypatch service.config_manager 指向临时 yaml；不起 PostgreSQL。
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cygnusx.api.deps import get_current_user_id
from cygnusx.middleware.rbac import require_admin
from cygnusx.reference_genomes import indexer, service
from cygnusx.reference_genomes.api import router
from cygnusx.reference_genomes.config import ConfigManager

FIXTURE_DIR = Path(__file__).parent / "reference_genomes" / "fixtures"

pytestmark = pytest.mark.skipif(
    not FIXTURE_DIR.exists(), reason="reference_genomes fixtures 缺失"
)


@pytest.fixture(scope="module")
def built_env(tmp_path_factory) -> Path:
    """迷你构建：返回临时 yaml 路径（含 species test-ath / 版本 fixture）。"""
    tmp_path = tmp_path_factory.mktemp("refgen")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for fx in FIXTURE_DIR.iterdir():
        if fx.name == "genome.fa.fai":
            continue
        shutil.copy(fx, data_dir / fx.name)
    raw = data_dir / "genome.fa"
    with open(raw, "rb") as fin, gzip.open(data_dir / "genome.fa.gz", "wb") as fout:
        fout.writelines(fin)
    raw.unlink()
    if (data_dir / "genome.fa.expected.json").exists():
        (data_dir / "genome.fa.expected.json").unlink()

    cfg = {
        "species": [
            {
                "id": "test-ath",
                "common_name": "测试拟南芥",
                "latin_name": "Arabidopsis thaliana",
                "taxonomy_id": "3702",
                "icon": "🌱",
                "versions": [
                    {
                        "id": "fixture",
                        "version_name": "FIX1",
                        "assembly_name": "FIX1",
                        "is_default": True,
                        "data_dir": str(data_dir),
                        "gene_index": "gene_index.db",
                        "stats": {"chromosomes": 2, "total_genes": 2, "genome_size": "1 Kb"},
                        "files": {
                            "fasta": {"path": "genome.fa.gz", "format": "genomic_fasta"},
                            "gff3": {"path": "tair10_genes.gff", "format": "gff3"},
                            "cds": {"path": "tair10_cds.fa", "format": "fasta_kv"},
                            "protein": {"path": "tair10_pep.fa", "format": "fasta_kv"},
                            "functional": {
                                "path": "tair10_functional.tsv",
                                "format": "tair_functional",
                            },
                            "go": {"path": "tair10_gaf.tsv", "format": "gaf"},
                            "go_obo": {"path": "go_terms.obo", "format": "obo"},
                            "kegg_ko": {"path": "kegg_ko.list", "format": "kegg_ko"},
                            "kegg_pathway": {
                                "path": "kegg_pathway.list",
                                "format": "kegg_pathway",
                            },
                            "kegg_pathway_name": {
                                "path": "kegg_pathway_name.list",
                                "format": "kegg_pathway_name",
                            },
                            "kegg_gene": {"path": "kegg_gene.list", "format": "kegg_gene"},
                        },
                    }
                ],
            }
        ]
    }
    yaml_path = tmp_path / "reference_genomes.yaml"
    yaml_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    indexer.build_index("fixture", only=None, config_path=str(yaml_path))
    assert (data_dir / "gene_index.db").exists()
    return yaml_path


@pytest.fixture()
def client(built_env: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(service, "config_manager", ConfigManager(str(built_env)))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/reference-genomes")

    # 复现 main.py 的全局异常处理（CygnusXError → status_code/detail）
    from fastapi.responses import JSONResponse

    from cygnusx.core.exceptions import CygnusXError

    @app.exception_handler(CygnusXError)
    async def _omic_error_handler(request, exc):  # noqa: ANN001
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.dependency_overrides[get_current_user_id] = lambda: "test-user"
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    return TestClient(app)


BASE = "/api/v1/reference-genomes"


class TestSpeciesAndVersion:
    def test_list_species(self, client) -> None:
        r = client.get(f"{BASE}/species")
        assert r.status_code == 200
        data = r.json()
        assert data["species"][0]["id"] == "test-ath"
        ver = data["species"][0]["genomeVersions"][0]
        assert ver["versionId"] == "fixture"
        assert ver["dataFiles"]["fasta"]["buildStatus"] == "ready"

    def test_version_detail(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture")
        assert r.status_code == 200
        d = r.json()
        assert d["buildStatus"] == "ready"
        assert d["indexed"] is True
        assert len(d["chromosomes"]) == 2  # genome.fa 有 seq1/seq2
        assert d["geneCount"] > 0

    def test_unknown_version_404(self, client) -> None:
        r = client.get(f"{BASE}/versions/nope")
        assert r.status_code == 404


class TestGeneSearch:
    def test_search_by_gene_id(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes",
                       params={"field": "gene_id", "q": "AT1G01010"})
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        item = d["items"][0]
        assert item["geneId"] == "AT1G01010"
        assert item["chromosome"] == "Chr1"
        assert item["annotation"] == "NAC domain containing protein 1"
        assert item["hasKegg"] is True

    def test_search_fts_annotation(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes",
                       params={"field": "annotation", "q": "NAC"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_empty_q_browse_mode(self, client) -> None:
        # q 为空 = 浏览模式：分页列出全部基因
        r = client.get(f"{BASE}/versions/fixture/genes", params={"q": ""})
        assert r.status_code == 200
        assert r.json()["total"] >= 2

    def test_empty_q_go_kegg_rejected(self, client) -> None:
        # go/kegg 反查必须有查询词
        r = client.get(f"{BASE}/versions/fixture/genes", params={"field": "go", "q": ""})
        assert r.status_code == 422

    def test_page_size_upper(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes",
                       params={"q": "AT", "page_size": 999})
        assert r.status_code == 422  # Query le=100

    def test_chromosome_filter(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes",
                       params={"q": "AT", "chromosome": "Chr1"})
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["chromosome"] == "Chr1"


class TestGeneDetail:
    def test_aggregate(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes/AT1G01010")
        assert r.status_code == 200
        d = r.json()
        assert d["gene"]["geneId"] == "AT1G01010"
        assert d["transcripts"], "应含转录本"
        assert d["sequenceAvailable"]["genomic"] is True

    def test_missing_gene_404(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes/NOPE123")
        assert r.status_code == 404


class TestSequences:
    def test_region_sequence(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/sequence",
                       params={"chrom": "seq1", "start": 1, "end": 10})
        assert r.status_code == 200
        assert r.json()["sequence"] == "A" * 10

    def test_region_too_large_400(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/sequence",
                       params={"chrom": "seq1", "start": 1, "end": 2_000_000})
        assert r.status_code == 400

    def test_fasta_format(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/sequence",
                       params={"chrom": "seq1", "start": 1, "end": 10, "format": "fasta"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert r.text.startswith(">")

    def test_gene_genomic_sequence(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/genes/AT1G01010/sequence",
                       params={"type": "genomic"})
        # 基因在 Chr1 上而 genome.fa 只有 seq1/seq2 → 404 或正常取决于染色体名；
        # 此处断言不为 500
        assert r.status_code in (200, 404)


class TestGoKegg:
    def test_go_list(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/go")
        assert r.status_code == 200
        assert r.json()["total"] > 0

    def test_go_genes_reverse(self, client) -> None:
        # fixture GAF 含 AT1G01010 → GO:0003700（真实行），基因在 genes 表中
        r = client.get(f"{BASE}/versions/fixture/go/GO:0003700/genes")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        assert d["items"][0]["geneId"] == "AT1G01010"

    def test_go_unknown_404(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/go/GO:9999999/genes")
        assert r.status_code == 404

    def test_kegg_pathways(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/kegg/pathways")
        assert r.status_code == 200


class TestSearchAndBatch:
    def test_version_search(self, client) -> None:
        r = client.get(f"{BASE}/versions/fixture/search", params={"q": "AT1G01010"})
        assert r.status_code == 200
        assert r.json()["genes"], "应命中基因"

    def test_global_search_species_hit(self, client) -> None:
        r = client.get(f"{BASE}/search", params={"q": "拟南芥"})
        assert r.status_code == 200
        assert r.json()["species"], "应命中物种 common_name"

    def test_batch(self, client) -> None:
        r = client.post(f"{BASE}/versions/fixture/genes/batch",
                        json={"geneIds": ["AT1G01010", "NOPE"]})
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 2
        assert d["found"] == 1

    def test_batch_over_limit_rejected(self, client) -> None:
        # schema max_length=500 → FastAPI 请求体校验 422
        r = client.post(f"{BASE}/versions/fixture/genes/batch",
                        json={"geneIds": [f"G{i}" for i in range(501)]})
        assert r.status_code == 422


class TestMapIdsAndReload:
    def test_map_ids_no_mapping(self, client) -> None:
        r = client.post(f"{BASE}/versions/fixture/map-ids",
                        json={"targetVersionId": "other", "ids": ["A", "B"]})
        assert r.status_code == 200
        d = r.json()
        assert d["totalCount"] == 2
        assert d["successCount"] == 0

    def test_reload(self, client) -> None:
        r = client.post(f"{BASE}/reload")
        assert r.status_code == 200
        assert r.json()["ok"] is True
