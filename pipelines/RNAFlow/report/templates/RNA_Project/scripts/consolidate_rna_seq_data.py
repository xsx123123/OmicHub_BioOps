#!/usr/bin/env python3
"""
Consolidate RNA-seq analysis data and generate AI interpretation reports.
Supports two subcommands:
  1. generate: Consolidate data from JSON/CSV into a text file.
  2. report: Send the consolidated text to an AI model for interpretation.
"""

import json
import os
import argparse
import csv
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
from loguru import logger
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

from rich.logging import RichHandler

# Import RichHelpFormatter
try:
    from rich_argparse import RichHelpFormatter
except ImportError:
    # Fallback if not installed (though user just requested it)
    RichHelpFormatter = argparse.RawDescriptionHelpFormatter

# Import AI Engine
try:
    from ai.engine import AIInterpreter
except ImportError:
    # Handle case where ai package is not in python path directly
    sys.path.append(str(Path(__file__).resolve().parent))
    from ai.engine import AIInterpreter

# -----------------------------------------------------------------------------
# Configuration & Constants
# -----------------------------------------------------------------------------

# Dynamic path resolution
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

# Default paths
DEFAULT_OUTPUT_PATH = DATA_DIR / "consolidated_rna_seq_data.txt"
DEFAULT_PROMPT_PATH = Path(os.environ.get("OMICHUB_PROMPT_ROOT", "/opt/omichub/prompts")) / "report" / "rnaseq_compact.md"
PROJECT_SUMMARY_PATH = DATA_DIR / "project_summary.json"
DEFAULT_REPORT_DIR = DATA_DIR / "ai_reports"


# -----------------------------------------------------------------------------
# Logging & Utilities
# -----------------------------------------------------------------------------

def setup_logging(verbose: bool = False):
    """Configure loguru logging with Rich integration."""
    logger.remove()  # Remove default handler

    # Console Handler (Rich)
    # Using RichHandler for beautiful console logs
    console_level = "DEBUG" if verbose else "INFO"
    logger.add(
        RichHandler(
            rich_tracebacks=True, 
            markup=True, 
            show_time=False, 
            show_path=False
        ),
        format="{message}",
        level=console_level
    )

    # File Handler (Detailed)
    logger.add(
        "rna_seq_tool.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB"
    )


def safe_resolve_path(path_str: str) -> Optional[Path]:
    """
    Safely resolve path relative to the data directory.
    Handles paths starting with '../data/' by mapping them to DATA_DIR.
    """
    if not path_str:
        return None
    
    path_str = str(path_str)
    
    # Handle relative paths that start with ../data/
    if path_str.startswith('../data/'):
        # Remove ../data/ prefix and join with DATA_DIR
        relative_part = path_str.replace('../data/', '', 1)
        resolved_path = DATA_DIR / relative_part
    else:
        # Resolve relative to CWD or absolute
        resolved_path = Path(path_str).resolve()
    
    logger.debug(f"Resolved path: {path_str} -> {resolved_path}")
    return resolved_path


def read_file_content(file_path: Path) -> str:
    """Read full content of a text file."""
    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return ""
    try:
        return file_path.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return ""


def csv_to_markdown_table(
    file_path: Path, 
    delimiter: str = '\t', 
    max_rows: Optional[int] = None,
    exclude_columns: Optional[List[str]] = None,
    filter_rows_func: Optional[Callable[[List[str]], bool]] = None
) -> str:
    """
    Read a CSV/TSV file and convert it to a Markdown table string.
    """
    if not file_path.exists():
        logger.warning(f"File not found for table conversion: {file_path}")
        return ""

    try:
        with open(file_path, 'r', encoding='utf-8', newline='') as f:
            # Auto-detect dialect if possible, otherwise fallback to provided delimiter
            try:
                sample = f.read(1024)
                f.seek(0)
                dialect = csv.Sniffer().sniff(sample, delimiters=[delimiter, ','])
                reader = csv.reader(f, dialect)
            except csv.Error:
                f.seek(0)
                reader = csv.reader(f, delimiter=delimiter)

            rows = list(reader)

        if not rows:
            return "*Empty file*"

        header = rows[0]
        data_rows = rows[1:]

        # 1. Row Filtering (Pre-limit)
        if filter_rows_func:
            data_rows = [row for row in data_rows if filter_rows_func(row)]

        if max_rows is not None:
            data_rows = data_rows[:max_rows]

        # 2. Column Exclusion
        if exclude_columns:
            # Identify indices to keep
            keep_indices = [i for i, col in enumerate(header) if col not in exclude_columns]
            
            # Update header
            header = [header[i] for i in keep_indices]
            
            # Update data rows
            new_data_rows = []
            for row in data_rows:
                # Handle rows that might differ in length, though csv reader handles this mostly
                # We simply grab indices if they exist
                new_row = [row[i] for i in keep_indices if i < len(row)]
                new_data_rows.append(new_row)
            data_rows = new_data_rows

        # Markdown Table Construction
        # 1. Header
        md_lines = []
        md_lines.append("| " + " | ".join(header) + " |")
        # 2. Separator
        md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        # 3. Data
        for row in data_rows:
            # Handle rows that might be shorter than header
            padded_row = row + [""] * (len(header) - len(row))
            md_lines.append("| " + " | ".join(padded_row) + " |")

        return "\n".join(md_lines)

    except Exception as e:
        logger.error(f"Error converting {file_path} to markdown: {e}")
        return f"Error reading table: {e}"


# -----------------------------------------------------------------------------
# Subcommand: Generate (Consolidate Data)
# -----------------------------------------------------------------------------

def run_generate(
    output_path: Path,
    deg_limit: int,
    enrichment_limit: int,
    prompt_path: Optional[Path],
    verbose: bool
):
    """
    Consolidate RNA-seq data into a text file.
    """
    console = Console()
    setup_logging(verbose)

    logger.info("Starting RNA-seq data consolidation")
    console.print(Panel("[bold blue]Task: Generate Consolidated Data[/bold blue]", expand=False))

    # 1. Load Project Summary
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("Loading project summary...", total=None)
        
        if not PROJECT_SUMMARY_PATH.exists():
            console.print(f"[red]Error: Project summary not found at {PROJECT_SUMMARY_PATH}[/red]")
            return

        try:
            with open(PROJECT_SUMMARY_PATH, 'r', encoding='utf-8') as f:
                project_summary = json.load(f)
        except Exception as e:
            console.print(f"[red]Error parsing project summary: {e}[/red]")
            return
            
        progress.update(task, completed=True)

    # 2. Extract Data
    project_meta = project_summary.get('project_meta', {})
    stats = project_summary.get('stats', {})
    input_files = project_summary.get('input_files', {})

    output_lines = []

    # -- Header --
    output_lines.append("# RNA-seq Analysis Summary\n")

    # -- Project Info --
    output_lines.append("## 1. Project Information\n")
    for key, val in project_meta.items():
        output_lines.append(f"- **{key.replace('_', ' ').title()}**: {val}")
    output_lines.append("\n")
    
    output_lines.append("## 2. Analysis Statistics\n")
    output_lines.append(f"- **Total Samples**: {stats.get('total_samples', 'N/A')}")
    output_lines.append(f"- **Groups**: {stats.get('group_count', 'N/A')}")
    output_lines.append("\n")

    # -- FASTP Stats --
    fastp_path = safe_resolve_path(input_files.get('fastp_stats_file'))
    if fastp_path and fastp_path.exists():
        output_lines.append("## 3. QC: FASTP Trimming Statistics\n")
        output_lines.append(csv_to_markdown_table(fastp_path, delimiter='\t', max_rows=10))
        output_lines.append("\n")

    # -- Mapping Stats --
    mapping_path = safe_resolve_path(input_files.get('mapping_file'))
    if mapping_path and mapping_path.exists():
        output_lines.append("## 4. QC: Mapping Statistics\n")
        
        # Filter function: Keep only clean sample names (exclude . and _stats)
        def clean_samples_filter(row: List[str]) -> bool:
            if not row:
                return False
            sample_name = row[0]
            return '.' not in sample_name and '_stats' not in sample_name

        output_lines.append(csv_to_markdown_table(
            mapping_path, 
            delimiter='\t', 
            max_rows=10, 
            filter_rows_func=clean_samples_filter
        ))
        output_lines.append("\n")

    # -- Expression (TPM) --
    tpm_path = safe_resolve_path(input_files.get('tpm_file'))
    if tpm_path and tpm_path.exists():
        output_lines.append("## 5. Expression Levels (TPM - Preview)\n")
        output_lines.append(csv_to_markdown_table(tpm_path, delimiter='\t', max_rows=10))
        output_lines.append("\n")

    # -- Contrasts --
    contrasts_path = safe_resolve_path(input_files.get('contrasts_file'))
    if contrasts_path and contrasts_path.exists():
        output_lines.append("## 6. Experimental Contrasts\n")
        output_lines.append(csv_to_markdown_table(contrasts_path, delimiter=',')) # Usually CSV
        output_lines.append("\n")

    # -- Differential Expression --
    deg_dir = safe_resolve_path(input_files.get('deg_dir'))
    if deg_dir and deg_dir.exists():
        deg_files = list(deg_dir.glob("*_DEG.csv"))
        if deg_files:
            target_deg = deg_files[0] # Take the first one for summary
            output_lines.append(f"## 7. Differential Expression ({target_deg.stem})\n")
            output_lines.append(f"Showing top {deg_limit} genes:\n")
            output_lines.append(csv_to_markdown_table(target_deg, delimiter=',', max_rows=deg_limit))
            output_lines.append("\n")

    # -- Enrichment --
    enrichment_dir = safe_resolve_path(input_files.get('enrichment_dir'))
    if enrichment_dir and enrichment_dir.exists():
        output_lines.append("## 8. Enrichment Analysis (Top Terms)\n")
        
        # Check for UP and DOWN files
        for suffix in ["_UP.csv", "_DOWN.csv"]:
             files = list(enrichment_dir.glob(f"*{suffix}"))
             if files:
                 f = files[0]
                 direction = "Upregulated" if "UP" in suffix else "Downregulated"
                 output_lines.append(f"### {direction} Genes Enrichment ({f.stem})\n")
                 output_lines.append(csv_to_markdown_table(
                     f, 
                     delimiter=',', 
                     max_rows=enrichment_limit,
                     exclude_columns=['geneID']
                 ))
                 output_lines.append("\n")

    # 3. Write Output
    final_content = []
    
    # Prepend prompt if exists
    target_prompt_path = prompt_path if prompt_path else DEFAULT_PROMPT_PATH
    if target_prompt_path and target_prompt_path.exists():
        prompt_content = read_file_content(target_prompt_path)
        if prompt_content:
            final_content.append(prompt_content)
            final_content.append("\n\n---\n\n")

    final_content.extend(output_lines)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save Consolidated Data
        full_text = "\n".join(final_content)
        output_path.write_text(full_text, encoding='utf-8')
        
        logger.success(f"Consolidated data written to {output_path}")
        console.print(f"[green]✓[/green] Consolidated data written to [bold]{output_path}[/bold]")
        console.print(f"[blue]📊[/blue] Output format: Markdown")
        
    except Exception as e:
        logger.error(f"Failed to write output: {e}")
        console.print(f"[red]Failed to write output: {e}[/red]")


# -----------------------------------------------------------------------------
# Subcommand: Report (Generate AI Report)
# -----------------------------------------------------------------------------

def run_report(
    input_path: Path,
    output_dir: Path,
    model: Optional[str],
    temperature: float,
    verbose: bool
):
    """
    Generate AI interpretation report from the consolidated text file.
    """
    console = Console()
    setup_logging(verbose)

    logger.info("Starting AI Report Generation")
    console.print(Panel("[bold purple]Task: AI Interpretation Report[/bold purple]", expand=False))

    if not input_path.exists():
        console.print(f"[red]Error: Input file not found at {input_path}[/red]")
        return

    # 1. Read Input
    try:
        input_text = input_path.read_text(encoding='utf-8')
        logger.info(f"Read input file: {input_path} ({len(input_text)} chars)")
    except Exception as e:
        console.print(f"[red]Error reading input file: {e}[/red]")
        return

    # 2. Initialize AI Interpreter
    try:
        interpreter = AIInterpreter(model=model) if model else AIInterpreter()
    except Exception as e:
        console.print(f"[red]Error initializing AI Interpreter: {e}[/red]")
        return

    # 3. Call AI
    console.print("[dim]Sending data to AI model... (This may take a minute)[/dim]")
    
    try:
        prompt_root = Path(os.environ.get("OMICHUB_PROMPT_ROOT", "/opt/omichub/prompts"))
        system_prompt = (prompt_root / "report" / "compact_system.md").read_text(encoding="utf-8").strip()
        user_content = [{"type": "text", "text": input_text}]
        trace_id = f"cli-report-{os.getpid()}"
        
        response = interpreter.execute_inference(
            system_prompt=system_prompt,
            user_content=user_content,
            trace_id=trace_id,
            temperature=temperature
        )
        
        # 4. Save Report
        output_dir.mkdir(parents=True, exist_ok=True)
        report_file = output_dir / "AI_Interpretation_Report.md"
        
        # Verify and extract content (removes XML tags if present)
        final_report_content = interpreter._verify_and_extract_content(response.content)
        
        report_file.write_text(final_report_content, encoding='utf-8')
        
        logger.success(f"AI Report generated: {report_file}")
        console.print(f"[green]✓[/green] AI Report generated at: [bold]{report_file}[/bold]")
        
        # Show cost if available
        if hasattr(interpreter, '_calculate_cost'):
             cost = interpreter._calculate_cost(response)
             console.print(f"[blue]💰[/blue] Estimated Cost: ¥{cost}")

    except Exception as e:
        logger.error(f"AI Report generation failed: {e}")
        console.print(f"[red]✗ AI Report generation failed: {e}[/red]")


# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------

def main():
    # RichHelpFormatter config
    if hasattr(RichHelpFormatter, "styles"):
        RichHelpFormatter.styles["argparse.groups"] = "bold cyan"
        RichHelpFormatter.styles["argparse.metavar"] = "bold yellow"
        RichHelpFormatter.styles["argparse.args"] = "green"

    parser = argparse.ArgumentParser(
        description="RNA-seq Data Consolidation & AI Reporting Tool",
        formatter_class=RichHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True, help='Subcommands')

    # --- Generate Subcommand ---
    parser_gen = subparsers.add_parser(
        'generate', 
        help='Consolidate data into text format',
        formatter_class=RichHelpFormatter
    )
    parser_gen.add_argument(
        '--output', '-o',
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f'Output file path (default: {DEFAULT_OUTPUT_PATH.name})'
    )
    parser_gen.add_argument(
        '--deg-limit', '-d',
        type=int,
        default=20,
        help='Max DEG rows to include'
    )
    parser_gen.add_argument(
        '--enrichment-limit', '-e',
        type=int,
        default=10,
        help='Max enrichment terms to include'
    )
    parser_gen.add_argument(
        '--prompt-path', '-p',
        type=Path,
        default=None,
        help='Custom prompt file path'
    )
    parser_gen.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    # --- Report Subcommand ---
    parser_rep = subparsers.add_parser(
        'report', 
        help='Generate AI report from consolidated text',
        formatter_class=RichHelpFormatter
    )
    parser_rep.add_argument(
        '--input', '-i',
        type=Path,
        required=True,
        help='Input text file path (generated by `generate` command)'
    )
    parser_rep.add_argument(
        '--output-dir', '-od',
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help='Directory to save the AI report'
    )
    parser_rep.add_argument(
        '--model', '-m',
        type=str,
        default=None,
        help='Specific model ID to use'
    )
    parser_rep.add_argument(
        '--temperature', '-t',
        type=float,
        default=0.7,
        help='Model temperature (creativity)'
    )
    parser_rep.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Dispatch to appropriate function
    if args.command == 'generate':
        run_generate(
            output_path=args.output,
            deg_limit=args.deg_limit,
            enrichment_limit=args.enrichment_limit,
            prompt_path=args.prompt_path,
            verbose=args.verbose
        )
    elif args.command == 'report':
        run_report(
            input_path=args.input,
            output_dir=args.output_dir,
            model=args.model,
            temperature=args.temperature,
            verbose=args.verbose
        )

if __name__ == "__main__":
    main()
