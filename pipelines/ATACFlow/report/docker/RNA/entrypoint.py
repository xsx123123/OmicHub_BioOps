#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import shutil
import subprocess
import signal
import argparse
import time
from pathlib import Path
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

# --- 初始化 Rich Console ---
console = Console()

# --- 1. 参数解析 (Argparse) ---
def parse_args():
    parser = argparse.ArgumentParser(description="RNAFlow 报告生成器容器入口")
    
    parser.add_argument(
        "-c", "--config", 
        default="/app/project_summary.json",
        help="配置文件路径 (默认: /app/project_summary.json)"
    )
    parser.add_argument(
        "-o", "--output", 
        default="/workspace",
        help="报告输出目录 (默认: /workspace)"
    )
    parser.add_argument(
        "--data-prefix",
        default="/data",
        help="Docker 容器内的数据挂载前缀 (默认: /data)"
    )
    
    return parser.parse_args()

# --- 2. 日志配置 (Loguru) ---
def setup_logging(output_dir):
    # 移除默认 handler
    logger.remove()
    
    # 添加控制台输出 (带颜色，格式简洁)
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    # 添加文件输出 (详细，包含所有 debug 信息)
    log_file = os.path.join(output_dir, "pipeline.log")
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB"  # 日志轮转
    )
    return log_file

# --- 3. 信号处理 ---
def signal_handler(sig, frame):
    console.print()
    logger.warning("⚠️  接收到中断信号 (Ctrl+C)，正在安全退出...")
    sys.exit(0)

# --- 4. 核心功能函数 ---

def print_banner():
    """打印漂亮的启动横幅"""
    title = Text("RNAFlow Report Generator", justify="center", style="bold cyan")
    subtitle = Text("v1.0.0 | Powered by Quarto & Docker", justify="center", style="dim white")
    console.print(Panel(
        Text.assemble(title, "\n", subtitle), 
        border_style="cyan", 
        expand=False,
        padding=(1, 5)
    ))

def load_config(json_path):
    logger.info(f"正在读取配置文件: [cyan]{json_path}[/]")
    path = Path(json_path)
    if not path.exists():
        logger.error(f"配置文件不存在: {json_path}")
        sys.exit(1)
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.critical(f"解析 JSON 失败: {e}")
        sys.exit(1)

def check_input_files(config):
    """使用 Rich Table 展示文件检查结果"""
    logger.info("开始检查输入文件完整性...")
    
    table = Table(title="输入文件检查清单", show_header=True, header_style="bold magenta")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Path", style="white")
    table.add_column("Status", justify="center")

    files_to_check = config.get("input_files", {})
    all_passed = True
    
    # 使用 Progress Spinner 模拟检查过程 (增加仪式感)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task(description="Scanning files...", total=len(files_to_check))
        
        for key, path_str in files_to_check.items():
            # 简单处理相对路径问题
            # 假设 config 里的路径是相对于 /data 或绝对路径
            path = Path(path_str)
            # 如果是相对路径 ../data，尝试修正为 absolute
            if path_str.startswith(".."):
                 # 这是一个简单的 heuristic，根据你的实际挂载调整
                 # 如果你保证 json 里写的是 /data 开头，这里就不需要 hack
                 pass

            exists = False
            # 尝试直接检查
            if path.exists():
                exists = True
            # 尝试作为相对路径检查 (相对于 cwd)
            elif Path(os.getcwd()).joinpath(path).exists():
                exists = True
            
            if exists:
                status = "[bold green]✔ Found[/]"
            else:
                status = "[bold red]✖ Missing[/]"
                all_passed = False
                # 记录详细错误日志
                logger.warning(f"缺失文件: {key} -> {path_str}")

            table.add_row(key, str(path_str), status)
            progress.advance(task)
            time.sleep(0.05) # 稍微停顿一下，让用户看到扫描过程

    console.print(table)

    if not all_passed:
        logger.error("检测到缺失文件，请检查挂载路径 (-v) 或 JSON 配置。")
        # 这里你可以选择 sys.exit(1) 强制退出，或者只是警告
        # sys.exit(1) 

def check_quarto_env():
    if shutil.which("quarto") is None:
        logger.critical("未找到 Quarto 可执行文件！")
        sys.exit(1)
    
    # 获取版本
    res = subprocess.run(["quarto", "--version"], capture_output=True, text=True)
    version = res.stdout.strip()
    console.print(f"🛠️  Quarto Environment: [bold green]{version}[/]")

def render_report(config_path, output_dir):
    logger.info("启动 Quarto 渲染引擎...")
    
    template_dir = "/app/templates"
    if not os.path.exists(template_dir):
        logger.error(f"模板目录缺失: {template_dir}")
        sys.exit(1)

    os.chdir(template_dir)
    
    env = os.environ.copy()
    env["REPORT_CONFIG"] = config_path 
    
    abs_output_dir = os.path.abspath(output_dir)
    
    cmd = ["quarto", "render", ".", "--output-dir", abs_output_dir, "--to", "html"]

    try:
        process = subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        
        # 实时处理输出，给 Quarto 的日志加点颜色前缀
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if line:
                if "ERROR" in line or "Error" in line:
                    logger.error(f"[Quarto] {line}")
                else:
                    # 使用 dim 样式让普通日志不那么抢眼
                    console.print(f"[dim blue][Quarto][/] {line}")

        process.stdout.close()
        return_code = process.wait()
        
        if return_code != 0:
            logger.error("❌ Quarto 渲染失败！")
            sys.exit(return_code)

        final_index = os.path.join(abs_output_dir, "index.html")
        
        # 使用 Panel 展示成功信息
        success_msg = Text.assemble(
            ("🎉 报告生成成功！\n", "bold green"),
            (f"📂 目录: {abs_output_dir}\n", "white"),
            (f"👉 入口: {final_index}", "underline blue")
        )
        console.print(Panel(success_msg, border_style="green"))

    except Exception as e:
        logger.critical(f"渲染未知错误: {e}")
        sys.exit(1)

def backup_config(config_path, output_dir):
    try:
        dst = os.path.join(output_dir, "run_config_backup.json")
        shutil.copy(config_path, dst)
        logger.debug(f"配置文件已备份至: {dst}")
    except Exception as e:
        logger.warning(f"备份失败: {e}")

# --- 5. 主函数 ---
def main():
    signal.signal(signal.SIGINT, signal_handler)
    
    # 1. 解析参数
    args = parse_args()
    
    # 2. 准备目录
    if not os.path.exists(args.output):
        os.makedirs(args.output, exist_ok=True)
        
    # 3. 初始化日志 (Argparse 解析完之后才知道 output 目录在哪)
    log_file = setup_logging(args.output)
    
    print_banner()
    logger.info(f"日志文件已创建: {log_file}")

    # 4. 加载配置
    config = load_config(args.config)

    # 5. 检查
    check_input_files(config)
    check_quarto_env()

    # 6. 执行
    render_report(args.config, args.output)
    
    # 7. 备份
    backup_config(args.config, args.output)

if __name__ == "__main__":
    main()