#!/usr/bin/env Rscript
# =============================================================================
# annotation_stats.R — scrna-annotation-stats skill CLI wrapper
#
# Modes:
#   prop      : cell type proportion stacked barplot (Proplot 2.0v)
#   fisher    : per-celltype proportion Fisher exact test (CalculationRatefisherTest)
#   glm       : per-celltype sample-level binomial GLM + chisq ANOVA (CalculationRateglmTest)
#   deg-prop  : DEG count x cell proportion bubble plot (DrawCellTypePropDEGGene)
#   pct-exp   : percent expressing + average expression per group (CalculationPercentAverageExp)
#
# The sourced library scripts are kept UNMODIFIED. Known upstream quirks are
# worked around at this wrapper layer:
#   * fisher/glm functions hard-reference literal `celltype` / `group` meta.data
#     columns and ignore their column-name arguments -> wrapper normalizes the
#     user columns to literal `celltype` / `group` before calling.
#   * DrawCellTypePropDEGGene hard-codes `Celltype` and orig.ident -> wrapper
#     normalizes both.
#   * GLM_cell_prop.r data2plot() has a filename-concatenation bug -> wrapper
#     never calls it; it writes the result CSV itself.
#   * fisher data2plot() writes into "<control> vs <treat>/" subdir -> wrapper
#     pre-creates it.
# =============================================================================

suppressPackageStartupMessages({
  library(optparse)
  library(jsonlite)
})

TOOL     <- "scrna-annotation-stats"
VERSION  <- "0.9.0"
MODES    <- c("prop", "fisher", "glm", "deg-prop", "pct-exp")

# ---- locate this script's directory (to source sibling libraries) -----------
.args_all <- commandArgs(trailingOnly = FALSE)
.file_arg <- grep("^--file=", .args_all, value = TRUE)
script_dir <- if (length(.file_arg) > 0) {
  dirname(normalizePath(sub("^--file=", "", .file_arg[1])))
} else {
  getwd()
}

# ---- pre-parse repeated --pair (optparse cannot store repeated options) -----
.raw_args <- commandArgs(trailingOnly = TRUE)
pairs <- character(0)
keep_args <- character(0)
i <- 1L
while (i <= length(.raw_args)) {
  a <- .raw_args[i]
  if (a == "--pair") {
    if (i == length(.raw_args)) {
      cat("[ERROR] --pair requires a value in format Treat:Control\n", file = stderr())
      quit(save = "no", status = 2L)
    }
    pairs <- c(pairs, .raw_args[i + 1L])
    i <- i + 2L
  } else if (grepl("^--pair=", a)) {
    pairs <- c(pairs, sub("^--pair=", "", a))
    i <- i + 1L
  } else {
    keep_args <- c(keep_args, a)
    i <- i + 1L
  }
}

# ---- CLI definition ----------------------------------------------------------
option_list <- list(
  make_option("--mode", type = "character", default = NULL,
              help = "Analysis mode: prop | fisher | glm | deg-prop | pct-exp [required]"),
  make_option("--input", type = "character", default = NULL,
              help = "Path to annotated Seurat RDS object [required]"),
  make_option("--output", type = "character", default = NULL,
              help = "Output directory (created if missing) [required]"),
  make_option("--celltype-col", type = "character", default = "celltype",
              help = "meta.data column with cell type annotation [default %default]"),
  make_option("--group-col", type = "character", default = "orig.ident",
              help = "meta.data grouping column [default %default]"),
  make_option("--name", type = "character", default = "prop",
              help = "(prop) Output file name prefix [default %default]"),
  make_option("--treat", type = "character", default = NULL,
              help = "(fisher/glm) Treatment group level [required]"),
  make_option("--control", type = "character", default = NULL,
              help = "(fisher/glm) Control group level [required]"),
  make_option("--pair", type = "character", default = NULL,
              help = "(deg-prop) Pair in format Treat:Control; repeatable, e.g. --pair LC:N --pair T:N [required]"),
  make_option("--project-id", type = "character", default = "deg-prop",
              help = "(deg-prop) Project id used as output file prefix [default %default]"),
  make_option("--genes", type = "character", default = NULL,
              help = "(pct-exp) Comma-separated gene list [required]")
)
parser <- OptionParser(option_list = option_list,
                       usage = "%prog --mode <mode> --input <rds> --output <dir> [options]",
                       description = "Cell proportion statistics & visualization for annotated scRNA-seq Seurat objects.")
opt <- parse_args(parser, args = keep_args)

# ---- helpers -----------------------------------------------------------------
write_summary <- function(output_dir, mode, status, outputs = list(),
                          stats = list(), warnings = character(0), error = NULL) {
  summary <- list(
    tool     = TOOL,
    version  = VERSION,
    status   = status,
    mode     = mode,
    outputs  = outputs,
    stats    = stats,
    warnings = as.list(warnings)
  )
  if (!is.null(error)) summary$error <- error
  tryCatch(
    jsonlite::write_json(summary, file.path(output_dir, "summary.json"),
                         auto_unbox = TRUE, pretty = TRUE),
    error = function(e) NULL
  )
  invisible(NULL)
}

fail <- function(msg, code = 1L) {
  cat(paste0("[ERROR] ", msg, "\n"), file = stderr())
  if (!is.null(opt$output)) {
    dir.create(opt$output, showWarnings = FALSE, recursive = TRUE)
    write_summary(opt$output,
                  ifelse(is.null(opt$mode), "unknown", opt$mode),
                  "failed", error = msg)
  }
  quit(save = "no", status = code)
}

require_pkgs <- function(pkgs) {
  missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing) > 0) {
    fail(paste0("Missing R packages: ", paste(missing, collapse = ", "),
                ". Install them per references/environment.md."))
  }
}

check_cols <- function(seurat, cols) {
  actual <- colnames(seurat@meta.data)
  missing <- setdiff(cols, actual)
  if (length(missing) > 0) {
    fail(paste0("Column(s) not found in meta.data: ", paste(missing, collapse = ", "),
                ". Available columns: ", paste(actual, collapse = ", ")))
  }
}

output_entry <- function(path, type) list(path = path, type = type)

# ---- common validation -------------------------------------------------------
if (is.null(opt$mode)) fail("--mode is required. One of: prop, fisher, glm, deg-prop, pct-exp.", 2L)
if (!opt$mode %in% MODES) fail(paste0("Unknown --mode '", opt$mode, "'. One of: ", paste(MODES, collapse = ", "), "."), 2L)
if (is.null(opt$input))  fail("--input is required.", 2L)
if (is.null(opt$output)) fail("--output is required.", 2L)
if (!file.exists(opt$input)) fail(paste0("Input file not found: ", opt$input))

dir.create(opt$output, showWarnings = FALSE, recursive = TRUE)

seurat <- tryCatch(readRDS(opt$input),
                   error = function(e) fail(paste0("Failed to read RDS: ", conditionMessage(e))))
if (!inherits(seurat, "Seurat")) {
  fail(paste0("Input object is not a Seurat object (class: ",
              paste(class(seurat), collapse = ", "), ")."))
}
check_cols(seurat, opt$`celltype-col`)

warnings_acc <- character(0)

# =============================================================================
# mode: prop — stacked barplot of cell type proportions
# =============================================================================
if (opt$mode == "prop") {
  require_pkgs(c("Seurat", "tidyverse", "ggplot2"))
  source(file.path(script_dir, "propplot.r"))
  check_cols(seurat, opt$`group-col`)

  p <- Proplot(data = seurat, Celltype = opt$`celltype-col`, group.by = opt$`group-col`,
               dir = opt$output, name = opt$name, angle = 45, color_list = NULL)

  pdf_path <- file.path(opt$output, paste0(opt$name, "-prop.pdf"))
  png_path <- file.path(opt$output, paste0(opt$name, "-prop.png"))
  n_groups <- length(unique(seurat@meta.data[[opt$`group-col`]]))
  ggplot2::ggsave(pdf_path, p, width = max(5, 1.2 * n_groups), height = 5)
  ggplot2::ggsave(png_path, p, width = max(5, 1.2 * n_groups), height = 5, dpi = 300)

  csv_path <- file.path(opt$output, paste0(opt$name, "-celltyoe.prop.csv")) # upstream spelling
  write_summary(
    opt$output, opt$mode, "success",
    outputs = list(output_entry(basename(csv_path), "table"),
                   output_entry(basename(pdf_path), "figure"),
                   output_entry(basename(png_path), "figure")),
    stats = list(
      n_cells     = ncol(seurat),
      n_celltypes = length(unique(as.character(seurat@meta.data[[opt$`celltype-col`]]))),
      n_groups    = n_groups
    ),
    warnings = warnings_acc
  )
}

# =============================================================================
# modes: fisher / glm — proportion significance tests
# =============================================================================
if (opt$mode %in% c("fisher", "glm")) {
  require_pkgs(c("Seurat", "tidyverse", "ggplot2"))
  source(file.path(script_dir, "fisher_test_cell_prop.r")) # data2plot/gt2html shared
  if (opt$mode == "glm") source(file.path(script_dir, "GLM_cell_prop.r"))

  if (is.null(opt$treat) || is.null(opt$control)) {
    fail(paste0("--mode ", opt$mode, " requires --treat and --control."), 2L)
  }
  check_cols(seurat, opt$`group-col`)

  # Normalize to the literal column names the upstream functions hard-reference.
  seurat$celltype <- factor(as.character(seurat@meta.data[[opt$`celltype-col`]]))
  seurat$group    <- factor(as.character(seurat@meta.data[[opt$`group-col`]]))

  group_levels <- levels(seurat$group)
  for (g in c(opt$control, opt$treat)) {
    if (!g %in% group_levels) {
      fail(paste0("Group level '", g, "' not found in column '", opt$`group-col`,
                  "'. Available levels: ", paste(group_levels, collapse = ", ")))
    }
  }
  pair <- c(opt$control, opt$treat) # upstream order: c(control, treat)

  if (opt$mode == "fisher") {
    res <- tryCatch(
      CalculationRatefisherTest(seurat = seurat, celltype = "celltype",
                                group = "group", pair = pair),
      error = function(e) fail(paste0("Fisher test failed: ", conditionMessage(e)))
    )
    csv_path <- file.path(opt$output, "fisher-test-result.csv")
    write.csv(res, csv_path, row.names = FALSE)

    # upstream data2plot writes into "<control> vs <treat>/" — pre-create it
    pair_dir <- file.path(opt$output, paste0(pair[1], " vs ", pair[2]))
    dir.create(pair_dir, showWarnings = FALSE, recursive = TRUE)
    tryCatch(data2plot(res, opt$output, pair),
             error = function(e) {
               warnings_acc <<- c(warnings_acc, paste0("data2plot failed: ", conditionMessage(e)))
             })
    if (requireNamespace("gt", quietly = TRUE)) {
      tryCatch(gt2html(res, opt$output, "fisher"),
               error = function(e) {
                 warnings_acc <<- c(warnings_acc, paste0("gt2html failed: ", conditionMessage(e)))
               })
    } else {
      warnings_acc <- c(warnings_acc, "Package 'gt' not installed: HTML result table skipped.")
    }

    meta <- seurat@meta.data
    low_ct <- names(table(meta$celltype)[table(meta$celltype) < 30])
    if (length(low_ct) > 0) {
      warnings_acc <- c(warnings_acc, paste0(
        "Cell types with < 30 cells (low statistical power): ",
        paste(low_ct, collapse = ", ")))
    }
    outputs <- list(output_entry("fisher-test-result.csv", "table"),
                    output_entry(file.path(paste0(pair[1], " vs ", pair[2]), "fisherTest.pdf"), "figure"),
                    output_entry(file.path(paste0(pair[1], " vs ", pair[2]), "fisherTest.png"), "figure"))
    if (file.exists(file.path(opt$output, "fisher-Test.html"))) {
      outputs <- c(outputs, list(output_entry("fisher-Test.html", "table")))
    }
    write_summary(
      opt$output, opt$mode, "success",
      outputs = outputs,
      stats = list(
        n_celltypes   = nrow(res),
        n_significant = sum(res$padj_fisher < 0.05, na.rm = TRUE),
        pair          = paste(pair, collapse = " vs ")
      ),
      warnings = warnings_acc
    )
  } else { # glm
    res <- tryCatch(
      CalculationRateglmTest(seurat = seurat, celltype = "celltype",
                             group = "group", pair = pair),
      error = function(e) fail(paste0(
        "GLM test failed: ", conditionMessage(e),
        ". GLM needs >= 2 biological replicates (orig.ident) per group; check sample counts."))
    )
    csv_path <- file.path(opt$output, "glm-test-result.csv")
    write.csv(res, csv_path, row.names = FALSE) # wrapper writes CSV; upstream data2plot has a filename bug and is never called

    samples_per_group <- tapply(as.character(seurat$orig.ident), seurat$group,
                                function(x) length(unique(x)))
    low_groups <- names(samples_per_group)[samples_per_group < 3]
    if (length(low_groups) > 0) {
      warnings_acc <- c(warnings_acc, paste0(
        "Groups with < 3 biological replicates (GLM power limited): ",
        paste(low_groups, collapse = ", ")))
    }
    write_summary(
      opt$output, opt$mode, "success",
      outputs = list(output_entry("glm-test-result.csv", "table")),
      stats = list(
        n_celltypes   = nrow(res),
        n_significant = sum(res$padj_aov < 0.05, na.rm = TRUE),
        pair          = paste(pair, collapse = " vs "),
        n_samples_per_group = as.list(samples_per_group)
      ),
      warnings = warnings_acc
    )
  }
}

# =============================================================================
# mode: deg-prop — DEG count x cell proportion bubble plot
# =============================================================================
if (opt$mode == "deg-prop") {
  require_pkgs(c("Seurat", "tidyverse", "ggplot2", "log4r", "crayon"))
  source(file.path(script_dir, "DrawCellTypePropDEGGene.r"))

  if (length(pairs) == 0) {
    fail("--mode deg-prop requires at least one --pair Treat:Control (repeatable).", 2L)
  }
  parsed <- strsplit(pairs, ":", fixed = TRUE)
  bad <- pairs[vapply(parsed, length, integer(1)) != 2L |
                 vapply(parsed, function(x) any(!nzchar(trimws(x))), logical(1))]
  if (length(bad) > 0) {
    fail(paste0("Invalid --pair format: ", paste(bad, collapse = ", "),
                ". Expected 'Treat:Control', e.g. --pair LC:N --pair T:N."), 2L)
  }
  check_cols(seurat, opt$`group-col`)
  group_vals <- unique(as.character(seurat@meta.data[[opt$`group-col`]]))
  for (pr in parsed) {
    for (g in trimws(pr)) {
      if (!g %in% group_vals) {
        fail(paste0("Pair level '", g, "' not found in column '", opt$`group-col`,
                    "'. Available values: ", paste(group_vals, collapse = ", ")))
      }
    }
  }

  # Normalize to the literal names the upstream function hard-codes:
  #   celltype column -> `Celltype`; grouping column -> orig.ident (in-memory copy only).
  seurat$Celltype <- as.character(seurat@meta.data[[opt$`celltype-col`]])
  if (opt$`group-col` != "orig.ident") {
    seurat@meta.data$orig.ident <- seurat@meta.data[[opt$`group-col`]]
  }

  group_list <- lapply(parsed, function(pr) list(tread = trimws(pr[1]), control = trimws(pr[2])))
  names(group_list) <- paste0("Group_", seq_along(group_list))

  p <- tryCatch(
    DrawCellTypePropDEGGene(Seurat = seurat, group_list = group_list,
                            celltype = "Celltype", color_low = "#fff6b7",
                            color_heigh = "#f6416c", save_dir = opt$output,
                            project_id = opt$`project-id`),
    error = function(e) fail(paste0("DrawCellTypePropDEGGene failed: ", conditionMessage(e)))
  )

  n_pairs <- length(group_list)
  pdf_path <- file.path(opt$output, paste0(opt$`project-id`, "-DrawCellTypePropDEGGene.pdf"))
  png_path <- file.path(opt$output, paste0(opt$`project-id`, "-DrawCellTypePropDEGGene.png"))
  w <- 3.5 * min(n_pairs, 3); h <- 3.5 * ceiling(n_pairs / 3) + 1.5
  ggplot2::ggsave(pdf_path, p, width = w, height = h)
  ggplot2::ggsave(png_path, p, width = w, height = h, dpi = 300)

  write_summary(
    opt$output, opt$mode, "success",
    outputs = list(
      output_entry(paste0(opt$`project-id`, "-DrawCellTypePropDEGGene.csv"), "table"),
      output_entry(basename(pdf_path), "figure"),
      output_entry(basename(png_path), "figure")),
    stats = list(
      n_celltypes = length(unique(seurat$Celltype)),
      n_pairs     = n_pairs,
      pairs       = as.list(pairs)
    ),
    warnings = warnings_acc
  )
}

# =============================================================================
# mode: pct-exp — percent expressing + average expression per group
# =============================================================================
if (opt$mode == "pct-exp") {
  require_pkgs(c("Seurat", "tidyverse", "scCustomize", "log4r", "crayon"))
  source(file.path(script_dir, "CalculationPercentAverageExp.r"))

  # scCustomize >= 2.0 renamed Percent_Expressing arguments
  # (gene -> features, group_by -> group.by). The library script hard-calls
  # scCustomize::Percent_Expressing(..., group_by = ...); bridge it with a
  # process-local shim via assignInNamespace (no package files are modified).
  .pe <- scCustomize::Percent_Expressing
  if (!"group_by" %in% names(formals(.pe))) {
    .pe_shim <- function(seurat_object, features, threshold = 0, group_by = NULL, ...) {
      .pe(seurat_object = seurat_object, features = features,
          threshold = threshold, group.by = group_by, ...)
    }
    assignInNamespace("Percent_Expressing", .pe_shim, ns = "scCustomize")
  }

  if (is.null(opt$genes)) fail("--mode pct-exp requires --genes (comma-separated).", 2L)
  genes <- trimws(strsplit(opt$genes, ",", fixed = TRUE)[[1]])
  genes <- genes[nzchar(genes)]
  if (length(genes) == 0) fail("--genes is empty after parsing.", 2L)
  check_cols(seurat, opt$`group-col`)

  missing_genes <- setdiff(genes, rownames(seurat))
  if (length(missing_genes) == length(genes)) {
    fail(paste0("None of the requested genes found in the object: ",
                paste(missing_genes, collapse = ", ")))
  }
  if (length(missing_genes) > 0) {
    warnings_acc <- c(warnings_acc, paste0("Genes not found and skipped: ",
                                           paste(missing_genes, collapse = ", ")))
  }
  genes <- intersect(genes, rownames(seurat))

  res <- tryCatch(
    CalculationPercentAverageExp(seurat_obj = seurat, gene = genes, group_by = opt$`group-col`),
    error = function(e) fail(paste0("CalculationPercentAverageExp failed: ", conditionMessage(e)))
  )
  csv_path <- file.path(opt$output, "pct-avg-exp.csv")
  write.csv(res, csv_path, row.names = FALSE)

  write_summary(
    opt$output, opt$mode, "success",
    outputs = list(output_entry("pct-avg-exp.csv", "table")),
    stats = list(
      n_genes  = length(genes),
      n_groups = length(unique(as.character(seurat@meta.data[[opt$`group-col`]])))
    ),
    warnings = warnings_acc
  )
}

cat("[OK] ", TOOL, " mode=", opt$mode, " done. Summary: ",
    file.path(opt$output, "summary.json"), "\n", sep = "")
