Seurat2h5ad <- function(Seurat_obj = NULL,
                        project_name = NULL,
                        save_dir = NULL,
                        assay_to_use = "RNA",
                        logger = NULL){

  log_info <- function(msg) {
    if (!is.null(logger) && requireNamespace("log4r", quietly = TRUE)) {
      log4r::info(logger, msg)
    } else {
      message(paste0("[INFO] ", msg))
    }
  }

  log_info('  Loading packages for Seurat to h5ad conversion...')
  if (!requireNamespace("SingleCellExperiment", quietly = TRUE)) stop("Please install SingleCellExperiment!")
  if (!requireNamespace("zellkonverter", quietly = TRUE)) stop("Please install zellkonverter!")

  current_layers <- Layers(Seurat_obj, assay = assay_to_use)
  is_split <- any(grepl("\\.", current_layers))
  
  if (is_split) {
    log_info(paste0('  Detected split layers in assay ', assay_to_use, '. Running JoinLayers...'))
    Seurat_obj <- JoinLayers(Seurat_obj, assay = assay_to_use)
  }

  log_info(paste0('  Converting Seurat Assay "', assay_to_use, '" to SingleCellExperiment...'))
  
  DefaultAssay(Seurat_obj) <- assay_to_use
  sce <- as.SingleCellExperiment(Seurat_obj, assay = assay_to_use)

  output_file <- file.path(save_dir, paste0(project_name, '_Seurat_2_anndata.h5ad'))
  log_info(paste0('  Writing h5ad file to: ', output_file))
  
  tryCatch({
    zellkonverter::writeH5AD(sce, file = output_file)
    log_info('  Conversion completed successfully!')
  }, error = function(e) {
    log_info(paste0('  Error during writeH5AD: ', e$message))
    stop(e)
  })
}
#-----------------------------------####---------------------------------------#
# END
#-----------------------------------####---------------------------------------#