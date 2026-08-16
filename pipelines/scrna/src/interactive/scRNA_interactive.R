#' Interactive scRNA-seq Analysis Pipeline
#'
#' This script loads all functions from the scRNA-seq analysis pipeline
#' into the R environment for interactive analysis.
#'
#' Usage:
#'   1. Set your working directory to the pipeline root: setwd("/path/to/scRNA_seq_Analysis_pipeline")
#'   2. Source this script: source("scRNA_interactive.R")
#'   3. All pipeline functions will be available for interactive use
#'
#' Author: JZhang
#' Date: 2025-12-22

# Set pipeline path to current working directory
PIPELINE_PATH <- getwd()

# Check if the scRNAseqMulticommand directory exists and contains files
scRNAseq_dir <- file.path(PIPELINE_PATH, 'scRNAseqMulticommand')
if (dir.exists(scRNAseq_dir) && length(list.files(scRNAseq_dir)) > 0) {
  info(logger,'PIPELINE_PATH Check OK\n')
} else {
  info(logger,'PIPELINE_PATH Check Failed\n')
  stop('The scRNAseqMulticommand directory is missing or empty')
}

#-----------------------------------####---------------------------------------#
# Pre-load required packages
#-----------------------------------####---------------------------------------#
required_packages <- c(
  "yaml", "qs", "log4r", "getopt", "stringr", "crayon", "praise", "data.table",
  "Seurat", "dplyr", "ggplot2", "patchwork", "parallel", "foreach", "doParallel",
  "SingleR", "celldex", "scran", "scater", "limma", "cluster", "RANN", "igraph",
  "uwot", "future", "future.apply", "BiocGenerics", "Matrix", "stats", "utils",
  "methods", "base", "grid", "gtable", "scales", "rlang", "tidyr", "tibble",
  "purrr", "readr", "magrittr", "ggrepel", "viridis", "RColorBrewer",'pander',
  'zellkonverter')

# Install and load packages as needed
for(pkg in required_packages) {
  if (!require(pkg, character.only = TRUE)) {
    info(logger,"Installing package:", pkg, "\n")
    if (!pkg %in% rownames(installed.packages())) {
      if (pkg %in% rownames(available.packages())) {
        # install.packages(pkg, repos = "https://cran.rstudio.com/")
      } else {
        # Try Bioconductor for bioinformatics packages
        if (!requireNamespace("BiocManager", quietly = TRUE)) {
          install.packages("BiocManager")
        }
        BiocManager::install(pkg)
      }
    }
    library(pkg, character.only = TRUE)
  }
}

#-----------------------------------####---------------------------------------#
# Load initialization scripts
#-----------------------------------####---------------------------------------#
source(file.path(PIPELINE_PATH, 'src/init/00.log4r.r'))
source(file.path(PIPELINE_PATH, 'src/init/01.Multicommand.r'))
source(file.path(PIPELINE_PATH, 'src/init/02.Print_Analysis_Config.r'))
source(file.path(PIPELINE_PATH, 'src/init/03.init.r'))
source(file.path(PIPELINE_PATH, 'src/init/04.logo.r'))

#-----------------------------------####---------------------------------------#
# Initialize logging (with console output only for interactive use)
#-----------------------------------####---------------------------------------#
logger <- log4r_init(level = "INFO", log_file = NULL)

#-----------------------------------####---------------------------------------#
# Load core analysis functions
#-----------------------------------####---------------------------------------#
# Load the main core functions
source(file.path(PIPELINE_PATH, 'src/core/core_main.r'))

# Additionally, load the main scripts referenced in the YAML config
# (These are loaded dynamically in the main pipeline, so we'll load them here too)
yaml_path <- file.path(PIPELINE_PATH, 'scRNAseqMulticommand.yaml')
if (file.exists(yaml_path)) {
  yaml_config <- suppressWarnings(yaml.load_file(yaml_path, readLines.warn = T))

  # Load scripts as defined in the YAML configuration
  if (!is.null(yaml_config$scripts)) {
    if (!is.null(yaml_config$scripts$general_scripts)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$general_scripts))
    }
    if (!is.null(yaml_config$scripts$color_Package)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$color_Package))
    }
    if (!is.null(yaml_config$scripts$dir)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$dir))
    }
    if (!is.null(yaml_config$scripts$main)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$main))
    }
    if (!is.null(yaml_config$scripts$cellID)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$cellID))
    }
    if (!is.null(yaml_config$scripts$gene_sets_prepare)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$gene_sets_prepare))
    }
    if (!is.null(yaml_config$scripts$sctype_score)) {
      source(file.path(PIPELINE_PATH, yaml_config$scripts$sctype_score))
    }
  }
} else {
  # If YAML doesn't exist, try to load common script paths
  common_script_paths <- c(
    'src/core/00.help_function.r',
    'src/core/01.parameter.r',
    'src/core/02.cells_qc.r',
    'src/core/03.AmbientRNA.r',
    'src/core/04.Checkdoublet.r',
    'src/core/05.Normal_PCA.r',
    'src/core/06.Merge_integer.r',
    'src/core/07.DEG.r',
    'src/core/07.FindClusterMarkersDotplot.r',
    'src/core/08.obj_subset.r',
    'src/core/10.annotation.r',
    'src/core/11.single_sample.r',
    'src/core/12.multisample.r',
    'src/viz/01.vis_dim_reduction.r',
    'src/viz/02.vis_annotation.r',
    'src/viz/03.vis_proportions.r',
    'src/viz/04.vis_expression.r',
    'src/viz/05.vis_qc_spatial.r',
    'src/viz/06.vis_data_export.r'
  )

  for (script_path in common_script_paths) {
    full_path <- file.path(PIPELINE_PATH, script_path)
    if (file.exists(full_path)) {
      source(full_path)
      info(logger,"Loaded:", script_path, "\n")
    } else {
      info(logger,"Warning: File not found:", script_path, "\n")
    }
  }
}
#-----------------------------------####---------------------------------------#
# Load CLI initialization (for parameter setup functions)
#-----------------------------------####---------------------------------------#
# Only load the initialization project functions, not the command line parsing
source(file.path(PIPELINE_PATH, 'src/cli/00.Initialize_Project.r'))
#-----------------------------------####---------------------------------------#
# Define helper functions for interactive use
#-----------------------------------####---------------------------------------#
#' Display available functions
#'
#' Shows a list of commonly used functions from the pipeline
display_functions <- function() {
  info(logger,"\n=== Available scRNA-seq Analysis Functions ===\n\n")

  functions <- c(
    "InitializeProject()",
    "Check_sample()",
    "multisample_scRNA_seq_analysis()",
    "singlesample_scRNA_seq_analysis()",
    "sc_RNA_seq_raw_qc()",
    "sc_RNA_seq_filted_qc()",
    "AutoFiltCells()",
    "Checkdoublet()",
    "NormalFeature()",
    "AutoPCA()",
    "MergeSeuratObjectBatchCheck()",
    "DealPatch()",
    "FindMarkerCluster()",
    "AutoSigleRAnn()",
    "DimPlotUMAPtSNE()",
    "DrawVolcanoSCRNA()",
    "AddModuleScorePlot()",
    "SubsetIntergetSeuratObject()"
  )

  for (func in functions) {
    info(logger,"-", func, "\n")
  }

  info(logger,"\nUse ?function_name to get help on any function.\n")
}

#' Quick start for interactive analysis
#'
#' Sets up a basic context for analysis with common parameters
quick_start_context <- function(project_name = "interactive_analysis",
                               base_dir = getwd(),
                               scRNAtype = "10x") {

  # Create basic context similar to the command-line version
  ctx <- list()

  # Basic directories
  ctx$projectname <- project_name
  ctx$basedir <- base_dir
  ctx$scRNAtype <- scRNAtype

  # Analysis directories
  ctx$obj_dir <- file.path(base_dir, "obj")
  ctx$figure_dir <- file.path(base_dir, "figure")
  ctx$data_dir <- file.path(base_dir, "data")
  ctx$tmp_dir <- file.path(base_dir, "tmp")

  # Quality control parameters
  ctx$pct_mt <- 20
  ctx$min_genes <- 200
  ctx$max_genes <- 6000
  ctx$min_cells <- 3
  ctx$doublet_rate <- 0.0755  # Default doublet rate

  # Analysis parameters
  ctx$reduceType <- "umap"  # Default reduction type
  ctx$normal_method <- "LogNormalize"  # Default normalization method
  ctx$integration_method <- "Harmony"  # Default integration method

  # Create directories if they don't exist
  dir.create(ctx$obj_dir, showWarnings = FALSE, recursive = TRUE)
  dir.create(ctx$figure_dir, showWarnings = FALSE, recursive = TRUE)
  dir.create(ctx$data_dir, showWarnings = FALSE, recursive = TRUE)
  dir.create(ctx$tmp_dir, showWarnings = FALSE, recursive = TRUE)

  info(logger,"Context initialized for project:", project_name, "\n")
  info(logger,"Base directory:", base_dir, "\n")
  info(logger,"Available directories:\n")
  info(logger,"  obj_dir:", ctx$obj_dir, "\n")
  info(logger,"  figure_dir:", ctx$figure_dir, "\n")
  info(logger,"  data_dir:", ctx$data_dir, "\n")

  return(ctx)
}

#-----------------------------------####---------------------------------------#
# Define helper functions for interactive use
#-----------------------------------####---------------------------------------#

#' Display available functions
#'
#' Shows a list of commonly used functions from the pipeline
display_functions <- function() {
  info(logger,"\n=== Available scRNA-seq Analysis Functions ===\n\n")

  functions <- c(
    "InitializeProject()",
    "Check_sample()",
    "multisample_scRNA_seq_analysis()",
    "singlesample_scRNA_seq_analysis()",
    "sc_RNA_seq_raw_qc()",
    "sc_RNA_seq_filted_qc()",
    "AutoFiltCells()",
    "Checkdoublet()",
    "NormalFeature()",
    "AutoPCA()",
    "MergeSeuratObjectBatchCheck()",
    "DealPatch()",
    "FindMarkerCluster()",
    "AutoSigleRAnn()",
    "DimPlotUMAPtSNE()",
    "DrawVolcanoSCRNA()",
    "AddModuleScorePlot()",
    "SubsetIntergetSeuratObject()"
  )

  for (func in functions) {
    info(logger,"-", func, "\n")
  }

  info(logger,"\nUse ?function_name to get help on any function.\n")
}

#' Quick start for interactive analysis
#'
#' Sets up a basic context for analysis with common parameters
quick_start_context <- function(project_name = "interactive_analysis",
                               base_dir = getwd(),
                               scRNAtype = "10x") {

  # Create basic context similar to the command-line version
  ctx <- list()

  # Basic directories
  ctx$projectname <- project_name
  ctx$basedir <- base_dir
  ctx$scRNAtype <- scRNAtype

  # Analysis directories
  ctx$obj_dir <- file.path(base_dir, "obj")
  ctx$figure_dir <- file.path(base_dir, "figure")
  ctx$data_dir <- file.path(base_dir, "data")
  ctx$tmp_dir <- file.path(base_dir, "tmp")

  # Quality control parameters
  ctx$pct_mt <- 20
  ctx$min_genes <- 200
  ctx$max_genes <- 6000
  ctx$min_cells <- 3
  ctx$doublet_rate <- 0.0755  # Default doublet rate

  # Analysis parameters
  ctx$reduceType <- "umap"  # Default reduction type
  ctx$normal_method <- "LogNormalize"  # Default normalization method
  ctx$integration_method <- "Harmony"  # Default integration method

  # Create directories if they don't exist
  dir.create(ctx$obj_dir, showWarnings = FALSE, recursive = TRUE)
  dir.create(ctx$figure_dir, showWarnings = FALSE, recursive = TRUE)
  dir.create(ctx$data_dir, showWarnings = FALSE, recursive = TRUE)
  dir.create(ctx$tmp_dir, showWarnings = FALSE, recursive = TRUE)

  info(logger,"Context initialized for project:", project_name, "\n")
  info(logger,"Base directory:", base_dir, "\n")
  info(logger,"Available directories:\n")
  info(logger,"  obj_dir:", ctx$obj_dir, "\n")
  info(logger,"  figure_dir:", ctx$figure_dir, "\n")
  info(logger,"  data_dir:", ctx$data_dir, "\n")

  return(ctx)
}

info(logger,"\n=== scRNA-seq Interactive Analysis Environment Loaded ===\n")
info(logger,"Pipeline path:", PIPELINE_PATH, "\n")
info(logger,"All functions from the scRNA-seq pipeline are now available.\n")
info(logger,"Use display_functions() to see available functions.\n")
info(logger,"Use quick_start_context() to initialize a basic analysis context.\n\n")