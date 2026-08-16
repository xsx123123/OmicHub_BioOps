import argparse
from pathlib import Path
from bioreport import ReportGenerator, RNALoader, save_json

def main():
    parser = argparse.ArgumentParser(description="BioReport Generator")
    parser.add_argument("--results", help="Path to analysis results directory", default=".")
    parser.add_argument("--format", help="Output format (html, docx, pdf)", default="html")
    args = parser.parse_args()

    # 1. 模拟：确保有一个结果目录存在 (实际使用时是你的 upstream output 目录)
    # 这里我们只是为了让 RNALoader 不报错
    Path(args.results).mkdir(exist_ok=True)

    print(f"--- Step 1: Loading Data from {args.results} ---")
    # 实例化 Loader，这里我们使用 RNALoader
    # 以后你可以根据 pipeline 类型选择不同的 Loader (比如 ATACLoader)
    loader = RNALoader(result_dir=args.results)
    
    # 提取所有数据 (Extract & Transform)
    report_data = loader.extract_context()
    
    # 保存中间 JSON 供调试/备份
    save_json(report_data, "output/report_context.json")
    print("Data loaded and saved to output/report_context.json")

    print("--- Step 2: Rendering Template ---")
    generator = ReportGenerator(template_dir="templates")
    
    # 渲染 .qmd
    qmd_path = generator.render(
        template_name="rna_seq.qmd.j2",
        data=report_data,
        output_path="output/final_report.qmd"
    )
    print(f"Template rendered: {qmd_path}")

    print(f"--- Step 3: Building {args.format.upper()} Report ---")
    try:
        final_report = generator.build(qmd_path, output_format=args.format)
        print(f"Success! Report generated: {final_report}")
    except Exception as e:
        print(f"Error building report: {e}")

if __name__ == "__main__":
    main()