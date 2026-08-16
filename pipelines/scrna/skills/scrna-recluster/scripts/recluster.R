#!/usr/bin/env Rscript
# recluster.R — CLI wrapper for the SingleSampleSubClusterRereduction function library.
# Re-cluster a single-sample Seurat object: Normalize -> HVG -> Scale -> PCA ->
# auto PC cutoff -> FindNeighbors/FindClusters -> UMAP, then save the new object
# and a summary.json (OSDP section 6.3).

suppressPackageStartupMessages(library(optparse))

## Resolve this script's own directory so the function library can be sourced
## regardless of the caller's working directory.
cmd_args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", cmd_args, value = TRUE)
if (length(file_arg) == 0L) {
  cat("ERROR: cannot determine script path; invoke via 'Rscript scripts/recluster.R ...'\n",
      file = stderr())
  quit(save = "no", status = 1)
}
script_dir <- dirname(normalizePath(sub("^--file=", "", file_arg[1L])))
source(file.path(script_dir, "SingleSampleSubClusterRereduction.r"))

option_list <- list(
  make_option("--input", type = "character", default = NULL,
              help = "Path to the input Seurat object RDS file [required]"),
  make_option("--output", type = "character", default = NULL,
              help = "Output directory; created if it does not exist [required]"),
  make_option("--name", type = "character", default = "recluster",
              help = "Prefix used for output file names [default %default]"),
  make_option("--resolution", type = "double", default = 1.2,
              help = "Clustering resolution passed to FindClusters [default %default]"),
  make_option("--nfeatures", type = "integer", default = 2000,
              help = "Number of highly variable features [default %default]"),
  make_option("--normalization-method", type = "character", default = "LogNormalize",
              dest = "normalization_method",
              help = "NormalizeData method [default %default]"),
  make_option("--scale-factor", type = "double", default = 10000,
              dest = "scale_factor",
              help = "NormalizeData scale.factor [default %default]")
)

opt <- parse_args(OptionParser(
  option_list = option_list,
  description = paste0(
    "Re-cluster a single-sample Seurat object (or a subset of one) with automatic ",
    "PC cutoff selection. Writes <name>-reclustered.rds, elbow plots and summary.json."
  )
))

captured_warnings <- character(0)

main <- function(opt) {
  if (is.null(opt$input) || is.null(opt$output)) {
    stop("both --input and --output are required; see --help", call. = FALSE)
  }
  if (!file.exists(opt$input)) {
    stop(sprintf("input file not found: %s", opt$input), call. = FALSE)
  }
  if (!dir.exists(opt$output)) {
    dir.create(opt$output, showWarnings = FALSE, recursive = TRUE)
  }

  obj <- tryCatch(
    readRDS(opt$input),
    error = function(e) {
      stop(sprintf("failed to read RDS file '%s': %s",
                   opt$input, conditionMessage(e)), call. = FALSE)
    }
  )
  if (!inherits(obj, "Seurat")) {
    stop("input RDS is not a Seurat object", call. = FALSE)
  }
  if (!"RNA" %in% Seurat::Assays(obj)) {
    stop("input Seurat object has no RNA assay; cannot recluster", call. = FALSE)
  }
  rna_counts <- tryCatch(obj[["RNA"]]$counts, error = function(e) NULL)
  if (is.null(rna_counts)) {
    stop("RNA assay has no counts layer; reclustering requires raw counts", call. = FALSE)
  }

  ## The function library references a GLOBAL `logger` (inside AutoSettingPcCutoff),
  ## so it must be created in the global environment before the call.
  logger <<- log4r_init()
  info(logger, sprintf("Reclustering %d cells (resolution = %s, nfeatures = %s)",
                       ncol(obj), opt$resolution, opt$nfeatures))

  new_obj <- withCallingHandlers(
    SingleSampleSubClusterRereduction(
      Seurat = obj,
      AutoSettingPcCutoff_plot_name = opt$name,
      normalization.method = opt$normalization_method,
      scale.factor = opt$scale_factor,
      nfeatures = opt$nfeatures,
      resolution = opt$resolution,
      save_dir = opt$output
    ),
    warning = function(w) {
      captured_warnings <<- c(captured_warnings, conditionMessage(w))
      invokeRestart("muffleWarning")
    }
  )

  ## Recompute the PC cutoff from the new object's PCA (same rule as the library:
  ## max of "cumulative >90% and single PC <5%" vs "last adjacent diff >0.1%").
  pc_stdev <- new_obj[["pca"]]@stdev
  pct <- pc_stdev / sum(pc_stdev) * 100
  cumu <- cumsum(pct)
  co1 <- which(cumu > 90 & pct < 5)[1]
  co2 <- sort(which((pct[1:length(pct) - 1] - pct[2:length(pct)]) > 0.1),
              decreasing = TRUE)[1] + 1
  pc_cutoff <- max(co1, co2)

  rds_file <- file.path(opt$output, paste0(opt$name, "-reclustered.rds"))
  saveRDS(new_obj, rds_file)

  n_cells <- ncol(new_obj)
  n_clusters <- length(levels(new_obj$seurat_clusters))

  summary <- list(
    tool = "SingleSampleSubClusterRereduction",
    version = "0.9.0",
    status = "success",
    outputs = list(
      list(path = basename(rds_file), type = "rds"),
      list(path = paste0(opt$name, "-PCT-ElbowPlot.pdf"), type = "figure"),
      list(path = paste0(opt$name, "-pct-ElbowPlot.png"), type = "figure")
    ),
    stats = list(
      n_cells = n_cells,
      n_clusters = n_clusters,
      pc_cutoff = pc_cutoff
    ),
    warnings = unique(captured_warnings)
  )
  jsonlite::write_json(summary, file.path(opt$output, "summary.json"),
                       auto_unbox = TRUE, pretty = TRUE)
  info(logger, sprintf("Done: %d cells, %d clusters, PC cutoff %d",
                       n_cells, n_clusters, pc_cutoff))
  invisible(TRUE)
}

result <- tryCatch(main(opt), error = function(e) e)
if (inherits(result, "error")) {
  cat(sprintf("ERROR: %s\n", conditionMessage(result)), file = stderr())
  quit(save = "no", status = 1)
}
quit(save = "no", status = 0)
