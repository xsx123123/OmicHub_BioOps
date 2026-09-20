"""Seqout 公共数据库检索工具 — 完整覆盖 seqout.org API 所有主要接口"""

import httpx
import json
from typing import Any

from fastmcp import FastMCP

from core.logger import logger

BASE_URL = "https://seqout.org/api"


class SeqoutAPIError(Exception):
    """Seqout API 调用异常"""

    pass


def _parse_search_response(data: dict | list, limit: int = 5) -> list[dict]:
    """解析搜索结果，裁剪上下文避免爆炸"""
    if isinstance(data, dict):
        raw_items = data.get("results", data.get("hits", data))
    else:
        raw_items = data

    if not isinstance(raw_items, list):
        return []

    results = []
    for item in raw_items[:limit]:
        results.append({
            "accession": item.get("accession") or item.get("id"),
            "title": item.get("title"),
            "organism": item.get("organism"),
            "sample_count": item.get("samples_count") or item.get("n_samples"),
            "source_db": item.get("database"),
            "summary": (item.get("summary") or item.get("description") or "")[:200] + "...",
        })
    return results


def _parse_samples_response(data: dict | list, limit: int = 30) -> list[dict]:
    """解析样本清单，结构化 characteristics"""
    if isinstance(data, dict):
        samples_list = data.get("samples", data.get("data", []))
    else:
        samples_list = data

    if not isinstance(samples_list, list):
        return []

    manifest = []
    for s in samples_list[:limit]:
        manifest.append({
            "sample_accession": s.get("accession") or s.get("geo_accession"),
            "title": s.get("title"),
            "characteristics": s.get("characteristics_ch1") or s.get("attributes") or [],
            "source_name": s.get("source_name_ch1") or s.get("source_name"),
        })
    return manifest


async def _seqout_request(endpoint: str, params: dict | None = None) -> dict:
    """发送 Seqout API 请求，处理速率限制和错误"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(f"{BASE_URL}{endpoint}", params=params)
            response.raise_for_status()
            
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                raise SeqoutAPIError(f"服务端返回 HTML 页面：{response.text[:200]}")
            
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise SeqoutAPIError("触发速率限制 (Rate Limit)，请稍后重试")
            raise SeqoutAPIError(f"Seqout API 错误 {e.response.status_code}: {e.response.text[:200]}")
        except httpx.TimeoutException:
            raise SeqoutAPIError("请求超时")
        except json.JSONDecodeError:
            raise SeqoutAPIError("响应解析失败：非 JSON 格式")


# ==================== Search Tools ====================

@mcp.tool()
async def seqout_search(query: str, limit: int = 5) -> str:
    """在 GEO/SRA/ENA/GSA 等公共数据库中搜索匹配的组学/转录组/单细胞项目。
    
    :param query: 检索关键词（如:'CD8 T cell exhaust','HCC single cell','GSE151530'）
    :param limit: 最多返回的项目数量，推荐 3-5 条，避免上下文膨胀
    :return: JSON 格式的结果列表，包含 accession、title、organism 等字段
    
    示例:
        await seqout_search("melanoma single cell", limit=3)
        # 返回黑色素瘤单细胞数据集
    """
    try:
        data = await _seqout_request("/search", params={"q": query})
        results = _parse_search_response(data, limit)
        
        if not results:
            return json.dumps(
                {"success": False, "summary": f"未找到与关键词 '{query}' 相关的项目数据集。"},
                ensure_ascii=False,
                indent=2
            )
        
        return json.dumps({
            "success": True,
            "summary": f"找到 {len(results)} 个项目",
            "data": results,
            "next_steps": ["使用 seqout_get_project_detail 查看项目详情", "使用 seqout_get_sample_manifest 获取样本清单"],
        }, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"检索公共数据集发生异常：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_search_geo(query: str, limit: int = 5) -> str:
    """仅搜索 GEO 数据库中的微阵列和单细胞数据集。
    
    :param query: 检索关键词（如:'melanoma','single cell'）
    :param limit: 最多返回的项目数量，推荐 3-5 条
    :return: JSON 格式的结果列表，包含 accession、title、organism 等字段
    
    示例:
        await seqout_search_geo("HCC single cell", limit=3)
        # 返回 GEO 相关的单细胞肝癌数据集
    """
    try:
        data = await _seqout_request("/search/geo", params={"q": query})
        results = _parse_search_response(data, limit)
        
        if not results:
            return json.dumps({"success": False, "summary": f"未在 GEO 中找到与 '{query}' 相关的项目。"}, ensure_ascii=False, indent=2)
        
        return json.dumps({"success": True, "summary": f"GEO 中找到 {len(results)} 个项目", "data": results}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"GEO 搜索失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_search_sra(query: str, limit: int = 5) -> str:
    """仅搜索 SRA 数据库中的测序运行记录。
    
    :param query: 检索关键词（如:'human peripheral blood','mouse brain'）
    :param limit: 最多返回的项目数量，推荐 3-5 条
    :return: JSON 格式的结果列表，包含 accession、title、organism 等字段
    
    示例:
        await seqout_search_sra("human immune cell", limit=3)
        # 返回 SRA 中的人免疫细胞测序记录
    """
    try:
        data = await _seqout_request("/search/sra", params={"q": query})
        results = _parse_search_response(data, limit)
        
        if not results:
            return json.dumps({"success": False, "summary": f"未在 SRA 中找到与 '{query}' 相关的记录。"}, ensure_ascii=False, indent=2)
        
        return json.dumps({"success": True, "summary": f"SRA 中找到 {len(results)} 条记录", "data": results}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"SRA 搜索失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_search_structured(organism: str, assay: str, limit: int = 5) -> str:
    """使用元数据过滤器进行结构化搜索，精确匹配物种和实验类型。
    
    :param organism: 物种名称或_taxon_id（如:'Homo sapiens','Mus musculus',9606）
    :param assay: 实验类型（如:'RNA-seq','ChIP-seq','ATAC-seq'）
    :param limit: 最多返回的项目数量，推荐 3-5 条
    :return: JSON 格式的结果列表
    
    示例:
        await seqout_search_structured("Homo sapiens", "RNA-seq", limit=3)
        # 返回人类 RNA-seq 项目
    """
    try:
        params = {"organism": organism}
        if assay:
            params["assay"] = assay
        data = await _seqout_request("/search/structured", params=params)
        results = _parse_search_response(data, limit)
        
        if not results:
            return json.dumps({"success": False, "summary": f"未找到匹配物种'{organism}'和实验类型'{assay}'的项目。"}, ensure_ascii=False, indent=2)
        
        return json.dumps({"success": True, "summary": f"找到 {len(results)} 个项目", "data": results}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"结构化搜索失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Project Tools ====================

@mcp.tool()
async def seqout_get_project_detail(accession: str) -> str:
    """获取指定项目 (如 GSE151530, PRJNA12345) 的详细实验设计、测序技术平台及文献引用。
    
    :param accession: 项目唯一编号（如:'GSE151530','PRJNA678901'）
    :return: JSON 格式的项目详情，包含实验设计、平台、引用等信息
    
    示例:
        await seqout_get_project_detail("GSE151530")
        # 返回单细胞肝癌项目的详细信息
    """
    try:
        data = await _seqout_request(f"/project/{accession}")
        return json.dumps({"success": True, "summary": f"项目 {accession} 详情", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取项目 {accession} 详情失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_project_metadata(accession: str) -> str:
    """获取项目的标题和描述信息。
    
    :param accession: 项目唯一编号（如:'GSE151530','PRJNA678901'）
    :return: JSON 格式的元数据，包含 title、description 等字段
    
    示例:
        await seqout_get_project_metadata("GSE123456")
        # 返回项目的标题和描述
    """
    try:
        data = await _seqout_request(f"/project/{accession}/metadata")
        return json.dumps({"success": True, "summary": f"项目 {accession} 元数据", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取元数据失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_project_citation(accession: str) -> str:
    """获取项目的 BibTeX 引用文献。
    
    :param accession: 项目唯一编号（如:'GSE151530','PRJNA678901'）
    :return: JSON 格式的 BibTeX 引用字符串
    
    示例:
        await seqout_get_project_citation("GSE151530")
        # 返回该项目的 BibTeX 引用格式文献信息
    """
    try:
        data = await _seqout_request(f"/project/{accession}/cite")
        return json.dumps({"success": True, "summary": f"项目 {accession} 引用文献", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取引用失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_project_enriched(accession: str) -> str:
    """获取 AI 增强的样本元数据（包含本体论注释）。
    
    :param accession: 项目唯一编号（如:'GSE151530','PRJNA678901'）
    :return: JSON 格式的增强元数据，包含标准化本体论术语
    
    示例:
        await seqout_get_project_enriched("GSE123456")
        # 返回带有本体论注释的增强样本元数据
    """
    try:
        data = await _seqout_request(f"/project/{accession}/enriched")
        return json.dumps({"success": True, "summary": f"项目 {accession} 增强元数据", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取增强元数据失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Experiment & Sample Tools ====================

@mcp.tool()
async def seqout_get_experiments(study_accession: str) -> str:
    """列出研究中的所有实验。
    
    :param study_accession: 研究项目编号（如:'GSE123456','PRJNA678901'）
    :return: JSON 格式的实验列表
    
    示例:
        await seqout_get_experiments("GSE123456")
        # 返回该研究下的所有实验列表
    """
    try:
        data = await _seqout_request(f"/project/{study_accession}/experiments")
        return json.dumps({"success": True, "summary": f"研究 {study_accession} 的实验列表", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取实验列表失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_runs(study_accession: str) -> str:
    """列出 FASTQ 下载链接。
    
    :param study_accession: 研究项目编号（如:'GSE123456','PRJNA678901'）
    :return: JSON 格式的测序运行列表，包含 SRR 编号和下载链接
    
    示例:
        await seqout_get_runs("GSE123456")
        # 返回该研究的所有 FASTQ 下载链接
    """
    try:
        data = await _seqout_request(f"/project/{study_accession}/runs")
        return json.dumps({"success": True, "summary": f"研究 {study_accession} 的测序运行列表", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取运行列表失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_run_download(run_accession: str) -> str:
    """获取单个运行的下载链接。
    
    :param run_accession: 运行编号（如:'SRR1234567','ERR1234567'）
    :return: JSON 格式的下载链接信息
    
    示例:
        await seqout_get_run_download("SRR1234567")
        # 返回 SRR1234567 的 FASTQ 下载链接
    """
    try:
        data = await _seqout_request(f"/run/{run_accession}")
        return json.dumps({"success": True, "summary": f"运行 {run_accession} 下载链接", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取下载链接失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_sample_metadata(accession: str) -> str:
    """获取样本元数据。
    
    :param accession: 样本编号（如:'GSM1234567','SRR1234567'）
    :return: JSON 格式的样本元数据
    
    示例:
        await seqout_get_sample_metadata("GSM1234567")
        # 返回 GSM1234567 的元数据信息
    """
    try:
        data = await _seqout_request(f"/sample/{accession}")
        return json.dumps({"success": True, "summary": f"样本 {accession} 元数据", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取样本元数据失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_sample_detail(accession: str) -> str:
    """获取完整的样本详细信息。
    
    :param accession: 样本编号（如:'GSM1234567','SRR1234567'）
    :return: JSON 格式的完整样本信息
    
    示例:
        await seqout_get_sample_detail("GSM1234567")
        # 返回样本的完整详细信息
    """
    try:
        data = await _seqout_request(f"/sample-detail/{accession}")
        return json.dumps({"success": True, "summary": f"样本 {accession} 详细信息", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取样本详细信息失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_sample_manifest(accession: str, max_samples: int = 30) -> str:
    """获取数据集的样本清单（Sample Manifest），包含样本组织来源、实验处理组 (Treatment) 与对照组 (Control) 标记。
    
    :param accession: GEO Series 编号（如:'GSE123456'）
    :param max_samples: 返回的最大样本数量预览，默认 30
    :return: JSON 格式的样本列表，包含 sample_accession、title、characteristics 等字段
    
    示例:
        await seqout_get_sample_manifest("GSE123456", max_samples=30)
        # 返回该数据集的前 30 个样本信息
    """
    try:
        data = await _seqout_request(f"/geo/series/{accession}/samples")
        samples = _parse_samples_response(data, max_samples)
        
        if not samples:
            return json.dumps({"success": False, "summary": f"数据集 {accession} 未找到结构化样本信息。"}, ensure_ascii=False, indent=2)
        
        return json.dumps({"success": True, "summary": f"共 {len(samples)} 个样本（已限制显示{max_samples}个）", "data": samples}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取样本清单失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Resolution Tools ====================

@mcp.tool()
async def seqout_resolve_accession(accession: str) -> str:
    """当科研人员仅提供单个样本编号 (GSM...) 或测序 Run (SRR...) 时，反查其归属的项目编号 (GSE/PRJNA)。
    
    :param accession: 样本或 Run 编号（如:'GSM456789','SRR1234567'）
    :return: JSON 格式的归属项目信息
    
    示例:
        await seqout_resolve_accession("GSM456789")
        # 返回该样本所属的 GSE 项目编号
    """
    try:
        data = await _seqout_request(f"/accession/{accession}/project")
        return json.dumps({"success": True, "summary": f"解析 {accession} 成功", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"解析编号 {accession} 失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_resolve_prj(prj_accession: str) -> str:
    """将 BioProject 解析到研究级别。
    
    :param prj_accession: BioProject 编号（如:'PRJNA123456','PRJEB123456'）
    :return: JSON 格式的解析结果，包含 GSE/GSM/SRR 等编号映射
    
    示例:
        await seqout_resolve_prj("PRJNA123456")
        # 返回该 BioProject 下的所有实验和样本编号
    """
    try:
        data = await _seqout_request(f"/prj/{prj_accession}")
        return json.dumps({"success": True, "summary": f"BioProject {prj_accession} 解析结果", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"解析失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Ontology & Statistics Tools ====================

@mcp.tool()
async def seqout_get_ontology_term(term: str) -> str:
    """查询本体论图中某个术语的所有相关信息。
    
    :param term: 本体论术语（如:'T cell','liver','RNA-seq'）
    :return: JSON 格式的术语信息，包含定义、同义词、父类等
    
    示例:
        await seqout_get_ontology_term("T cell")
        # 返回 T cell 的本体论信息
    """
    try:
        data = await _seqout_request(f"/ontology/term?term={term}")
        return json.dumps({"success": True, "summary": f"本体论术语 '{term}' 信息", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取本体论信息失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_organisms() -> str:
    """列出所有支持的生物物种。
    
    :return: JSON 格式的物种列表，包含学名、常用名、taxon_id
    
    示例:
        await seqout_get_organisms()
        # 返回所有支持的物种列表
    """
    try:
        data = await _seqout_request("/organisms")
        return json.dumps({"success": True, "summary": "所有支持的物种列表", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取物种列表失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_common_name(organism: str) -> str:
    """获取物种的常用名称。
    
    :param organism: 物种标识符（如:'Homo sapiens','Mus musculus',9606）
    :return: JSON 格式的常用名称信息
    
    示例:
        await seqout_get_common_name("Homo sapiens")
        # 返回人类的常用名称
    """
    try:
        data = await _seqout_request(f"/common-name?organism={organism}")
        return json.dumps({"success": True, "summary": f"物种 '{organism}' 的常用名称", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取常用名称失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Beacon Tools ====================

@mcp.tool()
async def seqout_beacon_info() -> str:
    """获取 Beacon 身份和元数据。
    
    :return: JSON 格式的 Beacon 元数据，包含版本、实例信息、访问策略
    
    示例:
        await seqout_beacon_info()
        # 返回 Beacon 服务的元数据信息
    """
    try:
        data = await _seqout_request("/beacon/info")
        return json.dumps({"success": True, "summary": "Beacon 元数据", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取 Beacon 信息失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_beacon_runs(run_accession: str | None = None, skip: int = 0, limit: int = 10) -> str:
    """浏览或获取测序运行（使用自定义 seqoutRun schema）。
    
    :param run_accession: 单个运行编号（可选，如:'SRR1234567'）
    :param skip: 分页索引，默认 0
    :param limit: 页面大小，最大 100，默认 10
    :return: JSON 格式的测序运行列表
    
    示例:
        await seqout_beacon_runs(limit=5)
        # 返回前 5 个测序运行
        await seqout_beacon_runs(run_accession="SRR1234567")
        # 返回特定运行的信息
    """
    try:
        params = {}
        if run_accession:
            params["id"] = run_accession
        if skip > 0:
            params["skip"] = skip
        if limit > 10:
            limit = 10
        if limit > 0:
            params["limit"] = limit
        
        data = await _seqout_request("/beacon/runs", params=params if params else None)
        return json.dumps({"success": True, "summary": f"测序运行列表（skip={skip}, limit={limit})", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取运行列表失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Statistics Tools ====================

@mcp.tool()
async def seqout_get_stats_growth() -> str:
    """获取数据库随时间的增长情况。
    
    :return: JSON 格式的增长统计，包含时间序列数据
    
    示例:
        await seqout_get_stats_growth()
        # 返回数据库增长趋势
    """
    try:
        data = await _seqout_request("/stats/growth")
        return json.dumps({"success": True, "summary": "数据库增长统计", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取统计失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_organism_totals() -> str:
    """获取每个物种的实验总数。
    
    :return: JSON 格式的物种实验计数统计
    
    示例:
        await seqout_get_organism_totals()
        # 返回各物种的实验数量排名
    """
    try:
        data = await _seqout_request("/stats/organism-totals")
        return json.dumps({"success": True, "summary": "物种实验总数统计", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取统计失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_platform_totals(platform: str | None = None) -> str:
    """获取每个平台的实验总数，或特定平台的过滤选项。
    
    :param platform: 平台代码（如:'ILLUMINA','ION'，可选）
    :return: JSON 格式的平台统计或过滤选项
    
    示例:
        await seqout_get_platform_totals()
        # 返回所有测序平台的实验数量统计
        await seqout_get_platform_totals("ILLUMINA")
        # 返回 Illumina 平台的过滤选项
    """
    try:
        endpoint = "/stats/platform-filters" if platform else "/stats/platform-totals"
        params = {"platform": platform} if platform else None
        data = await _seqout_request(endpoint, params=params)
        summary = f"平台 '{platform}' 过滤选项" if platform else "平台实验总数统计"
        return json.dumps({"success": True, "summary": summary, "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取统计失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


# ==================== Download Tools ====================

@mcp.tool()
async def seqout_get_download_links(study_accession: str) -> str:
    """以 TSV 格式获取运行下载链接。
    
    :param study_accession: 研究项目编号（如:'GSE123456','PRJNA678901'）
    :return: JSON 格式的 TSV 下载链接数据
    
    示例:
        await seqout_get_download_links("GSE123456")
        # 返回该研究的 FASTQ 下载链接 TSV 数据
    """
    try:
        data = await _seqout_request(f"/project/{study_accession}/runs/download")
        return json.dumps({"success": True, "summary": f"研究 {study_accession} 的下载链接 TSV", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取下载链接失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


@mcp.tool()
async def seqout_get_metadata_csv(study_accession: str) -> str:
    """下载合并的元数据 CSV。
    
    :param study_accession: 研究项目编号（如:'GSE123456','PRJNA678901'）
    :return: JSON 格式的 CSV 元数据内容
    
    示例:
        await seqout_get_metadata_csv("GSE123456")
        # 返回该研究的合并元数据 CSV 文件内容
    """
    try:
        data = await _seqout_request(f"/project/{study_accession}/metadata/download")
        return json.dumps({"success": True, "summary": f"研究 {study_accession} 的元数据 CSV", "data": data}, ensure_ascii=False, indent=2)
    except SeqoutAPIError as e:
        return json.dumps({"success": False, "summary": f"获取元数据 CSV 失败：{str(e)}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "summary": f"未知错误：{str(e)}"}, ensure_ascii=False, indent=2)


def register(mcp: FastMCP, _) -> None:
    """注册 Seqout 工具到 FastMCP 实例"""
    tools = [
        seqout_search,
        seqout_search_geo,
        seqout_search_sra,
        seqout_search_structured,
        seqout_get_project_detail,
        seqout_get_project_metadata,
        seqout_get_project_citation,
        seqout_get_project_enriched,
        seqout_get_experiments,
        seqout_get_runs,
        seqout_get_run_download,
        seqout_get_sample_metadata,
        seqout_get_sample_detail,
        seqout_get_sample_manifest,
        seqout_resolve_accession,
        seqout_resolve_prj,
        seqout_get_ontology_term,
        seqout_get_organisms,
        seqout_get_common_name,
        seqout_beacon_info,
        seqout_beacon_runs,
        seqout_get_stats_growth,
        seqout_get_organism_totals,
        seqout_get_platform_totals,
        seqout_get_download_links,
        seqout_get_metadata_csv,
    ]
    
    for tool in tools:
        mcp.tool()(tool)
    
    logger.info(f"[Seqout] 工具组注册完成 ({len(tools)} 个工具)")
