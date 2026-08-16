# ==============================================================================
# load_seurat.R
# Description: Safely loads Seurat objects saved by the pipeline.
# ==============================================================================

load_seurat <- function(result_dir, rel_path) {
  obj_path <- file.path(result_dir, rel_path)
  if (!file.exists(obj_path)) return(NULL)
  ext <- tools::file_ext(obj_path)
  switch(ext,
    "qs" = qs::qread(obj_path),
    "rds" = readRDS(obj_path),
    stop("Unsupported object format: ", ext)
  )
}
