#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict

def _validate_df(df: pd.DataFrame, required_cols: List[str], index_col: str) -> None:
    """[Internal function] Validate DataFrame integrity and uniqueness (unchanged)"""
    try:
        from snakemake_logger_plugin_rich_loguru import get_analysis_logger
        logger = get_analysis_logger()
    except ImportError:
        import logging
        logger = logging.getLogger("Analysis")

    # 1. Validate required columns
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"❌ Sample table format error! Missing columns: {missing_cols}")
        sys.exit(1)

    # 2. Validate ID uniqueness
    if df[index_col].duplicated().any():
        duplicated_ids = df[df[index_col].duplicated()][index_col].unique().tolist()
        logger.error(f"❌ Sample IDs are not unique! Duplicate IDs: {duplicated_ids}")
        sys.exit(1)

    # 3. Validate null values
    if df[required_cols].isnull().any().any():
        nan_rows = df[df[required_cols].isnull().any(axis=1)][index_col].tolist()
        logger.warning(f"⚠️ Warning: Samples contain null values: {nan_rows}")

def load_samples(csv_path, required_cols=None, index_col="sample",logger = None) -> Tuple[bool, Dict]:
    """
    Read CSV and automatically generate BAM paths.

    Returns:
        merge_group (bool): Returns True only when all groups have > 1 samples.
        samples_dict (dict): Dictionary containing sample information.
    """
    if required_cols is None:
        required_cols = [index_col, "group"]

    file_path = Path(csv_path)
    if not file_path.exists():
        logger.error(f"❌ Error: Sample table file not found: {file_path}")
        sys.exit(1)

    try:
        # Read and clean data
        df = pd.read_csv(file_path, dtype=str, comment='#')
        df.columns = df.columns.str.strip()
        df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

        _validate_df(df, required_cols, index_col)

        # =========================================================
        # [Core modification] Check logic: all groups must have > 1 sample
        # =========================================================
        group_counts = df['group'].value_counts()

        # .all() : Returns True only when all values in the Series are True
        merge_group = (group_counts > 1).all()

        # Detailed debug information
        if merge_group:
            logger.info(f"[bold green]✅ Merge condition satisfied:[/bold green] All groups contain biological replicates (All groups have >1 samples).")
            logger.info(f"   Merge Mode -> [bold green]ON[/bold green]")
        else:
            # Find which groups are single-sample, causing False
            single_sample_groups = group_counts[group_counts <= 1].index.tolist()
            logger.warning(f"[bold yellow]⚠️ Merge condition not satisfied:[/bold yellow] Single-sample groups detected (Singletons detected).")
            logger.warning(f"   Groups preventing full merge: [bold red]{single_sample_groups}[/bold red]")
            logger.warning(f"   Merge Mode -> [bold red]OFF[/bold red]")

        # Automatically construct BAM paths
        df['bam'] = df[index_col].apply(
            lambda x: f"02.mapping/Bowtie2/{x}/{x}.sorted.bam"
        )

        samples_dict = df.set_index(index_col, drop=False).to_dict(orient="index")
        return merge_group, samples_dict

    except Exception as e:
        logger.warning(f"[bold red]❌ Error: load_samples parsing failed: {e}[/bold red]")
        sys.exit(1)

def load_contrasts(csv_path, samples_dict, logger=None):
    """
    Parse contrast table and match corresponding BAM file paths based on samples_dict.
    """
    try:
        from snakemake_logger_plugin_rich_loguru import get_analysis_logger
        logger = get_analysis_logger() if logger is None else logger
    except ImportError:
        import logging
        logger = logging.getLogger("Analysis") if logger is None else logger

    file_path = Path(csv_path)
    if not file_path.exists():
        logger.error(f"❌ Error: Contrast table file not found: {file_path}")
        sys.exit(1)

    try:
        # 1. Read and clean data
        df = pd.read_csv(file_path, dtype=str, comment='#')
        df.columns = df.columns.str.strip()
        df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

        if "Control" not in df.columns or "Treat" not in df.columns:
            logger.error(f"❌ Error: contrasts.csv must contain 'Control' and 'Treat' columns")
            sys.exit(1)

        all_contrasts = []
        contrast_map = {}

        # 2. Iterate through each contrast row
        for _, row in df.iterrows():
            ctrl_grp = row['Control']
            treat_grp = row['Treat']
            c_name = f"{ctrl_grp}_vs_{treat_grp}"

            # 3. Filter BAMs from samples_dict
            # Since load_samples already ensures each row has a 'bam' key, we can directly access it
            bams_ctrl = [
                info['bam'] for info in samples_dict.values()
                if info['group'] == ctrl_grp
            ]
            bams_treat = [
                info['bam'] for info in samples_dict.values()
                if info['group'] == treat_grp
            ]

            # 4. Only check if samples were found (logical check), not physical file existence
            if not bams_ctrl:
                logger.warning(f"⚠️ Warning: Group '{ctrl_grp}' has no samples, skipping {c_name}")
                continue
            if not bams_treat:
                logger.warning(f"⚠️ Warning: Group '{treat_grp}' has no samples, skipping {c_name}")
                continue

            all_contrasts.append(c_name)
            contrast_map[c_name] = {
                "b1": bams_ctrl,
                "b2": bams_treat
            }

        return all_contrasts, contrast_map

    except Exception as e:
        logger.error(f"❌ Error: load_contrasts parsing failed: {e}")
        sys.exit(1)

def parse_groups(samples_dict: Dict, logger=None) -> Dict[str, List[str]]:
    """
    Invert the SampleID -> Info dictionary to Group -> [SampleID_1, SampleID_2] dictionary.

    Args:
        samples_dict: Dictionary returned by load_samples

    Returns:
        dict: {'Control': ['s1', 's2'], 'Treat': ['s3', 's4']}
    """
    try:
        from snakemake_logger_plugin_rich_loguru import get_analysis_logger
        logger = get_analysis_logger() if logger is None else logger
    except ImportError:
        import logging
        logger = logging.getLogger("Analysis") if logger is None else logger

    # Using defaultdict(list) eliminates the need for "if key not in dict" checks, making code more concise
    groups = defaultdict(list)

    for sample_id, info in samples_dict.items():
        # Get the group name for this sample
        group_name = info.get('group')

        if group_name:
            groups[group_name].append(sample_id)
        else:
            # Defensive programming: in case there's no group field (though load_samples validates this)
            logger.warning(f"⚠️ Warning: Sample {sample_id} has no group info!")

    return dict(groups) # Convert back to regular dictionary before returning


if __name__ == "__main__":
    import tempfile

    # Scenario 1: Perfect case (all groups have replicates) -> Expect True
    csv_perfect = """sample, sample_name, group
    s1, A_rep1, GroupA
    s2, A_rep2, GroupA
    s3, B_rep1, GroupB
    s4, B_rep2, GroupB
    """

    # Scenario 2: Mixed case (GroupA has replicates, GroupB has only one) -> Expect False
    csv_mixed = """sample, sample_name, group
    s1, A_rep1, GroupA
    s2, A_rep2, GroupA
    s3, B_rep1, GroupB
    """

    print("\n--- Test Scenario 1: All groups have replicates (Expect: True) ---")
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as tmp:
        tmp.write(csv_perfect)
        path1 = tmp.name
    load_samples(path1)
    os.remove(path1)

    print("\n--- Test Scenario 2: Mixed case (Expect: False) ---")
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as tmp:
        tmp.write(csv_mixed)
        path2 = tmp.name
    load_samples(path2)
    os.remove(path2)