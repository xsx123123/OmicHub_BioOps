# ==============================================================================
# tables.R
# Description: Helper functions for rendering tables in the Quarto report.
# ==============================================================================

is_missing_report_value <- function(x) {
  if (is.factor(x)) x <- as.character(x)
  missing <- is.na(x)
  if (is.character(x)) {
    value <- trimws(x)
    missing <- missing | !nzchar(value) | toupper(value) %in% c("NA", "N/A", "NULL", "NONE", "NAN")
  }
  missing
}

clean_report_table <- function(df) {
  if (is.null(df) || nrow(df) == 0) return(data.frame())
  for (name in colnames(df)) {
    if (is.factor(df[[name]])) df[[name]] <- as.character(df[[name]])
    if (is.character(df[[name]])) {
      df[[name]][is_missing_report_value(df[[name]])] <- NA_character_
    }
  }
  rownames(df) <- NULL
  df
}

drop_all_missing_columns <- function(df, keep = character(0)) {
  if (is.null(df) || nrow(df) == 0) return(data.frame())
  drop <- vapply(colnames(df), function(name) {
    !(name %in% keep) && all(is_missing_report_value(df[[name]]))
  }, logical(1))
  df[, !drop, drop = FALSE]
}

as_table_rows <- function(x) {
  if (is.null(x) || length(x) == 0) return(data.frame())
  if (is.data.frame(x)) return(clean_report_table(x))

  rows <- lapply(x, function(item) {
    if (is.null(item)) return(NULL)
    as.data.frame(item, stringsAsFactors = FALSE)
  })
  rows <- rows[!vapply(rows, is.null, logical(1))]
  if (length(rows) == 0) return(data.frame())
  clean_report_table(do.call(rbind, rows))
}

table_col <- function(df, name, default = NA) {
  if (name %in% colnames(df)) return(df[[name]])
  rep(default, nrow(df))
}

render_count_table <- function(counts, name_label = "name", count_label = "count") {
  df <- as_table_rows(counts)
  if (nrow(df) == 0) return(data.frame())
  keep <- intersect(c(name_label, count_label), colnames(df))
  if (length(keep) > 0) df <- df[, keep, drop = FALSE]
  clean_report_table(df)
}

render_qc_table <- function(summary_list) {
  if (is.null(summary_list)) return(data.frame())
  if (is.data.frame(summary_list) || !is.list(summary_list) || any(c("step", "samples", "metrics", "artifacts") %in% names(summary_list))) {
    summary_list <- list(summary_list)
  }

  rows <- lapply(summary_list, function(s) {
    samples <- as_table_rows(s$samples)
    if (nrow(samples) == 0) return(NULL)

    origin <- suppressWarnings(as.numeric(table_col(samples, "origin_cells")))
    filtered <- suppressWarnings(as.numeric(table_col(samples, "filtered_cells")))
    retention <- ifelse(is.finite(origin) & origin > 0 & is.finite(filtered), round(filtered / origin * 100, 2), NA)

    data.frame(
      Sample = table_col(samples, "name"),
      Group = table_col(samples, "group"),
      Origin.Cells = origin,
      Filtered.Cells = filtered,
      Retention.Rate = retention,
      MT.Cutoff = suppressWarnings(as.numeric(table_col(samples, "mt_cutoff"))),
      nFeature.Lower = suppressWarnings(as.numeric(table_col(samples, "nfeature_lower"))),
      nFeature.Upper = suppressWarnings(as.numeric(table_col(samples, "nfeature_upper"))),
      Filter.Mode = table_col(samples, "filter_mode"),
      stringsAsFactors = FALSE
    )
  })

  rows <- rows[!vapply(rows, is.null, logical(1))]
  if (length(rows) == 0) return(data.frame())

  df <- clean_report_table(do.call(rbind, rows))
  drop_all_missing_columns(
    df,
    keep = c("Sample", "MT.Cutoff", "nFeature.Lower", "nFeature.Upper", "Filter.Mode")
  )
}

render_samples_table <- function(summary_obj) {
  if (is.null(summary_obj) || is.null(summary_obj$samples) || length(summary_obj$samples) == 0) return(data.frame())
  as_table_rows(summary_obj$samples)
}

render_artifacts_table <- function(summary_obj) {
  if (!exists("artifact_table")) return(data.frame())
  artifact_table(summary_obj)
}

render_steps_table <- function(manifest) {
  if (is.null(manifest$steps)) return(data.frame())
  steps <- as_table_rows(manifest$steps)
  if (nrow(steps) == 0) return(data.frame())
  steps[, intersect(c("step", "status", "summary"), colnames(steps)), drop = FALSE]
}

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x
