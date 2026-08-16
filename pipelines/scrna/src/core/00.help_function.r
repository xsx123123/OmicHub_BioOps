# ==============================================================================
# Helper Functions for scRNA-seq Analysis Pipeline
# Description: A collection of utility functions for logging, file management, 
#              configuration validation, and visual feedback used throughout the pipeline.
# ==============================================================================

# ==============================================================================
# Function: Check_log_models
# Description: Initializes the log4r logging system with a custom colorful layout.
#              It defines log levels (INFO, WARN, ERROR, FATAL, DEBUG) with specific
#              colors and emojis for better readability in the console.
#              It assigns the 'logger' object to the global environment.
# ==============================================================================
Check_log_models <- function(){
  # Ensure dependencies are loaded
  if(!require(log4r, quietly = TRUE)) library(log4r)
  if(!require(crayon, quietly = TRUE)) library(crayon)
  if(!require(stringr, quietly = TRUE)) library(stringr)
  
  if (exists("logger") && inherits(logger, "logger")) {
    cat(green("✔ The logger object exists and is ready.\n"))
  } else {
    cat(yellow("ℹ The logger object doesn't exist. Loading log4r models...\n"))
    
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
# Function: checkscRNAConf
# Description: Validates the configuration dataframe for scRNA-seq analysis.
#              1. Checks if required columns (CellRanger, name, group) exist.
#              2. Verifies that the specified CellRanger paths actually exist.
# Parameters:
#   cellRangerlist: A dataframe containing the experiment configuration.
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
# Description: Retrieves the global 'width_print' variable if it exists,
#              otherwise returns a default width of 100.
# ==============================================================================
.get_print_width <- function() {
  if (exists("width_print") && !is.na(get("width_print"))) {
    return(get("width_print"))
  }
  return(100)
}

# ==============================================================================
# Internal Helper: .print_styled_banner
# Description: A generic function to print stylized ASCII banners with consistent
#              padding and colors. Used by print_color_note_* functions.
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
# Description: Prints a 'START' banner with a happy kaomoji.
#              Used to indicate the beginning of a major process step.
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
# Description: Prints a simple middle divider/header.
#              Used to indicate a sub-step or section break.
# ==============================================================================
print_color_note_middle <- function(logo){
  w <- .get_print_width()
  cat("\n")
  cat(bold(blue(str_pad(paste0("── ", logo, " ──"), width=w, pad = " ", side = "both"))), " \n")
  cat("\n")
}

# ==============================================================================
# Function: print_color_note_DOWN
# Description: Prints a 'DONE' banner with a satisfied kaomoji.
#              Used to indicate the successful completion of a major process step.
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
# Function: print_color_note_warring (Legacy naming)
# Description: Prints a high-visibility WARNING banner with red background.
#              Used to alert the user of potential issues or important notices.
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
# Description: Prints a 'NOTE' banner for informational messages.
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
# Description: A generic alias for 'print_color_note_UP'.
# ==============================================================================
print_color_note <- function(logo){
  print_color_note_UP(logo)
}

# ==============================================================================
# Function: CheckPackage
# Description: Checks if a list of R packages are installed.
#              Logs success if all are present, or stops execution with a 
#              warning banner if any are missing.
# Parameters:
#   needlist: A vector of package names to check.
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
# Description: Sanitizes directory paths. Specifically handles relative paths
#              starting with "./" by converting them to absolute paths using the
#              current working directory.
# Parameters:
#   path_dir: The path string to check.
# Returns: The sanitized absolute path string.
# ==============================================================================
check_path <- function(path_dir){
  if(grepl("^\\./", path_dir)){
    # Remove the dot and cleanly join with current working directory
    # substring(path_dir, 3) extracts string starting from 3rd char (after "./")
    PATH <- file.path(getwd(), substring(path_dir, 3)) 
  } else {
    PATH <- path_dir
  }
  return(PATH)
}

# ==============================================================================
# Function: ProgressBar
# Description: Displays a visual progress bar (10 seconds) to the console.
#              Useful for pacing output or waiting for async processes (simulated).
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
# Function: execute_and_record
# Description: Executes an R expression while capturing and redirecting its 
#              console output (stdout) and messages (stderr) to the logger. 
#              It cleans the output by removing common progress bars, dividers,
#              and empty lines to keep the log file tidy.
# @ expr : The R expression or code block to evaluate.
# @ log_level : The logging level to use for the captured output (default: "DEBUG").
# ==============================================================================
execute_and_record <- function(expr, log_level = "DEBUG") {
  # 1. Prepare temporary file
  temp_f <- tempfile()
  
  # 2. Open a file connection for writing text
  con <- file(temp_f, open = "wt")
  
  # 3. Direct both output and message to the connection object
  # split=FALSE ensures output is NOT mirrored to the console
  sink(con, type = "output")
  sink(con, type = "message")
  
  # 4. Register cleanup mechanism on exit
  on.exit({
    # A. Stop sinking output and messages
    sink(type = "message")
    sink(type = "output")
    
    # B. Close the file connection to release the file
    close(con)
    
    # C. Read and clean the captured logs
    if (file.exists(temp_f)) {
      captured_lines <- readLines(temp_f, warn = FALSE)
      
      # Filter rules: remove progress bars, separators, and empty lines
      clean_lines <- captured_lines[
        !grepl("^\\s*\\d+%.*\\d+%", captured_lines) &  # Filter "10%... 20%" patterns
        !grepl("\\[-+\\|-+\\]", captured_lines) &      # Filter progress bars [---|---]
        !grepl("^\\*+$", captured_lines) &              # Filter divider lines *******
        nchar(trimws(captured_lines)) > 0               # Filter empty or whitespace-only lines
      ]
      
      # D. Log the cleaned lines
      if (length(clean_lines) > 0 && exists("logger")) {
        log_msg <- paste0("TOOL_LOG >> ", clean_lines)
        if (log_level == "INFO") {
          lapply(log_msg, function(x) info(logger, x))
        } else {
          lapply(log_msg, function(x) debug(logger, x))
        }
      }
      
      # E. Remove the temporary file
      unlink(temp_f)
    }
  })
  
  # 5. Execute the expression
  result <- expr
  return(result)
}

# ==============================================================================
# Function: CreateNewSeurat
# Description: Creates a new Seurat object from an existing one, specifically 
#              extracting the raw counts and metadata. This is often used to 
#              "clean" or reset a Seurat object while preserving essential info.
# @ data : The source Seurat object.
# ==============================================================================
CreateNewSeurat <- function(data){
  if(exists("logger")) debug(logger, "Creating a new Seurat object from existing data...")
  cellinfo <- data@meta.data
  if(exists("logger")) debug(logger, paste0("Extracted metadata for ", nrow(cellinfo), " cells."))
  
  new_data <- CreateSeuratObject(counts = data@assays$RNA$counts, meta.data = cellinfo)
  if(exists("logger")) debug(logger, "New Seurat object successfully created.")
  
  return(new_data)
}

# ==============================================================================
# Function: StatCellCluster
# Description: Extracts clustering information (original identity, cluster ID, 
#              contamination score) from a Seurat object and saves it as a CSV file.
# Parameters:
#   data: A Seurat object containing metadata.
#   output_dir: The directory where the CSV file will be saved.
# ==============================================================================
StatCellCluster <- function(data, output_dir){
  # Ensure dplyr is available
  if(!require(dplyr, quietly = TRUE)) library(dplyr)
  
  if (!dir.exists(output_dir)) dir.create(output_dir, recursive = TRUE)
  
  Integr_cell_cluster <- data@meta.data |> dplyr::select(orig.ident, any_of(c("unintegrated_clusters", "Contamination")))
  write.csv(Integr_cell_cluster, file.path(output_dir, "Cell-cluster-infor.csv"))
}
# ==============================================================================
# END 
# ==============================================================================