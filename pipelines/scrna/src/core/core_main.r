#-----------------------------------####---------------------------------------#
# Author      :  JZHANG
# Date        :  2025-12-19
#-----------------------------------####---------------------------------------#
# PATH-1 : loading function
# loading help function
source(file.path(PIPELINE_PATH,'src/core/00.help_function.r'))
# loading parameter function
source(file.path(PIPELINE_PATH,'src/core/01.parameter.r'))
# loading cell qc function
source(file.path(PIPELINE_PATH,'src/core/02.cells_qc.r'))
# loading AmbientRNA function
source(file.path(PIPELINE_PATH,'src/core/03.AmbientRNA.r'))
# loading Checkdoublet function
source(file.path(PIPELINE_PATH,'src/core/04.Checkdoublet.r'))
# loading NormalFeature & AutoPCA function
source(file.path(PIPELINE_PATH,'src/core/05.Normal_PCA.r'))
# loading merge & interget function
source(file.path(PIPELINE_PATH,'src/core/06.Merge_integer.r'))
# loading DEG function
source(file.path(PIPELINE_PATH,'src/core/07.DEG.r'))
source(file.path(PIPELINE_PATH,'src/core/07.FindClusterMarkersDotplot.r'))
# loading annotation function
source(file.path(PIPELINE_PATH,'src/core/08.obj_subset.r'))
# loading annotation function
source(file.path(PIPELINE_PATH,'src/core/10.annotation.r'))
# loading single sample analysis function
source(file.path(PIPELINE_PATH,'src/core/11.single_sample.r'))
# loading multi sample analysis function 
source(file.path(PIPELINE_PATH,'src/core/12.multisample.r'))
# loading report manifest generator
source(file.path(PIPELINE_PATH,'src/core/99.report_manifest.r'))
#-----------------------------------####---------------------------------------#
# loading visualization function
source(file.path(PIPELINE_PATH,'src/viz/01.vis_dim_reduction.r'))
source(file.path(PIPELINE_PATH,'src/viz/02.vis_annotation.r'))
source(file.path(PIPELINE_PATH,'src/viz/03.vis_proportions.r'))
source(file.path(PIPELINE_PATH,'src/viz/04.vis_expression.r'))
source(file.path(PIPELINE_PATH,'src/viz/05.vis_qc_spatial.r'))
source(file.path(PIPELINE_PATH,'src/viz/06.vis_data_export.r'))
#-----------------------------------####---------------------------------------#
# loading RDS export function
source(file.path(PIPELINE_PATH,'src/core/13.rds_export.r'))
#-----------------------------------####---------------------------------------#
# --- MAIN FUNCTIONS --- #
Check_sample <- function(cellRangerlist, ctx){

  # Check input type
  if (!is.data.frame(cellRangerlist) && !is.matrix(cellRangerlist)) {
    stop("cellRangerlist must be a data.frame or matrix.")
  }
  debug(logger,crayon::bold('Check scRNA-seq pipeline cellRangerlist type '))

  # get scRNA-seq samples count
  n_samples <- nrow(cellRangerlist)
  debug(logger,crayon::blue(crayon::bold(paste0('scRNA-seq pipeline analysis samples count :',n_samples))))

  # Multi-sample analysis
  if (n_samples > 1) {
    info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
    # info(logger,crayon::yellow(crayon::bold('---------------------------------------------')))
    # info(logger,crayon::yellow(crayon::bold('-               CORE FUNCTION               -')))
    # info(logger,crayon::yellow(crayon::bold('---------------------------------------------')))
    info(logger,crayon::bold(crayon::inverse(">>> STEP 7 : Multi Sample scRNA-seq Analysis")))
    # info(logger, paste0(crayon::bgGreen('Multi Sample scRNA-seq Analysis DO')))
    multisample_scRNA_seq_analysis(ctx)
  } else {
    # Single-sample analysis
    info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
    # info(logger,crayon::yellow(crayon::bold('---------------------------------------------')))
    # info(logger,crayon::yellow(crayon::bold('-               CORE FUNCTION               -')))
    # info(logger,crayon::yellow(crayon::bold('---------------------------------------------')))
    info(logger,crayon::bold(crayon::inverse(">>> STEP 7 : Single Sample scRNA-seq Analysis")))
    # info(logger, paste0(crayon::bgGreen('Single Sample scRNA-seq Analysis DO')))
    # Validate `infor` (Using ctx$infor if available, falling back to global for safety if needed)
    infor_obj <- if(!is.null(ctx$infor)) ctx$infor else get("infor", envir = .GlobalEnv)
    
    if (!is.list(infor_obj) || !"infor" %in% names(infor_obj)) {
      stop("The variable `infor` must exist and contain an element named `infor`.")
    }

    name <- infor_obj$infor
    scRNAtype <- infor_obj$library_type
    info(logger, paste0(crayon::bgGreen(paste0('scRNA-seq pipelie analysis : ',name))))
    
    # Clean up directories if they exist
    # Accessing directories via ctx
    if (dir.exists(ctx$BatchCheck_dir)) {
      unlink(ctx$BatchCheck_dir, recursive = TRUE)
    }
    if (dir.exists(ctx$DealPatch_dir)) {
      unlink(ctx$DealPatch_dir, recursive = TRUE)
    }
    # Call single-sample analysis function
    singlesample_scRNA_seq_analysis(scRNAtype, name, ctx$reduceType, ctx)
  }
}
# ==============================================================================
# END 
# ==============================================================================
