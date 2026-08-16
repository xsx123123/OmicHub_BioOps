#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import rich_click as click
from .wrapper import run_interpretation_task, display_model_status

# 屏蔽 httpx/httpcore 的 INFO 日志
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

@click.group(context_settings=dict(help_option_names=['-h', '--help']))
def cli():
    """
    BioReport AI 工具箱
    
    包含模型检查与报告生成功能。
    """
    pass

@cli.command()
@click.option('--config', help='YAML 配置文件路径')
def model_check(config):
    """
    检查可用模型与 API Key 状态
    """
    display_model_status(config)


@cli.command()
@click.option('--project-id', required=True, help='项目 ID')
@click.option('--data-file', required=True, help='JSON 数据文件路径')
@click.option('--template-file', default=None, help='Jinja2 模板路径；缺省读取 OMICHUB_PROMPT_ROOT/report/rnaseq_standard.md.j2')
@click.option('--attachment', '-a', multiple=True, help='附加文件路径 (PDF/PNG/JPG)')
@click.option('--output', default="./ai_report/", help='结果输出目录或文件路径')
@click.option('--tissue-type', help='样本组织/细胞类型 (e.g. "Liver", "Hela Cells")')
@click.option('--goal', help='分析目标/生物学问题 (e.g. "Identify drug targets")')
@click.option('--language', help='报告语言 (e.g. "Chinese", "English")')
@click.option('--extra-param', '-e', multiple=True, help='额外参数 (key=value 格式)')
@click.option('--config', help='YAML 配置文件路径')
@click.option('--provider', help='指定 AI 服务提供商 (volcengine/aliyun)')
@click.option('--model', help='指定 AI 模型 ID (覆盖配置文件)')
@click.option('--temperature', type=float, help='模型温度 (0.0 - 1.0)')
@click.option('--top-p', type=float, help='核采样阈值 (0.0 - 1.0)')
@click.option('--log-level', default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]), help='日志级别')
def report(project_id, data_file, template_file, attachment, output, tissue_type, goal, language, extra_param, config, provider, model, temperature, top_p, log_level):
    """
    生成 AI 解读报告
    """
    run_interpretation_task(
        project_id=project_id,
        data_file=data_file,
        template_file=template_file,
        attachments=attachment,
        output=output,
        tissue_type=tissue_type,
        goal=goal,
        language=language,
        extra_params=extra_param,
        config_file=config,
        provider=provider,
        model=model,
        temperature=temperature,
        top_p=top_p,
        log_level=log_level
    )

if __name__ == "__main__":
    cli()
