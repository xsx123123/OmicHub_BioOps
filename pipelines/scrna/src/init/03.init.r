# scripts/Command_scripts/init.r

#' Initialize Pipeline Context
#' 
#' @description Determines the pipeline root directory and sets global constants.
#' @param logger Optional. A log4r logger object.
#' @return A list containing PIPELINE_PATH, YAML_PATH, and VERSION.
initialize_pipeline_context <- function(logger = NULL,
                                        app_name = NULL,
                                        YAML_PATH = NULL,
                                        description = NULL,
                                        ScriptsVersion = NULL) {
  
  # cat command to print the pipeline header
  cat('\n')
  # print appname & logo
  show_random_logo(version = ScriptsVersion,
                   app_name = app_name,
                   description = description)

  debug(logger,crayon::blue(crayon::bold('>>> scRNA-seq Pipeline Initialization <<<')))

  # Robustly determine the script's directory
  initial_options <- commandArgs(trailingOnly = FALSE)
  file_arg_name <- "--file="
  script_name <- sub(file_arg_name, "", initial_options[grep(file_arg_name, initial_options)])
  
  if (length(script_name) > 0) {
    # If run via Rscript
    PIPELINE_PATH <- dirname(normalizePath(script_name))
  } else {
    # Fallback: check if we are in an interactive session or sourced
    PIPELINE_PATH <- getwd()
  }

  # Log info if logger is provided
  if (!is.null(logger)) {
    if(requireNamespace("crayon", quietly = TRUE)) {
       debug(logger, paste0(crayon::cyan('Pipeline Version : ',ScriptsVersion)))
       debug(logger, paste0(crayon::cyan('Pipeline ROOT    : ',PIPELINE_PATH)))
       debug(logger, paste0(crayon::cyan('Config PATH      : ',paste0("<PIPELINE_PATH>/", YAML_PATH))))
    } else {
       debug(logger, paste0('Pipeline Version : ',ScriptsVersion))
       debug(logger, paste0('Pipeline ROOT    : ',PIPELINE_PATH))
       debug(logger, paste0('Config PATH      : ',paste0("<PIPELINE_PATH>/", YAML_PATH)))
    }
  }

  debug(logger,crayon::blue(crayon::bold('>>> -seq Pipeline Initialization <<<')))

  return(list(
    PIPELINE_PATH = PIPELINE_PATH,
    YAML_PATH = YAML_PATH,
    VERSION = ScriptsVersion
  ))
}
# ==============================================================================
# END 
# ==============================================================================
