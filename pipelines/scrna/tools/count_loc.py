#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import prettytable

# 配置
TARGET_EXTENSIONS = {'.r', '.R', '.py', '.sh', '.yaml', '.conf'}
IGNORE_DIRS = {'.git', 'build_analysis_env', 'celldex', '.gemini'} # 忽略的目录
PROJECT_ROOT = "."

def is_comment(line, ext):
    """简单的注释判断逻辑"""
    line = line.strip()
    if not line: return False
    if ext in ['.r', '.R', '.py', '.sh', '.yaml', '.conf']:
        return line.startswith('#')
    return False

def count_lines(filepath):
    """统计单个文件的行数"""
    total = 0
    code = 0
    comment = 0
    blank = 0
    ext = os.path.splitext(filepath)[1]
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                total += 1
                stripped = line.strip()
                if not stripped:
                    blank += 1
                elif is_comment(line, ext):
                    comment += 1
                else:
                    code += 1
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

    return {'total': total, 'code': code, 'comment': comment, 'blank': blank}

def scan_directory(root_dir):
    file_stats = []
    
    for root, dirs, files in os.walk(root_dir):
        # 过滤忽略的目录
        dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS]
        
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in TARGET_EXTENSIONS:
                filepath = os.path.join(root, file)
                stats = count_lines(filepath)
                if stats:
                    stats['file'] = filepath
                    stats['dir'] = root
                    file_stats.append(stats)
    return file_stats

def print_summary(stats):
    if not stats:
        print("No script files found.")
        return

    # 1. 总体统计
    total_files = len(stats)
    total_lines = sum(s['total'] for s in stats)
    total_code = sum(s['code'] for s in stats)
    
    print("\n" + "="*60)
    print(f"  📊 PROJECT CODE STATISTICS")
    print("="*60)
    print(f"  Total Files       : {total_files}")
    print(f"  Total Lines       : {total_lines}")
    print(f"  Effective Code    : {total_code} ({total_code/total_lines*100:.1f}%)")
    print("="*60 + "\n")

    # 2. 按目录汇总
    dir_summary = {}
    for s in stats:
        d = s['dir']
        if d not in dir_summary:
            dir_summary[d] = {'files': 0, 'total': 0, 'code': 0}
        dir_summary[d]['files'] += 1
        dir_summary[d]['total'] += s['total']
        dir_summary[d]['code'] += s['code']

    # 排序：按代码行数倒序
    sorted_dirs = sorted(dir_summary.items(), key=lambda x: x[1]['total'], reverse=True)

    print("📁 Breakdown by Directory:")
    pt_dir = prettytable.PrettyTable(["Directory", "Files", "Total LOC", "Code LOC"])
    pt_dir.align["Directory"] = "l"
    pt_dir.align["Total LOC"] = "r"
    pt_dir.align["Code LOC"] = "r"
    
    for d, info in sorted_dirs:
        pt_dir.add_row([d, info['files'], info['total'], info['code']])
    print(pt_dir)
    print("\n")

    # 3. Top 15 大文件（重构重点）
    print("📄 Top 15 Largest Files (Refactoring Targets):")
    sorted_files = sorted(stats, key=lambda x: x['total'], reverse=True)[:15]
    
    pt_file = prettytable.PrettyTable(["File Path", "Total LOC", "Code LOC", "Comments"])
    pt_file.align["File Path"] = "l"
    pt_file.align["Total LOC"] = "r"
    
    for s in sorted_files:
        pt_file.add_row([s['file'], s['total'], s['code'], s['comment']])
    print(pt_file)
    print("\n")

if __name__ == "__main__":
    try:
        # Check dependencies
        import prettytable
    except ImportError:
        print("Installing dependency 'prettytable'...")
        os.system("pip install prettytable")
        print("-" * 30)

    print(f"Scanning project root: {PROJECT_ROOT} ...")
    data = scan_directory(PROJECT_ROOT)
    print_summary(data)
