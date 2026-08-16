#!/usr/bin/env python3
# author : zhang jian
# date : 2026-08-03
# skill : scrna-deg-analysis (OmicHub OSDP v1.0)
# description : 合并 DEG 结果根目录下全部 *-DEG-infor.csv 为一张汇总表。
#   重写自 tools/DEG/Extert_DEG.PY: 移除 /titan3/ 硬编码路径, 改为 argparse CLI。
# 退出码: 0 成功; 1 未找到任何 -DEG-infor.csv; 2 读取/合并失败。

import argparse
import os
import sys

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(
        description="递归合并 DEG 输出目录下的 *-DEG-infor.csv (各细胞类型上下调基因计数) 为一张 csv")
    parser.add_argument("--input", required=True,
                        help="DEG 结果根目录 (deg_analysis.R 的 --output 目录)")
    parser.add_argument("--output", required=True,
                        help="合并结果 csv 输出路径")
    args = parser.parse_args()

    if not os.path.isdir(args.input):
        print(f"[ERROR] 输入目录不存在: {args.input}", file=sys.stderr)
        return 1

    csv_files = []
    for root, _dirs, files in os.walk(args.input):
        for file in sorted(files):
            if file.endswith("-DEG-infor.csv"):
                csv_files.append(os.path.join(root, file))

    if not csv_files:
        print(f"[ERROR] 在 {args.input} 下未找到任何 '-DEG-infor.csv' 文件", file=sys.stderr)
        return 1

    print(f"[INFO] 找到 {len(csv_files)} 个 -DEG-infor.csv 文件")
    merged_df = pd.DataFrame()
    try:
        for file in csv_files:
            df = pd.read_csv(file)
            # 用相对路径标识来源 (含细胞类型目录与比较名)
            source = os.path.splitext(os.path.basename(file))[0].replace("-DEG-infor", "")
            df["filename"] = source
            merged_df = pd.concat([merged_df, df], ignore_index=True)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 读取/合并失败: {e}", file=sys.stderr)
        return 2

    merged_df.set_index("filename", inplace=True)
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    merged_df.to_csv(args.output)
    print(f"[INFO] 已合并 {len(csv_files)} 个文件, 共 {len(merged_df)} 行 -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
