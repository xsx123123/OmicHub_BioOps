# ==============================================================================
# plot_helpers.R
# Description: Common plotting helpers for the Quarto report.
# ==============================================================================

artifact_table <- function(summary_obj, types = NULL, path_pattern = NULL) {
  if (is.null(summary_obj) || is.null(summary_obj$artifacts) || length(summary_obj$artifacts) == 0) {
    return(data.frame())
  }
  artifacts <- summary_obj$artifacts
  if (is.data.frame(artifacts)) {
    df <- artifacts
  } else {
    df <- do.call(rbind, lapply(artifacts, as.data.frame, stringsAsFactors = FALSE))
  }
  if (!is.null(types) && "type" %in% colnames(df)) {
    df <- df[tolower(df$type) %in% tolower(types), , drop = FALSE]
  }
  if (!is.null(path_pattern) && "path" %in% colnames(df)) {
    df <- df[grepl(path_pattern, df$path, ignore.case = TRUE), , drop = FALSE]
  }
  rownames(df) <- NULL
  df
}

find_artifact <- function(summary_obj, type = NULL, path_pattern = NULL) {
  df <- artifact_table(summary_obj, types = type, path_pattern = path_pattern)
  if (nrow(df) == 0) return(NULL)
  df$path[1]
}

find_artifacts <- function(summary_obj, types = NULL, path_pattern = NULL) {
  artifact_table(summary_obj, types = types, path_pattern = path_pattern)
}

artifact_abs_paths <- function(result_dir, artifacts_df) {
  if (is.null(artifacts_df) || nrow(artifacts_df) == 0 || !"path" %in% colnames(artifacts_df)) return(character(0))
  paths <- file.path(result_dir, artifacts_df$path)
  paths[file.exists(paths)]
}

# Display one image file if it exists, otherwise print a placeholder message.
display_image <- function(result_dir, rel_path, caption = NULL) {
  img_path <- file.path(result_dir, rel_path)
  if (!file.exists(img_path)) {
    cat("Image not found: ", rel_path)
    return(invisible(NULL))
  }
  knitr::include_graphics(img_path)
}

# Display all matching image artifacts from a summary object.
display_images <- function(result_dir,
                           summary_obj,
                           path_pattern = NULL,
                           max_images = 12,
                           types = c("png", "jpg", "jpeg", "gif", "svg")) {
  images <- artifact_table(summary_obj, types = types, path_pattern = path_pattern)
  paths <- artifact_abs_paths(result_dir, images)
  if (length(paths) == 0) {
    cat("No matching image artifacts found.")
    return(invisible(NULL))
  }
  paths <- paths[seq_len(min(length(paths), max_images))]
  knitr::include_graphics(paths)
}
