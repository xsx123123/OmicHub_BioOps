# scRNAseqMulticommand Quarto Report

This Quarto project generates an interactive HTML report from scRNAseqMulticommand pipeline outputs.

## Recommended Workflow

Generate report JSON from an existing pipeline result directory and render the HTML site:

```bash
Rscript tools/build_quarto_report.R \
  --result-dir /path/to/project-scRNA-seq-result \
  --project-name MyProject \
  --species-tax-id 10090 \
  --integration-method Harmony
```

The command writes `manifest.json` at the result root, writes per-step `summary.json` files under the corresponding output folders, and renders the Quarto website to `report/_site/`.

To only generate JSON without rendering Quarto:

```bash
Rscript tools/build_quarto_report.R --result-dir /path/to/project-scRNA-seq-result --no-render
```

## Direct Quarto Rendering

If JSON files already exist, render the report directly from a local data link:

```bash
cd report
ln -sfn /path/to/project-scRNA-seq-result data/current
SCRNASEQ_REPORT_DATA=data/current quarto render
ln -sfn /path/to/project-scRNA-seq-result _site/data/current
```

Alternatively, copy your pipeline output directory to `report/data/` and run:

```bash
cd report
SCRNASEQ_REPORT_DATA=data/<project-scRNA-seq-result> quarto render
```

Open `report/_site/index.html` in your browser.

## Project Structure

- `index.qmd` - Project overview dashboard
- `01-qc.qmd` - Quality control, doublet detection, ambient RNA
- `02-integration.qmd` - Batch effect and integration
- `03-clustering.qmd` - Clustering and marker genes
- `04-annotation.qmd` - Cell type annotation
- `05-deg.qmd` - Differential expression
- `06-methods.qmd` - Methods and parameters
- `R/` - Helper R functions
- `styles/` - Custom CSS/SCSS themes
- `_quarto.yml` - Quarto project configuration

## Data Contract

The report expects the pipeline output directory to contain:

- `manifest.json` - Global summary of the analysis run
- `summary.json` files in each step directory, such as `QC/Cellranger-result/summary.json`, `QC/doublet/summary.json`, `DealPatch/summary.json`, and `cluster/marker_gene/summary.json`
- Plots and CSV files referenced by the summaries

See `docs/QUARTO_REPORT_ARCHITECTURE.md` for the full data contract.
