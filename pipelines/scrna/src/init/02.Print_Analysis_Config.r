# ==============================================================================
# Function: Print_Analysis_Config
# Description: Prints the parsed configuration in a beautified format.
# ==============================================================================
Print_Analysis_Config <- function(opt) {
  # Print header
  info(logger, "")
  info(logger, bold(cyan("=== Analysis Configuration ===")))
  
  # Ensure logger exists
  if (!exists("logger")) {
     library(log4r)
     logger <- log4r::logger(threshold = "INFO")
  }
  
  # Print configuration with clean formatting
  info(logger, paste0("  Config File          : ", magenta(opt$scRNAseqdataframe)))
  info(logger, paste0("  Output Directory     : ", magenta(opt$outputdir)))
  info(logger, paste0("  Project Name         : ", magenta(opt$projectname)))
  info(logger, paste0("  Taxonomy ID          : ", magenta(opt$origintaxID)))
  info(logger, paste0("  Marker Database      : ", magenta(opt$scRNAref)))
  info(logger, paste0("  Target Organ         : ", magenta(opt$organ)))
  info(logger, paste0("  Annotation Ref       : ", magenta(opt$AnnReference)))
  info(logger, paste0("  Integration Method   : ", magenta(opt$intergetmethods)))
  info(logger, paste0("  Reduce Method (tSNE) : ", magenta(opt$reduceType)))
  info(logger, paste0("  Auto-Filter Cells    : ", magenta(opt$autofiltedcell)))
  info(logger, paste0("  Mito Cutoff          : ", magenta(opt$maxmt)))
  info(logger, paste0("  Min Gene Features    : ", magenta(opt$nFeature_RNA_parameter_min)))
  info(logger, paste0("  Max Gene Features    : ", magenta(opt$nFeature_RNA_parameter_max)))
  info(logger, paste0("  Threads              : ", magenta(opt$threads)))
  info(logger, paste0("  PCA Cutoff           : ", magenta(opt$PCscutoff)))
  
  info(logger, bold(cyan("==============================")))
  info(logger, "")
}
# ==============================================================================
# END 
# ==============================================================================
