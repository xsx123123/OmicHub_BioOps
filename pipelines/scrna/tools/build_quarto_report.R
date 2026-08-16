#!/usr/bin/env Rscript
# ==============================================================================
# Build scRNAseqMulticommand Quarto report
# Description: Backfill report JSON from an existing result directory and render
#              the Quarto website using report/ as the template project.
# ==============================================================================

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

parse_args <- function(args) {
  opts <- list(render = TRUE, include_empty = TRUE)
  i <- 1
  while (i <= length(args)) {
    arg <- args[[i]]
    if (arg %in% c("-h", "--help")) {
      opts$help <- TRUE
      i <- i + 1
    } else if (arg == "--no-render") {
      opts$render <- FALSE
      i <- i + 1
    } else if (arg == "--include-empty") {
      opts$include_empty <- TRUE
      i <- i + 1
    } else if (arg == "--skip-empty") {
      opts$include_empty <- FALSE
      i <- i + 1
    } else if (grepl("^--[^=]+=", arg)) {
      key <- sub("^--", "", sub("=.*$", "", arg))
      value <- sub("^[^=]+=", "", arg)
      opts[[gsub("-", "_", key)]] <- value
      i <- i + 1
    } else if (grepl("^--", arg)) {
      key <- gsub("-", "_", sub("^--", "", arg))
      if (i == length(args) || grepl("^--", args[[i + 1]])) {
        stop("Missing value for ", arg, call. = FALSE)
      }
      opts[[key]] <- args[[i + 1]]
      i <- i + 2
    } else {
      stop("Unknown argument: ", arg, call. = FALSE)
    }
  }
  opts
}

usage <- function() {
  cat("Usage:\n")
  cat("  Rscript tools/build_quarto_report.R --result-dir <result_dir> [options]\n\n")
  cat("Options:\n")
  cat("  --result-dir PATH          Existing *-scRNA-seq-result directory. Required.\n")
  cat("  --report-dir PATH          Quarto report template directory. Default: <repo>/report.\n")
  cat("  --project-name NAME        Override project name in manifest.json.\n")
  cat("  --species-tax-id TAXID     Override species tax ID in manifest.json.\n")
  cat("  --integration-method NAME  Override integration method.\n")
  cat("  --pipeline-version NAME    Override pipeline version.\n")
  cat("  --sample-sheet PATH        Optional sample sheet with name/group columns.\n")
  cat("  --include-empty            Write warning summaries for empty known step dirs. Default.\n")
  cat("  --skip-empty               Do not write summaries for empty step dirs.\n")
  cat("  --no-render                Only generate JSON; do not call Quarto.\n")
  cat("  -h, --help                 Show this help message.\n")
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
if (isTRUE(args$help)) {
  usage()
  quit(status = 0)
}
if (is.null(args$result_dir)) {
  usage()
  stop("--result-dir is required", call. = FALSE)
}

initial_options <- commandArgs(trailingOnly = FALSE)
file_arg <- "--file="
script_path <- sub(file_arg, "", initial_options[grep(file_arg, initial_options)])
if (length(script_path) == 0) {
  script_path <- sys.frames()[[1]]$ofile %||% "tools/build_quarto_report.R"
}
repo_root <- dirname(dirname(normalizePath(script_path, mustWork = TRUE)))
report_dir <- normalizePath(args$report_dir %||% file.path(repo_root, "report"), mustWork = TRUE)
result_dir <- normalizePath(args$result_dir, mustWork = TRUE)

source(file.path(repo_root, "src/core/99.report_manifest.r"))


prepare_report_data_link <- function(report_dir, result_dir) {
  data_dir <- file.path(report_dir, "data")
  dir.create(data_dir, recursive = TRUE, showWarnings = FALSE)
  link_path <- file.path(data_dir, "current")
  if (file.exists(link_path) || nzchar(Sys.readlink(link_path))) {
    unlink(link_path, recursive = TRUE, force = TRUE)
  }
  ok <- file.symlink(result_dir, link_path)
  if (!isTRUE(ok)) {
    warning("Could not create report/data/current symlink; falling back to absolute result path.")
    return(result_dir)
  }
  file.path("data", "current")
}

prepare_site_data_link <- function(report_dir, result_dir) {
  site_data_dir <- file.path(report_dir, "_site", "data")
  dir.create(site_data_dir, recursive = TRUE, showWarnings = FALSE)
  link_path <- file.path(site_data_dir, "current")
  if (file.exists(link_path) || nzchar(Sys.readlink(link_path))) {
    unlink(link_path, recursive = TRUE, force = TRUE)
  }
  invisible(file.symlink(result_dir, link_path))
}

manifest_path <- generate_report_json(
  result_dir = result_dir,
  project_name = args$project_name %||% NULL,
  species_tax_id = if (!is.null(args$species_tax_id)) suppressWarnings(as.integer(args$species_tax_id)) else NULL,
  integration_method = args$integration_method %||% NULL,
  pipeline_version = args$pipeline_version %||% NULL,
  sample_sheet = args$sample_sheet %||% NULL,
  include_empty = isTRUE(args$include_empty)
)
cat("Report JSON written: ", manifest_path, "\n", sep = "")

if (isTRUE(args$render)) {
  quarto <- Sys.which("quarto")
  if (!nzchar(quarto)) {
    stop("Quarto executable not found. JSON was generated; install Quarto or rerun with --no-render.", call. = FALSE)
  }
  render_data_dir <- prepare_report_data_link(report_dir, result_dir)
  cat("Rendering Quarto report from: ", report_dir, "\n", sep = "")
  old_wd <- setwd(report_dir)
  on.exit(setwd(old_wd), add = TRUE)
  status <- system2(quarto, args = c("render"), env = c(paste0("SCRNASEQ_REPORT_DATA=", render_data_dir)))
  if (!identical(status, 0L)) {
    stop("quarto render failed with exit status ", status, call. = FALSE)
  }
  prepare_site_data_link(report_dir, result_dir)
  cat("Quarto report written under: ", file.path(report_dir, "_site"), "\n", sep = "")
}
