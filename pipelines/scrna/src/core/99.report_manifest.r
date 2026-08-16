# ==============================================================================
# Report Manifest Generator
# Author: zhang jian
# Description: Generates standardized summary.json files for analysis steps and a
#              global manifest.json for downstream Quarto report consumption.
#              It can be called from the running pipeline or used to backfill JSON
#              files from an existing scRNAseqMulticommand result directory.
# ==============================================================================

`%||%` <- function(x, y) {
  if (is.null(x) || length(x) == 0) y else x
}

.utc_timestamp <- function() {
  format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
}

.safe_json_write <- function(data, file_path) {
  dir.create(dirname(file_path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(data, path = file_path, pretty = TRUE, auto_unbox = TRUE, null = "null")
}

.log_report_info <- function(message) {
  if (exists("logger") && inherits(get("logger"), "logger")) {
    info(logger, message)
  }
}

.escape_regex <- function(x) {
  gsub("([][{}()+*^$|\\\\?.])", "\\\\\\1", x)
}

.normal_path <- function(path, mustWork = FALSE) {
  normalizePath(path, winslash = "/", mustWork = mustWork)
}

.rel_path <- function(path, root) {
  if (is.null(path) || is.na(path) || !nzchar(path)) return(NA_character_)
  root_norm <- .normal_path(root, mustWork = TRUE)
  path_norm <- .normal_path(path, mustWork = file.exists(path))
  rel <- sub(paste0("^", .escape_regex(root_norm), "/?"), "", path_norm)
  if (!nzchar(rel)) "." else rel
}

.infer_result_dir <- function(step_dir, levels_up) {
  result_dir <- .normal_path(step_dir, mustWork = FALSE)
  for (i in seq_len(levels_up)) {
    result_dir <- dirname(result_dir)
  }
  result_dir
}

.safe_read_table <- function(file_path, nrows = -1) {
  if (!file.exists(file_path)) return(data.frame())
  ext <- tolower(tools::file_ext(file_path))
  sep <- if (ext %in% c("tsv", "txt")) "\t" else ","
  tryCatch(
    utils::read.table(
      file_path,
      header = TRUE,
      sep = sep,
      quote = "\"",
      comment.char = "",
      check.names = FALSE,
      stringsAsFactors = FALSE,
      fill = TRUE,
      nrows = nrows
    ),
    error = function(e) data.frame()
  )
}

.count_data_rows <- function(file_path) {
  if (!file.exists(file_path)) return(0L)
  lines <- tryCatch(readLines(file_path, warn = FALSE), error = function(e) character(0))
  max(length(lines) - 1L, 0L)
}

.numeric_or_na <- function(x) {
  suppressWarnings(as.numeric(x))
}

.is_missing_scalar <- function(x) {
  if (is.null(x) || length(x) == 0) return(TRUE)
  if (length(x) > 1) return(FALSE)
  if (is.na(x)) return(TRUE)
  if (is.character(x)) {
    value <- trimws(x)
    return(!nzchar(value) || toupper(value) %in% c("NA", "N/A", "NULL", "NONE", "NAN"))
  }
  FALSE
}

.first_non_missing <- function(...) {
  values <- list(...)
  for (value in values) {
    if (!.is_missing_scalar(value)) return(value)
  }
  NA
}

.summarise_numeric <- function(x) {
  values <- .numeric_or_na(x)
  values <- values[is.finite(values)]
  if (length(values) == 0) {
    return(list(min = NA_real_, median = NA_real_, mean = NA_real_, max = NA_real_))
  }
  list(
    min = unname(min(values)),
    median = unname(stats::median(values)),
    mean = unname(mean(values)),
    max = unname(max(values))
  )
}

.named_count_list <- function(x, max_items = 100) {
  x <- x[!is.na(x)]
  if (length(x) == 0) return(list())
  counts <- sort(table(as.character(x)), decreasing = TRUE)
  counts <- counts[seq_len(min(length(counts), max_items))]
  lapply(names(counts), function(name) {
    list(name = name, count = unname(as.integer(counts[[name]])))
  })
}

.file_artifact <- function(result_dir, file_path, description = NULL) {
  rel <- .rel_path(file_path, result_dir)
  list(
    type = tolower(tools::file_ext(file_path)),
    path = rel,
    file = basename(file_path),
    bytes = unname(file.info(file_path)$size),
    description = description %||% NA_character_
  )
}

.build_artifacts <- function(result_dir,
                             rel_dir,
                             types = c("png", "jpg", "jpeg", "gif", "svg", "pdf", "csv", "tsv", "txt", "qs", "rds", "h5ad", "html"),
                             pattern = NULL,
                             recursive = FALSE) {
  dir_path <- file.path(result_dir, rel_dir)
  if (!dir.exists(dir_path)) return(list())
  files <- list.files(dir_path, pattern = pattern, recursive = recursive, full.names = TRUE, ignore.case = TRUE)
  files <- files[file.exists(files) & !dir.exists(files)]
  if (length(files) == 0) return(list())
  files <- files[!basename(files) %in% c("summary.json", "manifest.json")]
  exts <- tolower(tools::file_ext(files))
  files <- files[exts %in% types]
  files <- sort(files)
  lapply(files, function(path) .file_artifact(result_dir, path))
}

.append_artifacts <- function(...) {
  artifacts <- unlist(list(...), recursive = FALSE)
  if (length(artifacts) == 0) return(list())
  paths <- vapply(artifacts, function(x) x$path %||% "", character(1))
  artifacts[!duplicated(paths)]
}

.metric_has_content <- function(metrics) {
  if (is.null(metrics) || length(metrics) == 0) return(FALSE)
  flat <- unlist(metrics, recursive = TRUE, use.names = FALSE)
  flat <- flat[!is.na(flat)]
  if (length(flat) == 0) return(FALSE)
  numeric_flat <- suppressWarnings(as.numeric(flat))
  if (all(!is.na(numeric_flat))) {
    return(any(numeric_flat != 0))
  }
  any(nzchar(as.character(flat)))
}

.summary_has_content <- function(summary_data) {
  length(summary_data$samples %||% list()) > 0 ||
    length(summary_data$artifacts %||% list()) > 0 ||
    length(summary_data$tables %||% list()) > 0 ||
    .metric_has_content(summary_data$metrics %||% list())
}

.status_from_summary <- function(summary_data) {
  if (.summary_has_content(summary_data)) "success" else "warning"
}

.sample_group <- function(sample_name, sample_info = NULL) {
  if (is.null(sample_info) || !is.data.frame(sample_info)) return(NA_character_)
  if (!all(c("name", "group") %in% colnames(sample_info))) return(NA_character_)
  group <- sample_info$group[as.character(sample_info$name) == sample_name]
  group[1] %||% NA_character_
}

.named_vector_lookup <- function(x, name, default = NA) {
  if (is.null(x) || length(x) == 0 || is.null(names(x)) || !(name %in% names(x))) return(default)
  x[[name]]
}

.count_cells_by_sample <- function(cell_info) {
  if (nrow(cell_info) == 0 || !"orig.ident" %in% colnames(cell_info)) return(integer(0))
  counts <- table(as.character(cell_info[["orig.ident"]]))
  stats::setNames(as.integer(counts), names(counts))
}

.doublet_metrics_by_sample <- function(doublet_dir) {
  if (!dir.exists(doublet_dir)) return(list())
  doublet_files <- list.files(doublet_dir, pattern = "-Doublet\\.tsv$", full.names = TRUE)
  metrics <- lapply(doublet_files, function(file_path) {
    sample_name <- sub("-Doublet\\.tsv$", "", basename(file_path))
    tab <- .safe_read_table(file_path)
    total_cells <- if (nrow(tab) > 0) nrow(tab) else .count_data_rows(file_path)
    group <- if ("group" %in% colnames(tab)) unique(as.character(tab$group))[1] else NA_character_
    list(name = sample_name, total_cells = as.integer(total_cells), group = group)
  })
  names(metrics) <- vapply(metrics, function(x) x$name, character(1))
  metrics
}

.read_sample_sheet <- function(sample_sheet = NULL) {
  if (is.null(sample_sheet) || !file.exists(sample_sheet)) return(NULL)
  .safe_read_table(sample_sheet)
}

.infer_samples_from_output <- function(result_dir) {
  qc_files <- list.files(file.path(result_dir, "QC", "Cellranger-result"), pattern = "_filted_setting\\.csv$", full.names = FALSE)
  samples <- sub("_filted_setting\\.csv$", "", qc_files)

  if (length(samples) == 0) {
    doublet_files <- list.files(file.path(result_dir, "QC", "doublet"), pattern = "-Doublet\\.tsv$", full.names = FALSE)
    samples <- sub("-Doublet\\.tsv$", "", doublet_files)
  }

  if (length(samples) == 0) {
    cell_info <- .safe_read_table(file.path(result_dir, "output", "Cell-cluster-infor.csv"), nrows = -1)
    if ("orig.ident" %in% colnames(cell_info)) {
      samples <- unique(as.character(cell_info[["orig.ident"]]))
    }
  }

  sort(unique(samples))
}

.infer_groups_from_output <- function(result_dir) {
  doublet_files <- list.files(file.path(result_dir, "QC", "doublet"), pattern = "-Doublet\\.tsv$", full.names = TRUE)
  groups <- character(0)
  for (file_path in doublet_files) {
    tab <- .safe_read_table(file_path, nrows = 5000)
    if ("group" %in% colnames(tab)) {
      groups <- c(groups, unique(as.character(tab$group)))
    }
  }
  sort(unique(groups[!is.na(groups) & nzchar(groups)]))
}

.infer_integration_method <- function(result_dir, integration_method = NULL) {
  if (!is.null(integration_method) && !is.na(integration_method) && nzchar(integration_method)) {
    return(as.character(integration_method))
  }
  candidates <- list.files(file.path(result_dir, "DealPatch"), recursive = TRUE, full.names = FALSE)
  candidates <- paste(tolower(candidates), collapse = " ")
  if (grepl("harmony", candidates)) return("Harmony")
  if (grepl("rpca", candidates)) return("RPCA")
  if (grepl("scvi", candidates)) return("SCVI")
  if (grepl("cca", candidates)) return("CCA")
  "NULL"
}

.cluster_columns <- function(colnames_vec) {
  grep("cluster|snn_res|seurat_clusters", colnames_vec, value = TRUE, ignore.case = TRUE)
}

.annotation_columns <- function(colnames_vec) {
  grep("singler|cellid|sctype|annotation|celltype|cell_type|predicted", colnames_vec, value = TRUE, ignore.case = TRUE)
}

.top_marker_table <- function(marker_df, top_n = 5) {
  if (nrow(marker_df) == 0 || !"gene" %in% colnames(marker_df)) return(data.frame())
  keep <- intersect(c("cluster", "gene", "avg_log2FC", "pct.1", "pct.2", "p_val_adj", "p_val"), colnames(marker_df))
  marker_df <- marker_df[, keep, drop = FALSE]
  if ("p_val_adj" %in% colnames(marker_df)) {
    marker_df <- marker_df[order(.numeric_or_na(marker_df$p_val_adj)), , drop = FALSE]
  } else if ("p_val" %in% colnames(marker_df)) {
    marker_df <- marker_df[order(.numeric_or_na(marker_df$p_val)), , drop = FALSE]
  }
  if (!"cluster" %in% colnames(marker_df)) {
    return(utils::head(marker_df, top_n))
  }
  rows <- lapply(split(marker_df, marker_df$cluster), utils::head, n = top_n)
  do.call(rbind, rows)
}

# ==============================================================================
# Function: write_step_summary
# Description: Writes a per-step summary.json file.
# ==============================================================================
write_step_summary <- function(step, data, output_dir, status = NULL, timestamp = NULL) {
  timestamp <- timestamp %||% .utc_timestamp()
  status <- status %||% .status_from_summary(data)

  base_fields <- c("samples", "metrics", "artifacts")
  summary_data <- list(
    step = step,
    status = status,
    timestamp = timestamp,
    samples = data$samples %||% list(),
    metrics = data$metrics %||% list(),
    artifacts = data$artifacts %||% list()
  )

  extra_names <- setdiff(names(data), base_fields)
  for (name in extra_names) {
    summary_data[[name]] <- data[[name]]
  }

  summary_path <- file.path(output_dir, "summary.json")
  .safe_json_write(summary_data, summary_path)
  .log_report_info(paste0("  Wrote step summary: ", summary_path))

  invisible(summary_path)
}

# ==============================================================================
# Function: write_manifest
# Description: Writes the global manifest.json based on Run_Context and discovered
#              step summaries.
# ==============================================================================
write_manifest <- function(ctx = list(),
                           output_dir,
                           steps = NULL,
                           final_objects = NULL,
                           timestamp = NULL,
                           metrics = NULL) {
  timestamp <- timestamp %||% .utc_timestamp()
  ctx <- ctx %||% list()

  project_name <- ctx$project_name %||% sub("-scRNA-seq-result$", "", basename(output_dir))
  species_tax_id <- ctx$origin_tax_ID %||% ctx$species_tax_id %||% NA_integer_
  samples <- ctx$infor$infor %||% ctx$samples %||% .infer_samples_from_output(output_dir)
  groups <- unique(ctx$infor$group %||% ctx$groups %||% .infer_groups_from_output(output_dir))
  integration_method <- ctx$intergetmethods %||% ctx$integration_method %||% .infer_integration_method(output_dir)
  pipeline_version <- ctx$pipeline_version %||% if (exists("ScriptsVersion")) ScriptsVersion else "unknown"

  if (is.null(steps)) {
    steps <- .discover_steps(output_dir)
  }

  manifest <- list(
    report_schema_version = "1.0.0",
    pipeline_version = pipeline_version,
    project_name = project_name,
    run_timestamp = timestamp,
    species_tax_id = species_tax_id,
    samples = as.character(samples),
    groups = as.character(groups),
    integration_method = as.character(integration_method),
    metrics = metrics %||% build_cell_metadata_metrics(output_dir),
    steps = steps,
    final_objects = final_objects %||% build_final_objects(output_dir)
  )

  manifest_path <- file.path(output_dir, "manifest.json")
  .safe_json_write(manifest, manifest_path)
  .log_report_info(paste0("  Wrote global manifest: ", manifest_path))

  invisible(manifest_path)
}

.discover_steps <- function(output_dir) {
  step_dirs <- list.dirs(output_dir, recursive = TRUE)
  summary_dirs <- step_dirs[file.exists(file.path(step_dirs, "summary.json"))]

  if (length(summary_dirs) == 0) {
    return(list())
  }

  steps <- lapply(summary_dirs, function(dir_path) {
    rel_path <- .rel_path(dir_path, output_dir)
    summary_json <- tryCatch(
      jsonlite::read_json(file.path(dir_path, "summary.json")),
      error = function(e) list(step = basename(dir_path), status = "unknown")
    )
    list(
      step = summary_json$step %||% basename(dir_path),
      summary = file.path(rel_path, "summary.json"),
      status = summary_json$status %||% "unknown"
    )
  })

  priority <- c("qc", "doublet", "ambient_rna", "batch_check", "integration", "cluster_markers", "annotation", "deg")
  step_names <- vapply(steps, function(x) x$step %||% "", character(1))
  order_idx <- match(step_names, priority)
  steps[order(is.na(order_idx), order_idx, step_names)]
}

# ==============================================================================
# Summary builders
# ==============================================================================

build_qc_summary <- function(qc_dir, sample_info = NULL, result_dir = NULL) {
  cellranger_dir <- if (basename(qc_dir) == "Cellranger-result") qc_dir else file.path(qc_dir, "Cellranger-result")
  result_dir <- result_dir %||% .infer_result_dir(cellranger_dir, levels_up = 2)

  setting_files <- list.files(cellranger_dir, pattern = "_filted_setting\\.csv$", full.names = TRUE)
  cell_info <- .safe_read_table(file.path(result_dir, "output", "Cell-cluster-infor.csv"))
  filtered_counts <- .count_cells_by_sample(cell_info)
  doublet_metrics <- .doublet_metrics_by_sample(file.path(result_dir, "QC", "doublet"))

  samples <- lapply(setting_files, function(file_path) {
    sample_name <- sub("_filted_setting\\.csv$", "", basename(file_path))
    settings <- .safe_read_table(file_path, nrows = 1)
    get_value <- function(name) {
      if (name %in% colnames(settings)) settings[[name]][1] else NA
    }
    doublet_sample <- doublet_metrics[[sample_name]] %||% list()
    filtered_cells <- .first_non_missing(
      .named_vector_lookup(filtered_counts, sample_name),
      doublet_sample$total_cells
    )
    list(
      name = sample_name,
      group = .first_non_missing(.sample_group(sample_name, sample_info), doublet_sample$group),
      origin_cells = .first_non_missing(get_value("origin_cells"), get_value("Origin.Cells")),
      filtered_cells = filtered_cells,
      mt_cutoff = .numeric_or_na(get_value("MT_cutoff_upper")),
      nfeature_lower = .numeric_or_na(get_value("nFeature_cutoff_lower")),
      nfeature_upper = .numeric_or_na(get_value("nFeature_cutoff_upper")),
      filter_mode = as.character(get_value("Mode"))
    )
  })

  artifacts <- .build_artifacts(result_dir, "QC/Cellranger-result", recursive = FALSE)
  mt_values <- vapply(samples, function(x) x$mt_cutoff %||% NA_real_, numeric(1))
  metrics <- list(
    sample_count = length(samples),
    artifact_count = length(artifacts),
    average_mt_cutoff = if (any(is.finite(mt_values))) mean(mt_values[is.finite(mt_values)]) else NA_real_
  )

  list(samples = samples, metrics = metrics, artifacts = artifacts)
}

build_doublet_summary <- function(doublet_dir, result_dir = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(doublet_dir, levels_up = 2)
  doublet_files <- list.files(doublet_dir, pattern = "-Doublet\\.tsv$", full.names = TRUE)

  samples <- lapply(doublet_files, function(file_path) {
    sample_name <- sub("-Doublet\\.tsv$", "", basename(file_path))
    tab <- .safe_read_table(file_path)
    total_cells <- if (nrow(tab) > 0) nrow(tab) else .count_data_rows(file_path)
    doublet_calls <- if ("Doublet" %in% colnames(tab)) {
      sum(tolower(as.character(tab$Doublet)) == "doublet", na.rm = TRUE)
    } else {
      NA_integer_
    }
    group <- if ("group" %in% colnames(tab)) unique(as.character(tab$group))[1] else NA_character_
    list(
      name = sample_name,
      group = group,
      total_cells = as.integer(total_cells),
      doublet_cells = as.integer(doublet_calls),
      singlet_cells = if (is.finite(doublet_calls)) as.integer(total_cells - doublet_calls) else NA_integer_,
      doublet_rate = if (total_cells > 0 && is.finite(doublet_calls)) round(doublet_calls / total_cells * 100, 3) else NA_real_
    )
  })

  total_cells <- sum(vapply(samples, function(x) x$total_cells %||% 0L, integer(1)), na.rm = TRUE)
  total_doublets <- sum(vapply(samples, function(x) x$doublet_cells %||% 0L, integer(1)), na.rm = TRUE)
  artifacts <- .build_artifacts(result_dir, "QC/doublet", recursive = FALSE)

  list(
    samples = samples,
    metrics = list(
      sample_count = length(samples),
      total_cells = total_cells,
      total_doublet_cells = total_doublets,
      doublet_rate = if (total_cells > 0) round(total_doublets / total_cells * 100, 3) else NA_real_,
      artifact_count = length(artifacts)
    ),
    artifacts = artifacts
  )
}

build_ambient_rna_summary <- function(rna_dir, result_dir = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(rna_dir, levels_up = 2)
  artifacts <- .build_artifacts(result_dir, "QC/RNAContamination", recursive = FALSE)
  cell_info <- .safe_read_table(file.path(result_dir, "output", "Cell-cluster-infor.csv"))

  samples <- list()
  contamination_summary <- list()
  if (nrow(cell_info) > 0 && "Contamination" %in% colnames(cell_info)) {
    contamination_summary <- .summarise_numeric(cell_info$Contamination)
    if ("orig.ident" %in% colnames(cell_info)) {
      samples <- lapply(sort(unique(as.character(cell_info$orig.ident))), function(sample_name) {
        idx <- as.character(cell_info$orig.ident) == sample_name
        list(
          name = sample_name,
          cells = sum(idx, na.rm = TRUE),
          mean_contamination = .summarise_numeric(cell_info$Contamination[idx])$mean
        )
      })
    }
  }

  list(
    samples = samples,
    metrics = list(
      contamination = contamination_summary,
      artifact_count = length(artifacts)
    ),
    artifacts = artifacts
  )
}

build_batch_check_summary <- function(batch_dir, result_dir = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(batch_dir, levels_up = 1)
  artifacts <- .build_artifacts(result_dir, "BatchCheck", recursive = FALSE)
  plot_count <- sum(vapply(artifacts, function(x) x$type %in% c("png", "jpg", "jpeg", "pdf"), logical(1)))
  list(
    samples = list(),
    metrics = list(plot_count = plot_count, artifact_count = length(artifacts)),
    artifacts = artifacts
  )
}

build_integration_summary <- function(integration_dir, result_dir = NULL, integration_method = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(integration_dir, levels_up = 1)
  artifacts <- .build_artifacts(result_dir, "DealPatch", recursive = FALSE)
  integrated_checkpoint <- file.path(result_dir, "QC", "doublet", "scrna_seq_integrated.rds")
  if (file.exists(integrated_checkpoint)) {
    artifacts <- .append_artifacts(artifacts, list(.file_artifact(result_dir, integrated_checkpoint, "Integrated Seurat checkpoint")))
  }
  plot_count <- sum(vapply(artifacts, function(x) x$type %in% c("png", "jpg", "jpeg", "pdf"), logical(1)))
  object_count <- sum(vapply(artifacts, function(x) x$type %in% c("qs", "rds", "h5ad"), logical(1)))
  list(
    samples = list(),
    metrics = list(
      integration_method = .infer_integration_method(result_dir, integration_method),
      plot_count = plot_count,
      object_count = object_count,
      artifact_count = length(artifacts)
    ),
    artifacts = artifacts
  )
}

build_cluster_markers_summary <- function(cluster_marker_dir, result_dir = NULL, integration_method = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(cluster_marker_dir, levels_up = 2)

  marker_artifacts <- .build_artifacts(result_dir, "cluster/marker_gene", recursive = FALSE)
  cluster_plot_artifacts <- .append_artifacts(
    .build_artifacts(result_dir, "cluster/UMAP-plot", recursive = FALSE),
    .build_artifacts(result_dir, "cluster/tSNE-plot", recursive = FALSE),
    .build_artifacts(result_dir, "cluster/DotPlot-plot", recursive = FALSE),
    .build_artifacts(result_dir, "cluster/DoHeatmap-plot", recursive = FALSE),
    .build_artifacts(result_dir, "figure", types = c("png", "pdf"), pattern = "Integrated|DimPlot|umap|tsne", recursive = FALSE)
  )
  artifacts <- .append_artifacts(marker_artifacts, cluster_plot_artifacts)

  marker_csvs <- list.files(cluster_marker_dir, pattern = "marker.*\\.csv$|_marker_list\\.csv$", full.names = TRUE, ignore.case = TRUE)
  marker_csvs <- sort(marker_csvs)
  preferred <- marker_csvs[grepl("_clusters_marker_list\\.csv$", basename(marker_csvs), ignore.case = TRUE)]
  main_marker_csv <- preferred[1] %||% marker_csvs[1] %||% NA_character_

  marker_files <- lapply(marker_csvs, function(file_path) {
    marker_df <- .safe_read_table(file_path)
    list(
      path = .rel_path(file_path, result_dir),
      rows = nrow(marker_df),
      clusters = if ("cluster" %in% colnames(marker_df)) length(unique(marker_df$cluster)) else NA_integer_,
      genes = if ("gene" %in% colnames(marker_df)) length(unique(marker_df$gene)) else NA_integer_
    )
  })

  top_markers <- data.frame()
  if (!is.na(main_marker_csv) && file.exists(main_marker_csv)) {
    top_markers <- .top_marker_table(.safe_read_table(main_marker_csv), top_n = 5)
  }

  list(
    samples = list(),
    metrics = list(
      integration_method = .infer_integration_method(result_dir, integration_method),
      marker_file_count = length(marker_csvs),
      plot_count = sum(vapply(cluster_plot_artifacts, function(x) x$type %in% c("png", "jpg", "jpeg", "pdf"), logical(1))),
      artifact_count = length(artifacts),
      marker_files = marker_files
    ),
    artifacts = artifacts,
    tables = list(top_markers = top_markers)
  )
}

build_annotation_summary <- function(annotation_dir, result_dir = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(annotation_dir, levels_up = 1)
  artifacts <- .build_artifacts(result_dir, "annotation", recursive = TRUE)
  cell_info <- .safe_read_table(file.path(result_dir, "output", "Cell-cluster-infor.csv"))

  annotation_counts <- list()
  if (nrow(cell_info) > 0) {
    annotation_cols <- .annotation_columns(colnames(cell_info))
    annotation_counts <- lapply(annotation_cols, function(col_name) {
      list(column = col_name, counts = .named_count_list(cell_info[[col_name]], max_items = 50))
    })
  }

  list(
    samples = list(),
    metrics = list(
      annotation_columns = if (nrow(cell_info) > 0) .annotation_columns(colnames(cell_info)) else character(0),
      annotation_counts = annotation_counts,
      plot_count = sum(vapply(artifacts, function(x) x$type %in% c("png", "jpg", "jpeg", "pdf"), logical(1))),
      object_count = sum(vapply(artifacts, function(x) x$type %in% c("qs", "rds"), logical(1))),
      artifact_count = length(artifacts)
    ),
    artifacts = artifacts
  )
}

build_deg_summary <- function(deg_dir, result_dir = NULL) {
  result_dir <- result_dir %||% .infer_result_dir(deg_dir, levels_up = 2)
  artifacts <- .build_artifacts(result_dir, "figure/deg", recursive = TRUE)
  csv_artifacts <- artifacts[vapply(artifacts, function(x) x$type == "csv", logical(1))]
  png_artifacts <- artifacts[vapply(artifacts, function(x) x$type %in% c("png", "jpg", "jpeg", "pdf"), logical(1))]

  result_files <- lapply(csv_artifacts, function(artifact) {
    file_path <- file.path(result_dir, artifact$path)
    tab <- .safe_read_table(file_path)
    list(path = artifact$path, rows = nrow(tab), columns = colnames(tab))
  })

  list(
    samples = list(),
    metrics = list(
      result_file_count = length(csv_artifacts),
      plot_count = length(png_artifacts),
      artifact_count = length(artifacts),
      result_files = result_files
    ),
    artifacts = artifacts
  )
}

build_cell_metadata_metrics <- function(result_dir) {
  cell_info_path <- file.path(result_dir, "output", "Cell-cluster-infor.csv")
  cell_info <- .safe_read_table(cell_info_path)
  if (nrow(cell_info) == 0) return(list())

  cluster_cols <- .cluster_columns(colnames(cell_info))
  annotation_cols <- .annotation_columns(colnames(cell_info))

  list(
    total_cells = nrow(cell_info),
    samples = if ("orig.ident" %in% colnames(cell_info)) .named_count_list(cell_info[["orig.ident"]]) else list(),
    clusters = lapply(cluster_cols, function(col_name) {
      list(column = col_name, counts = .named_count_list(cell_info[[col_name]], max_items = 100))
    }),
    annotations = lapply(annotation_cols, function(col_name) {
      list(column = col_name, counts = .named_count_list(cell_info[[col_name]], max_items = 100))
    })
  )
}

build_final_objects <- function(output_dir) {
  result_dir <- output_dir
  objects <- list()

  known_files <- c(
    "output/scrna_seq_merge.qs",
    "output/scrna_seq.rds",
    "output/Cell-cluster-infor.csv",
    "QC/doublet/Seurat_list_Doublet.qs",
    "QC/doublet/scrna_seq_integrated.rds"
  )

  for (rel in known_files) {
    path <- file.path(result_dir, rel)
    if (file.exists(path)) {
      objects <- c(objects, list(list(
        type = tolower(tools::file_ext(path)),
        path = rel,
        description = switch(
          rel,
          "output/scrna_seq_merge.qs" = "Final merged Seurat object",
          "output/scrna_seq.rds" = "Final single-sample Seurat object",
          "output/Cell-cluster-infor.csv" = "Cell metadata and cluster assignments",
          "QC/doublet/Seurat_list_Doublet.qs" = "Per-sample Seurat objects after doublet detection",
          "QC/doublet/scrna_seq_integrated.rds" = "Integrated Seurat checkpoint",
          "Pipeline output object"
        )
      )))
    }
  }

  decontx_files <- list.files(file.path(result_dir, "QC", "RNAContamination"), pattern = "decontX.*\\.qs$", full.names = TRUE, ignore.case = TRUE)
  dealpatch_files <- list.files(file.path(result_dir, "DealPatch"), pattern = "\\.qs$", full.names = TRUE, ignore.case = TRUE)
  for (path in c(decontx_files, dealpatch_files)) {
    objects <- c(objects, list(list(
      type = tolower(tools::file_ext(path)),
      path = .rel_path(path, result_dir),
      description = "Pipeline intermediate object"
    )))
  }

  if (length(objects) == 0) return(list())
  paths <- vapply(objects, function(x) x$path, character(1))
  objects[!duplicated(paths)]
}

# ==============================================================================
# Function: generate_report_json
# Description: Backfills step summaries and manifest from an existing result dir.
# ==============================================================================
generate_report_json <- function(result_dir,
                                 project_name = NULL,
                                 species_tax_id = NULL,
                                 integration_method = NULL,
                                 pipeline_version = NULL,
                                 sample_sheet = NULL,
                                 include_empty = TRUE) {
  result_dir <- .normal_path(result_dir, mustWork = TRUE)
  sample_info <- .read_sample_sheet(sample_sheet)

  write_if_content <- function(step, summary_data, output_dir) {
    if (!dir.exists(output_dir)) return(NULL)
    if (!include_empty && !.summary_has_content(summary_data)) return(NULL)
    write_step_summary(step, summary_data, output_dir)
  }

  write_if_content(
    "qc",
    build_qc_summary(file.path(result_dir, "QC", "Cellranger-result"), sample_info = sample_info, result_dir = result_dir),
    file.path(result_dir, "QC", "Cellranger-result")
  )
  write_if_content(
    "doublet",
    build_doublet_summary(file.path(result_dir, "QC", "doublet"), result_dir = result_dir),
    file.path(result_dir, "QC", "doublet")
  )
  write_if_content(
    "ambient_rna",
    build_ambient_rna_summary(file.path(result_dir, "QC", "RNAContamination"), result_dir = result_dir),
    file.path(result_dir, "QC", "RNAContamination")
  )
  write_if_content(
    "batch_check",
    build_batch_check_summary(file.path(result_dir, "BatchCheck"), result_dir = result_dir),
    file.path(result_dir, "BatchCheck")
  )
  write_if_content(
    "integration",
    build_integration_summary(file.path(result_dir, "DealPatch"), result_dir = result_dir, integration_method = integration_method),
    file.path(result_dir, "DealPatch")
  )
  write_if_content(
    "cluster_markers",
    build_cluster_markers_summary(file.path(result_dir, "cluster", "marker_gene"), result_dir = result_dir, integration_method = integration_method),
    file.path(result_dir, "cluster", "marker_gene")
  )
  write_if_content(
    "annotation",
    build_annotation_summary(file.path(result_dir, "annotation"), result_dir = result_dir),
    file.path(result_dir, "annotation")
  )
  write_if_content(
    "deg",
    build_deg_summary(file.path(result_dir, "figure", "deg"), result_dir = result_dir),
    file.path(result_dir, "figure", "deg")
  )

  ctx <- list(
    project_name = project_name %||% sub("-scRNA-seq-result$", "", basename(result_dir)),
    origin_tax_ID = species_tax_id %||% NA_integer_,
    intergetmethods = .infer_integration_method(result_dir, integration_method),
    pipeline_version = pipeline_version %||% if (exists("ScriptsVersion")) ScriptsVersion else "unknown",
    samples = .infer_samples_from_output(result_dir),
    groups = if (!is.null(sample_info) && "group" %in% colnames(sample_info)) unique(sample_info$group) else .infer_groups_from_output(result_dir)
  )

  write_manifest(
    ctx = ctx,
    output_dir = result_dir,
    final_objects = build_final_objects(result_dir),
    metrics = build_cell_metadata_metrics(result_dir)
  )
}

# ==============================================================================
# END
# ==============================================================================
