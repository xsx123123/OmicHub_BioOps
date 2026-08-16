import os
import sys
import json
import re
import yaml
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from loguru import logger
from rich.logging import RichHandler
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from .engine import AIInterpreter
from .prompt_assets import prompt_root

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    path = config_path if config_path else DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        logger.warning(f"配置文件未找到: {path}，使用默认设置")
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"无法读取配置文件 {path}: {e}")
        return {}

def configure_logging(level: str, log_file: str = None, json_log_file: str = None, console: bool = True):
    """配置日志系统 (Rich + Loguru)"""
    logger.remove()
    if console:
        logger.add(
            RichHandler(rich_tracebacks=True, markup=True, show_path=False), 
            format="{message}", 
            level=level.upper()
        )
    if log_file:
        logger.add(log_file, serialize=False, level="DEBUG", rotation="10 MB", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}")
        logger.info(f"日志将记录到: {log_file}")

    if json_log_file:
        logger.add(json_log_file, serialize=True, level="DEBUG", rotation="10 MB")
        logger.info(f"JSON日志将记录到: {json_log_file}")

def generate_output_filename(project_id: str, tissue: str, language: str, output_dir: str) -> str:
    """生成规范的输出文件名"""
    safe_project = re.sub(r'[^a-zA-Z0-9_-]', '', project_id)
    if tissue:
        clean_tissue = re.sub(r'(?i)tissue', '', tissue).strip()
        safe_tissue = re.sub(r'[^a-zA-Z0-9_-]', '', clean_tissue.replace(" ", "_"))
        if not safe_tissue: safe_tissue = "Unknown"
    else:
        safe_tissue = "UnknownTissue"
    safe_lang = language if language else "Chinese"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_project}_{safe_tissue}_{timestamp}_{safe_lang}.md"
    return os.path.join(output_dir, filename)

def display_model_status(config_path: Optional[str] = None):
    """检查可用模型与 API Key 状态并打印 Rich UI"""
    console = Console()
    cfg = load_config(config_path)
    ai_config = cfg.get("ai", {})
    current_provider = ai_config.get("provider", "Unknown")
    
    console.print("[bold underline]AI Configuration Status Check[/bold underline]", justify="center")
    console.print()

    def check_provider(name, env_var, config_key, is_active):
        api_key = os.environ.get(env_var)
        status_color = "green" if api_key else "red"
        status_text = "API Key Configured" if api_key else f"Missing {env_var}"
        status_icon = "✅" if api_key else "❌"
        models = ai_config.get(config_key, {}).get("model", [])
        if isinstance(models, str): models = [models]
        model_list = "\n".join([f"  • {m}" for m in models if m])
        title_style = "bold cyan" if is_active else "dim white"
        border_style = "cyan" if is_active else "dim"
        active_badge = " [bold yellow](ACTIVE)[/bold yellow]" if is_active else ""
        content = (
            f"[bold]Status:[/bold] [{status_color}]{status_icon} {status_text}[/{status_color}]\n\n"
            f"[bold]Available Models:[/bold]\n{model_list}"
        )
        return Panel(content, title=f"[{title_style}]Provider: {name}{active_badge}[/{title_style}]", border_style=border_style, expand=False, padding=(1, 2))

    panels = [
        check_provider("Volcengine (火山引擎)", "ARK_API_KEY", "volcengine", current_provider == "volcengine"),
        check_provider("Aliyun (阿里云)", "DASHSCOPE_API_KEY", "aliyun", current_provider == "aliyun")
    ]
    console.print(Columns(panels, equal=True, expand=True))
    console.print("\n[dim]Tip: Update 'bioreport/config.yaml' to change defaults or add models.[/dim]")

def check_env_vars(provider: str) -> bool:
    """检查指定 Provider 的环境变量是否已配置"""
    env_vars = {"volcengine": "ARK_API_KEY", "aliyun": "DASHSCOPE_API_KEY"}
    var_name = env_vars.get(provider)
    if var_name and not os.environ.get(var_name):
        logger.error(f"Missing Environment Variable: {var_name}")
        logger.error(f"Please set {var_name} to use {provider} services.")
        return False
    return True

def run_interpretation_task(
    project_id: str,
    data_file: str,
    template_file: str,
    attachments: List[str],
    output: str,
    tissue_type: Optional[str] = None,
    goal: Optional[str] = None,
    language: str = None,
    extra_params: List[str] = [],
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    config_file: Optional[str] = None,
    log_level: str = "INFO"
):
    """执行解读任务的高级封装函数"""
    trace_id = str(uuid.uuid4())[:8]
    if not logger._core.handlers:
        configure_logging(log_level)

    config = load_config(config_file)
    ai_config = config.get("ai", {})
    final_provider = provider if provider else ai_config.get("provider", "volcengine")
    
    if not check_env_vars(final_provider):
        logger.error(f"[{trace_id}] Environment check failed for provider: {final_provider}. Aborting.")
        sys.exit(1)
    
    provider_config = ai_config.get(final_provider, {})
    final_model = model
    if not final_model:
        config_models = provider_config.get("model", [])
        if isinstance(config_models, list) and len(config_models) > 0:
            final_model = config_models[0]
        elif isinstance(config_models, str):
            final_model = config_models
    if not final_model:
        final_model = "doubao-seed-1-6-251015"
    
    final_temp = temperature if temperature is not None else ai_config.get("temperature", 0.6)
    final_top_p = top_p if top_p is not None else ai_config.get("top_p", 0.9)
    final_base_url = provider_config.get("base_url")
    final_lang = language if language else ai_config.get("default_language", "Chinese")

    try:
        with open(data_file, 'r') as f:
            raw_data = json.load(f)
    except Exception as e:
        logger.error(f"Error reading data file {data_file}: {e}")
        return

    project_info = raw_data.setdefault('project_info', {})
    if tissue_type: project_info['tissue_type'] = tissue_type
    if goal: project_info['goal'] = goal
    if final_lang: project_info['language'] = final_lang
    
    extra_params_dict = {}
    for param in extra_params:
        if '=' in param:
            k, v = param.split('=', 1)
            extra_params_dict[k.strip()] = v.strip()
    if extra_params_dict:
        project_info['extra_params'] = extra_params_dict

    is_dir_output = os.path.isdir(output) or output.endswith(os.sep) or output.endswith("/")
    if is_dir_output:
        os.makedirs(output, exist_ok=True)
        final_output_path = generate_output_filename(project_id, project_info.get('tissue_type'), final_lang, output)
    else:
        final_output_path = output

    if final_output_path.lower().endswith(".md"):
        base_path = final_output_path[:-3]
    else:
        base_path = final_output_path

    log_file_path = base_path + ".log"
    json_log_file_path = base_path + ".json"

    configure_logging(log_level, log_file=log_file_path, json_log_file=json_log_file_path)
    
    logger.info(f"[{trace_id}] Starting interpretation task for Project: [bold cyan]{project_id}[/bold cyan]")
    logger.debug(f"[{trace_id}] Config: {config_file or 'Default'}, Provider: {final_provider}, Model: {final_model}")
    logger.info(f"[{trace_id}] Report will be saved to: {final_output_path}")
    
    engine = AIInterpreter(model=final_model, provider=final_provider, base_url=final_base_url, config=ai_config)
    if not template_file:
        template_file = str(prompt_root() / "report" / "rnaseq_standard.md.j2")
    
    engine.generate_report(
        data_json=raw_data,
        template_path=template_file,
        attachments=attachments,
        output_path=final_output_path,
        temperature=final_temp,
        top_p=final_top_p,
        trace_id=trace_id
    )
