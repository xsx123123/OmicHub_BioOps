import os
import subprocess
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, template_dir: str):
        """
        初始化 ReportGenerator。
        
        Args:
            template_dir: 存放 Jinja2 模板的目录路径
        """
        self.template_dir = Path(template_dir)
        if not self.template_dir.exists():
            raise FileNotFoundError(f"Template directory not found: {self.template_dir}")
            
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(['html', 'xml', 'qmd.j2', 'j2']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        logger.info(f"ReportGenerator initialized with templates at: {self.template_dir}")

    def render(self, template_name: str, data: Dict[str, Any], output_path: str) -> str:
        """
        将数据注入模板并渲染为 .qmd 文件。
        
        Args:
            template_name: 模板文件名 (例如 'rna_seq.qmd.j2')
            data: 用于渲染的数据字典
            output_path: 渲染后的 .qmd 文件保存路径
            
        Returns:
            生成的 .qmd 文件的绝对路径
        """
        try:
            template = self.env.get_template(template_name)
            rendered_content = template.render(**data)
            
            out_path = Path(output_path)
            # 确保输出目录存在
            out_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(rendered_content)
                
            logger.info(f"Template '{template_name}' rendered to '{out_path}'")
            return str(out_path.resolve())
            
        except Exception as e:
            logger.error(f"Failed to render template {template_name}: {e}")
            raise

    def build(self, qmd_path: str, output_format: str = 'html') -> str:
        """
        调用 Quarto 构建最终报告。
        
        Args:
            qmd_path: .qmd 文件路径
            output_format: 输出格式 ('html', 'pdf', 'docx')
            
        Returns:
            生成的报告文件路径
        """
        qmd_file = Path(qmd_path)
        if not qmd_file.exists():
            raise FileNotFoundError(f"QMD file not found: {qmd_path}")

        logger.info(f"Building report from {qmd_path} to {output_format}...")
        
        # 构造 Quarto 命令
        cmd = ["quarto", "render", str(qmd_file), "--to", output_format]
        
        # 仅针对 HTML 格式强制使用 embed-resources (Word/PDF 不需要，因为它们本质上就是单文件)
        if output_format == 'html':
            cmd.extend(["-M", "embed-resources:true"])
        
        try:
            # 检查 Quarto 是否安装
            # 注意: 某些环境可能在 PATH 中找不到 quarto，这里做一个简单的 check
            try:
                subprocess.run(["quarto", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (FileNotFoundError, subprocess.CalledProcessError):
                msg = "Quarto executable not found in PATH. Please install Quarto (https://quarto.org/)."
                logger.error(msg)
                raise RuntimeError(msg)
            
            # 执行渲染
            result = subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            
            logger.info("Quarto build successful.")
            
            # 假设输出文件名与输入名相同，只是后缀改变
            # Quarto 默认行为: input.qmd -> input.html
            output_file = qmd_file.with_suffix(f'.{output_format}')
            
            if not output_file.exists():
                logger.warning(f"Expected output file {output_file} not found after successful build.")
            
            return str(output_file)

        except subprocess.CalledProcessError as e:
            logger.error(f"Quarto build failed with return code {e.returncode}")
            logger.error(f"Stderr: {e.stderr}")
            raise RuntimeError(f"Quarto build failed: {e.stderr}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during build: {e}")
            raise
