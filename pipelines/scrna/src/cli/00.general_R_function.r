# ==============================================================================
# Helper Functions for scRNA-seq Analysis Pipeline
# Source: 00.help_function.r (Unified)
# Description: A collection of utility functions for logging, file management, 
#              configuration validation, and visual feedback used throughout the pipeline.
# ==============================================================================

# ==============================================================================
# Function: Check_log_models
# Description: Initializes the log4r logging system with a custom colorful layout.
# ==============================================================================
Check_log_models <- function(){
  # Ensure dependencies are loaded
  if(!require(log4r, quietly = TRUE)) library(log4r)
  if(!require(crayon, quietly = TRUE)) library(crayon)
  if(!require(stringr, quietly = TRUE)) library(stringr)
  
  if (exists("logger") && inherits(logger, "logger")) {
    cat(green("✔ The logger object exists and is ready.
"))
  } else {
    cat(yellow("ℹ The logger object doesn't exist. Loading log4r models...
"))
    
    # Beautified layout function for log messages
    my_layout <- function(level, ...) {
      ts <- make_style("gray60")(format(Sys.time(), "%H:%M:%S"))
      msg <- paste0(..., collapse = "")
      
      if (level == 'INFO'){
        paste0(ts, " ", bold(cyan("ℹ️  INFO ")), "  ", msg, "\n")
      } else if (level == 'WARN'){
        paste0(ts, " ", bold(yellow("⚠️  WARN ")), "  ", msg, "\n")
      } else if (level == 'ERROR'){
        paste0(ts, " ", bold(red("❌ ERROR")), "  ", msg, "\n")
      } else if (level == 'FATAL'){
        paste0(ts, " ", bold(bgRed(white("💀 FATAL"))), "  ", msg, "\n")
      } else if (level == 'DEBUG'){
        paste0(ts, " ", bold(blue("🐛 DEBUG")), "  ", msg, "\n")
      } else {
        paste0(ts, " [", level, "] ", msg, "\n")
      }
    }
    
    # Assign to global environment to ensure it persists across function calls
    assign("logger", log4r::logger(threshold = "INFO", appenders = list(console_appender(my_layout))), envir = .GlobalEnv)
  }
}

# ==============================================================================
# Function: create_dir
# Description: Iterates through a list of directory paths. Checks if each directory
#              exists; if not, creates it recursively.
# ==============================================================================
create_dir <- function(list_dir){
  for (i in list_dir) {
    if(!dir.exists(i)){
      dir.create(i, recursive = TRUE, showWarnings = FALSE)
      if(exists("logger") && inherits(logger, "logger")) info(logger, paste("Created directory:", i))
    }
  }
}

# ==============================================================================
# Function: checkscRNAConf
# Description: Validates the configuration dataframe for scRNA-seq analysis.
# ==============================================================================
checkscRNAConf <- function(cellRangerlist){
  # Check required column names
  required_cols <- c("CellRanger", "name", "group", "library_type")
  if (all(required_cols %in% colnames(cellRangerlist))){
    if(exists("logger")) info(logger, 'scRNAseq CONF colnames check passed.')
  } else {
    if(exists("logger")) error(logger, 'Please check scRNAseq CONF colnames!')
    stop("Missing columns in configuration: ", paste(setdiff(required_cols, colnames(cellRangerlist)), collapse=", "))
  }
  
  # Validate library_type values
  valid_library_types <- c("DNBC4", "10x")
  invalid_types <- cellRangerlist$library_type[!cellRangerlist$library_type %in% valid_library_types]
  if (length(invalid_types) > 0) {
    if(exists("logger")) error(logger, paste('Invalid library_type values found:', paste(unique(invalid_types), collapse=", ")))
    stop("Invalid library_type values. Must be one of: ", paste(valid_library_types, collapse=" | "))
  }
  
  # Check if CellRanger paths exist
  missing_files <- c()
  for (i in cellRangerlist$CellRanger){
    if (!dir.exists(i) && !file.exists(i)){
      missing_files <- c(missing_files, i)
    }
  }
  
  if(length(missing_files) > 0){
    if(exists("logger")) error(logger, paste("Cell feature matrix Path not found:", head(missing_files, 1), "..."))
    stop("Paths not found:\n", paste(missing_files, collapse="\n"))
  }
}

# ==============================================================================
# Internal Helper: .get_print_width
# ==============================================================================
.get_print_width <- function() {
  if (exists("width_print") && !is.na(get("width_print"))) {
    return(get("width_print"))
  }
  return(100)
}

# ==============================================================================
# Internal Helper: .print_styled_banner
# ==============================================================================
.print_styled_banner <- function(logo, style_top, style_bottom, color_func) {
  w <- .get_print_width()
  
  # Ensure styles fit width
  line_top <- str_pad(style_top, width=w, pad = "─", side = "both")
  line_bottom <- str_pad(style_bottom, width=w, pad = "─", side = "both")
  
  cat("\n")
  cat(bold(color_func(line_top)), " \n")
  cat("\n")
  cat(bold(str_pad(logo, width=w, pad = " ", side = "both")), " \n")
  cat("\n")
  if (!is.null(style_bottom)) {
    cat(bold(color_func(line_bottom)), " \n")
  }
  cat("\n")
}

# ==============================================================================
# Function: print_color_note_UP
# ==============================================================================
print_color_note_UP <- function(logo){
  .print_styled_banner(
    logo = logo,
    style_top = " (●´∀｀●)ﾉ START ",
    style_bottom = NULL,
    color_func = cyan
  )
}

# ==============================================================================
# Function: print_color_note_middle
# ==============================================================================
print_color_note_middle <- function(logo){
  w <- .get_print_width()
  cat("\n")
  cat(bold(blue(str_pad(paste0("── ", logo, " ──"), width=w, pad = " ", side = "both"))), " \n")
  cat("\n")
}

# ==============================================================================
# Function: print_color_note_DOWN
# ==============================================================================
print_color_note_DOWN <- function(logo){
  .print_styled_banner(
    logo = logo,
    style_top = NULL,
    style_bottom = " (￣▽￣)~* DONE ",
    color_func = green
  )
}

# ==============================================================================
# Function: print_color_note_warring
# ==============================================================================
print_color_note_warring <- function(logo){
  w <- .get_print_width()
  logo_style <- " (σ｀д′)σ WARNING "
  
  padded_line <- str_pad(logo_style, width=w, pad = "!", side = "both")
  
  cat("\n")
  cat(bold(bgRed(white(padded_line))), " \n")
  cat("\n")
  cat(bold(red(str_pad(logo, width=w, pad = " ", side = "both"))), " \n")
  cat("\n")
  cat(bold(bgRed(white(padded_line))), " \n")
}

# ==============================================================================
# Function: print_color_note_NOTE
# ==============================================================================
print_color_note_NOTE <- function(logo){
  .print_styled_banner(
    logo = logo,
    style_top = " ✎ NOTE ",
    style_bottom = " ────── ",
    color_func = magenta
  )
}

# ==============================================================================
# Function: print_color_note
# ==============================================================================
print_color_note <- function(logo){
  print_color_note_UP(logo)
}

# ==============================================================================
# Function: CheckPackage
# ==============================================================================
CheckPackage <- function(needlist){
  packagelist <- installed.packages()[, "Package"]
  missing_pkg <- needlist[!(needlist %in% packagelist)]
  
  if (length(missing_pkg) == 0){
    if(exists("logger")) info(logger, 'All scRNA-seq Analysis dependent packages are installed.')
  } else {
    if(exists("logger")) warn(logger, "Some dependent packages are NOT installed.")
    print_color_note_warring(paste0("Not installed R packages: ", paste(missing_pkg, collapse = ", ")))
    stop("Missing packages: ", paste(missing_pkg, collapse = ", "))
  }
}

# ==============================================================================
# Function: check_path
# ==============================================================================
check_path <- function(path_dir){
  if(grepl("^\\./", path_dir)){
    PATH <- file.path(getwd(), substring(path_dir, 3)) 
  } else {
    PATH <- path_dir
  }
  return(PATH)
}

# ==============================================================================
# Function: ProgressBar
# ==============================================================================
ProgressBar <- function(){
  if(!require(progress, quietly = TRUE)) return()
  
  pb <- progress_bar$new(
    format = '  Waiting [:bar] :percent in :elapsed',
    total = 10, clear = FALSE, width = 80,
    chars = "■□" 
  )
  
  for (i in 1:10) {
    pb$tick()
    Sys.sleep(1)
  }
}

# ==============================================================================
# Function: StatCellCluster
# ==============================================================================
StatCellCluster <- function(data, output_dir) {

  if (!dir.exists(output_dir)) dir.create(output_dir, recursive = TRUE)
  
  info(logger, 'Save Cluster Cells State...')
  
  Integr_cell_cluster <- data@meta.data |> 
    tibble::rownames_to_column(var = "Barcode") |> 
    dplyr::select(
      Barcode,
      orig.ident, 
      dplyr::any_of(c("group", "unintegrated_clusters", "Contamination"))
    )
  
  output_file <- file.path(output_dir, "Cell-cluster-infor.csv")
  
  if (requireNamespace("readr", quietly = TRUE)) {
    readr::write_csv(Integr_cell_cluster, output_file)
  } else {
    write.csv(Integr_cell_cluster, output_file, row.names = FALSE, quote = FALSE)
  }
  
  info(logger, paste0("✅ Saved metadata info to: ", output_file))
  
  return(Integr_cell_cluster) 
}
# ==============================================================================
# END 
# ==============================================================================