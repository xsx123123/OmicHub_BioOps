"""Seqout MCP Tools 完整测试套件 — 覆盖所有 26 个工具的功能和错误处理"""

import json
import pytest
from tools.seqout import (
    # Search Tools
    seqout_search, seqout_search_geo, seqout_search_sra, seqout_search_structured,
    # Project Tools
    seqout_get_project_detail, seqout_get_project_metadata, seqout_get_project_citation, seqout_get_project_enriched,
    # Experiment & Sample Tools
    seqout_get_experiments, seqout_get_runs, seqout_get_run_download,
    seqout_get_sample_metadata, seqout_get_sample_detail, seqout_get_sample_manifest,
    # Resolution Tools
    seqout_resolve_accession, seqout_resolve_prj,
    # Ontology & Statistics Tools
    seqout_get_ontology_term, seqout_get_organisms, seqout_get_common_name,
    seqout_beacon_info, seqout_beacon_runs,
    seqout_get_stats_growth, seqout_get_organism_totals, seqout_get_platform_totals,
    # Download Tools
    seqout_get_download_links, seqout_get_metadata_csv,
)


# ==================== Helper Functions ====================

def validate_response(result: str, expect_success: bool = True):
    """验证响应格式是否符合 CygnusX 规范"""
    try:
        data = json.loads(result)
        assert "success" in data, "缺少 success 字段"
        assert "summary" in data, "缺少 summary 字段"
        
        if expect_success:
            assert data["success"] is True, f"预期成功但失败：{data.get('summary')}"
            assert "data" in data, "成功响应应包含 data 字段"
        else:
            # 失败时可能没有 data 字段
            pass
        
        return data
    except json.JSONDecodeError as e:
        pytest.fail(f"响应不是有效的 JSON: {result[:200]}... 错误：{e}")


# ==================== Search Tools Tests ====================

@pytest.mark.asyncio
async def test_seqout_search_basic():
    """测试基本关键词检索与输出字段结构"""
    result = await seqout_search(query="melanoma single cell", limit=2)
    data = validate_response(result)
    
    assert data["data"], "搜索结果应为非空列表或包含数据"
    if len(data["data"]) > 0:
        item = data["data"][0]
        assert "accession" in item, "搜索结果应包含 accession"
        assert "title" in item, "搜索结果应包含 title"


@pytest.mark.asyncio
async def test_seqout_search_limit():
    """测试 limit 参数控制返回数量"""
    result = await seqout_search(query="cancer", limit=3)
    data = validate_response(result)
    
    # 注意：实际返回数量取决于 API，这里只验证不超过 limit
    assert len(data["data"]) <= 3, f"返回结果不应超过 limit={3}"


@pytest.mark.asyncio
async def test_seqout_search_empty_result():
    """测试无匹配结果的优雅降级"""
    result = await seqout_search(query="nonexistent_dataset_xyz123", limit=1)
    data = validate_response(result, expect_success=False)
    
    assert "未找到" in data["summary"] or "异常" in data["summary"], \
        f"应返回友好的错误消息：{data['summary']}"


@pytest.mark.asyncio
async def test_seqout_search_geo():
    """测试 GEO 专用搜索"""
    result = await seqout_search_geo(query="GSE12345", limit=2)
    data = validate_response(result)
    
    # 验证是 GEO 相关的结果
    if len(data["data"]) > 0:
        item = data["data"][0]
        assert "accession" in item


@pytest.mark.asyncio
async def test_seqout_search_sra():
    """测试 SRA 专用搜索"""
    result = await seqout_search_sra(query="SRR123", limit=2)
    data = validate_response(result)
    
    if len(data["data"]) > 0:
        item = data["data"][0]
        assert "accession" in item


@pytest.mark.asyncio
async def test_seqout_search_structured():
    """测试结构化搜索（带物种过滤器）"""
    result = await seqout_search_structured(organism="Homo sapiens", assay="RNA-seq", limit=2)
    data = validate_response(result)
    
    # 可能返回空结果，但不应该报错
    if not data["success"]:
        assert "异常" in data["summary"] or "错误" in data["summary"]


# ==================== Project Tools Tests ====================

@pytest.mark.asyncio
async def test_seqout_get_project_detail():
    """测试项目详情获取"""
    result = await seqout_get_project_detail(accession="GSE12345")
    data = validate_response(result)
    
    if data["success"]:
        assert "data" in data
        project_data = data["data"]
        assert isinstance(project_data, dict), "项目详情应为字典"


@pytest.mark.asyncio
async def test_seqout_get_project_metadata():
    """测试项目元数据获取"""
    result = await seqout_get_project_metadata(accession="GSE12345")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_project_citation():
    """测试项目引用文献获取"""
    result = await seqout_get_project_citation(accession="GSE12345")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_project_enriched():
    """测试 AI 增强元数据获取"""
    result = await seqout_get_project_enriched(accession="GSE12345")
    validate_response(result)


# ==================== Experiment & Sample Tools Tests ====================

@pytest.mark.asyncio
async def test_seqout_get_experiments():
    """测试实验列表获取"""
    result = await seqout_get_experiments(study_accession="GSE12345")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_runs():
    """测试运行列表获取"""
    result = await seqout_get_runs(study_accession="GSE12345")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_run_download():
    """测试单个运行下载链接获取"""
    result = await seqout_get_run_download(run_accession="SRR1234567")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_sample_metadata():
    """测试样本元数据获取"""
    result = await seqout_get_sample_metadata(accession="GSM123456")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_sample_detail():
    """测试样本详细信息获取"""
    result = await seqout_get_sample_detail(accession="GSM123456")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_sample_manifest():
    """测试样本清单获取（核心功能）"""
    result = await seqout_get_sample_manifest(accession="GSE120575", max_samples=5)
    data = validate_response(result)
    
    if data["success"]:
        samples = data["data"]
        assert isinstance(samples, list), "样本清单应为列表"
        assert len(samples) <= 5, f"样本数不应超过 max_samples={5}"
        
        if len(samples) > 0:
            sample = samples[0]
            required_fields = ["sample_accession", "title", "characteristics", "source_name"]
            for field in required_fields:
                assert field in sample, f"样本应包含字段：{field}"


# ==================== Resolution Tools Tests ====================

@pytest.mark.asyncio
async def test_seqout_resolve_accession():
    """测试 accession 反查（核心功能）"""
    # 使用一个已知的 GSM 编号测试
    result = await seqout_resolve_accession(accession="GSM123456")
    data = validate_response(result)
    
    if data["success"]:
        assert "data" in data
        resolved = data["data"]
        # 应包含父项目信息
        assert "accession" in resolved or "project" in resolved or "study" in resolved


@pytest.mark.asyncio
async def test_seqout_resolve_prj():
    """测试 BioProject 解析"""
    result = await seqout_resolve_prj(prj_accession="PRJNA12345")
    validate_response(result)


# ==================== Ontology & Statistics Tools Tests ====================

@pytest.mark.asyncio
async def test_seqout_get_ontology_term():
    """测试本体论术语查询"""
    result = await seqout_get_ontology_term(term="tissue")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_organisms():
    """测试物种列表获取"""
    result = await seqout_get_organisms()
    data = validate_response(result)
    
    if data["success"]:
        assert isinstance(data["data"], list), "物种列表应为列表"
        assert len(data["data"]) > 0, "应至少有一个物种"


@pytest.mark.asyncio
async def test_seqout_get_common_name():
    """测试物种常用名称获取"""
    result = await seqout_get_common_name(organism="9606")  # Homo sapiens taxon_id
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_beacon_info():
    """测试 Beacon 元数据获取"""
    result = await seqout_beacon_info()
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_beacon_runs():
    """测试 Beacon 运行浏览"""
    result = await seqout_beacon_runs(skip=0, limit=5)
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_stats_growth():
    """测试数据库增长统计"""
    result = await seqout_get_stats_growth()
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_organism_totals():
    """测试物种实验总数统计"""
    result = await seqout_get_organism_totals()
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_platform_totals():
    """测试平台统计"""
    result = await seqout_get_platform_totals()
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_platform_totals_with_filter():
    """测试带过滤器的平台统计"""
    result = await seqout_get_platform_totals(platform="ILLUMINA")
    validate_response(result)


# ==================== Download Tools Tests ====================

@pytest.mark.asyncio
async def test_seqout_get_download_links():
    """测试 TSV 下载链接获取"""
    result = await seqout_get_download_links(study_accession="GSE12345")
    validate_response(result)


@pytest.mark.asyncio
async def test_seqout_get_metadata_csv():
    """测试元数据 CSV 下载"""
    result = await seqout_get_metadata_csv(study_accession="GSE12345")
    validate_response(result)


# ==================== Output Format Consistency Tests ====================

@pytest.mark.asyncio
async def test_all_tools_output_format_consistency():
    """测试所有工具的输出格式一致性（遵循 CygnusX 规范）"""
    tools_test_cases = [
        (seqout_search("test", 1), "seqout_search"),
        (seqout_search_geo("test", 1), "seqout_search_geo"),
        (seqout_search_sra("test", 1), "seqout_search_sra"),
        (seqout_search_structured("Homo sapiens", "RNA-seq", 1), "seqout_search_structured"),
        (seqout_get_project_detail("GSE12345"), "seqout_get_project_detail"),
        (seqout_get_project_metadata("GSE12345"), "seqout_get_project_metadata"),
        (seqout_get_project_citation("GSE12345"), "seqout_get_project_citation"),
        (seqout_get_project_enriched("GSE12345"), "seqout_get_project_enriched"),
        (seqout_get_experiments("GSE12345"), "seqout_get_experiments"),
        (seqout_get_runs("GSE12345"), "seqout_get_runs"),
        (seqout_get_run_download("SRR1234567"), "seqout_get_run_download"),
        (seqout_get_sample_metadata("GSM123456"), "seqout_get_sample_metadata"),
        (seqout_get_sample_detail("GSM123456"), "seqout_get_sample_detail"),
        (seqout_get_sample_manifest("GSE12345", 1), "seqout_get_sample_manifest"),
        (seqout_resolve_accession("GSM123456"), "seqout_resolve_accession"),
        (seqout_resolve_prj("PRJNA12345"), "seqout_resolve_prj"),
        (seqout_get_ontology_term("tissue"), "seqout_get_ontology_term"),
        (seqout_get_organisms(), "seqout_get_organisms"),
        (seqout_get_common_name("9606"), "seqout_get_common_name"),
        (seqout_beacon_info(), "seqout_beacon_info"),
        (seqout_beacon_runs(skip=0, limit=1), "seqout_beacon_runs"),
        (seqout_get_stats_growth(), "seqout_get_stats_growth"),
        (seqout_get_organism_totals(), "seqout_get_organism_totals"),
        (seqout_get_platform_totals(), "seqout_get_platform_totals"),
        (seqout_get_download_links("GSE12345"), "seqout_get_download_links"),
        (seqout_get_metadata_csv("GSE12345"), "seqout_get_metadata_csv"),
    ]
    
    success_count = 0
    failure_count = 0
    
    for coro, name in tools_test_cases:
        try:
            result = await coro
            data = validate_response(result)
            
            if data["success"]:
                success_count += 1
            else:
                # 失败也是正常的（如无效 accession），只要格式正确即可
                success_count += 1
                
        except Exception as e:
            failure_count += 1
            pytest.fail(f"{name} 调用失败：{str(e)}")
    
    print(f"\n✅ 所有工具格式验证完成：成功={success_count}, 失败={failure_count}")
    assert failure_count == 0, f"有 {failure_count} 个工具调用失败"


# ==================== Rate Limit & Error Handling Tests ====================

@pytest.mark.asyncio
async def test_invalid_accession_handling():
    """测试无效 accession 的错误处理"""
    invalid_accessions = [
        ("seqout_get_project_detail", seqout_get_project_detail("GSE999999999")),
        ("seqout_resolve_accession", seqout_resolve_accession("GSM999999999")),
        ("seqout_get_sample_manifest", seqout_get_sample_manifest("GSE999999999", 1)),
    ]
    
    for name, coro in invalid_accessions:
        result = await coro
        data = validate_response(result, expect_success=False)
        
        # 应返回友好的错误消息，而不是崩溃
        assert "success" in data and data["success"] is False, \
            f"{name} 对无效 accession 应返回失败状态"
        assert "summary" in data, f"{name} 应提供错误描述"


@pytest.mark.asyncio
async def test_context_window_protection():
    """测试上下文窗口保护（限制返回数量）"""
    # 测试 search 工具的 limit 参数
    result_large = await seqout_search(query="cancer", limit=10)
    data_large = validate_response(result_large)
    
    result_small = await seqout_search(query="cancer", limit=2)
    data_small = validate_response(result_small)
    
    # 小 limit 的结果不应超过 2 条
    assert len(data_small["data"]) <= 2, \
        f"limit=2 时应最多返回 2 条，实际返回{len(data_small['data'])}"
    
    print(f"\n✅ 上下文窗口保护验证：limit=2 时返回{len(data_small['data'])}条结果")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
