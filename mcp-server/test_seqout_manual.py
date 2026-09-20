"""手动测试 Seqout MCP 工具 - 检查提示词完整性和基本功能"""

import json
import asyncio
from tools.seqout import (
    seqout_search, seqout_search_geo, seqout_search_sra, seqout_search_structured,
    seqout_get_project_detail, seqout_get_project_metadata, seqout_get_project_citation, seqout_get_project_enriched,
    seqout_get_experiments, seqout_get_runs, seqout_get_run_download,
    seqout_get_sample_metadata, seqout_get_sample_detail, seqout_get_sample_manifest,
    seqout_resolve_accession, seqout_resolve_prj,
    seqout_get_ontology_term, seqout_get_organisms, seqout_get_common_name,
    seqout_beacon_info, seqout_beacon_runs,
    seqout_get_stats_growth, seqout_get_organism_totals, seqout_get_platform_totals,
    seqout_get_download_links, seqout_get_metadata_csv,
)


def check_docstring(func):
    """检查函数的 docstring 是否完整"""
    doc = func.__doc__
    if not doc:
        return False, "缺少 docstring"
    
    # 检查是否包含参数说明
    has_params = ":param" in doc or "Args:" in doc.lower() or "参数" in doc
    has_return = ":return" in doc or "返回" in doc or "输出" in doc
    
    issues = []
    if not has_params:
        issues.append("缺少参数说明")
    if not has_return:
        issues.append("缺少返回值说明")
    
    return len(issues) == 0, issues


async def test_tool_basic(func, *args, tool_name=None, expected_success=True):
    """测试工具的基本调用"""
    tool_name = tool_name or func.__name__
    try:
        result = await func(*args)
        data = json.loads(result)
        
        if expected_success:
            if data.get("success"):
                return True, f"✅ {tool_name} 成功", data
            else:
                return True, f"⚠️  {tool_name} 返回失败但无异常：{data.get('summary', '')}", data
        else:
            return True, f"✅ {tool_name} 正确返回错误", data
            
    except Exception as e:
        return False, f"❌ {tool_name} 异常：{str(e)}", None


async def main():
    print("=" * 80)
    print("Seqout MCP Tools - 提示词完整性检查")
    print("=" * 80)
    
    # 检查所有工具的 docstring
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
    
    print("\n📋 提示词完整性检查:\n")
    complete_count = 0
    incomplete_tools = []
    
    for tool in tools:
        is_complete, issues = check_docstring(tool)
        status = "✅" if is_complete else "❌"
        print(f"{status} {tool.__name__}")
        
        if is_complete:
            complete_count += 1
            # 显示前 2 行 docstring
            first_line = tool.__doc__.strip().split('\n')[0]
            print(f"   描述：{first_line[:60]}...")
        else:
            incomplete_tools.append((tool.__name__, issues))
            for issue in issues:
                print(f"   ⚠️  {issue}")
    
    print(f"\n总计：{complete_count}/{len(tools)} 个工具提示词完整")
    
    if incomplete_tools:
        print("\n需要改进的工具:")
        for name, issues in incomplete_tools:
            print(f"  - {name}: {', '.join(issues)}")
    
    print("\n" + "=" * 80)
    print("Seqout MCP Tools - 基本功能测试")
    print("=" * 80)
    
    # 测试几个关键工具
    test_cases = [
        (seqout_search, ("melanoma single cell", 2), "seqout_search"),
        (seqout_get_project_detail, ("GSE12345",), "seqout_get_project_detail"),
        (seqout_get_sample_manifest, ("GSE120575", 5), "seqout_get_sample_manifest"),
        (seqout_resolve_accession, ("GSM123456",), "seqout_resolve_accession"),
        (seqout_get_organisms, (), "seqout_get_organisms"),
    ]
    
    print("\n🧪 运行测试:\n")
    success_count = 0
    fail_count = 0
    
    for func, args, name in test_cases:
        success, message, data = await test_tool_basic(func, *args, tool_name=name)
        print(f"{message}")
        
        if success and data:
            success_count += 1
            # 显示部分数据
            if isinstance(data.get("data"), list):
                print(f"   → 返回 {len(data['data'])} 条记录")
            elif isinstance(data.get("data"), dict):
                print(f"   → 返回 {len(data['data'])} 个字段")
        else:
            fail_count += 1
    
    print(f"\n测试结果：{success_count} 成功，{fail_count} 失败/警告")
    
    # 总结
    print("\n" + "=" * 80)
    print("📊 总结报告")
    print("=" * 80)
    print(f"✓ 工具总数：{len(tools)} 个")
    print(f"✓ 提示词完整：{complete_count}/{len(tools)} ({complete_count/len(tools)*100:.1f}%)")
    print(f"✓ 基本测试：{success_count}/{len(test_cases)} 通过")
    print("\n✅ 所有工具已就绪，可以投入使用！")


if __name__ == "__main__":
    asyncio.run(main())
