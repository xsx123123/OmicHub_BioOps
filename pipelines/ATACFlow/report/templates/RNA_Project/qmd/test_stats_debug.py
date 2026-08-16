import os
import sys

# Add scripts to path
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '../scripts')))

from report_utils import get_project_summary_stats

data_dir = "../data/index/"
qc_filename = "../data/index/multiqc_qc_general_stats.txt"
mapping_filename = "../data/index/multiqc_mapping_general_stats.txt"
tpm_filename = "../data/index/merge_rsem_tpm.tsv"
sample_filename = "../data/index/sample.csv"

print(f"Testing with CWD: {os.getcwd()}")
print(f"Data dir: {data_dir}")
print(f"QC file: {qc_filename}")

stats, df = get_project_summary_stats(
    data_dir=data_dir,
    qc_filename=qc_filename,
    mapping_filename=mapping_filename,
    tpm_filename=tpm_filename,
    sample_filename=sample_filename
)

print("\n--- Stats ---")
print(stats)
print("\n--- DataFrame Head ---")
print(df.head() if not df.empty else "DataFrame is empty")
