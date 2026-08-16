# ============================================================================== 
# Parameter Review Functions for scRNA-seq Analysis Pipeline 
# Description: Functions to summarize and display the current runtime parameters 
#              and sample information. These functions facilitate a final check 
#              before the computationally expensive analysis begins. 
# Dependencies: This script assumes specific configuration variables (e.g., 
#               root_dir, project_name) are already loaded in the global environment. 
# ============================================================================== 

# ============================================================================== 
# Function: get_run_parameter 
# Description: Aggregates and prints key analysis parameters and sample information. 
#              Intended for automated or non-interactive logging. 
# Global Variables Accessed: 
#   root_dir, input_data_scRNA_seq_dir_name, project_name, scRNAAutofilted, 
#   nFeature_RNA_cutoff_1, nFeature_RNA_cutoff_2, threads, infor, list 
# ============================================================================== 
get_run_parameter <- function(){ 
  # Create a summary dataframe of parameters 
  # Using checks to prevent crashing if variables are missing 
  param_values <- c( 
    if(exists("root_dir")) root_dir else "NA", 
    if(exists("input_data_scRNA_seq_dir_name")) input_data_scRNA_seq_dir_name else "NA", 
    if(exists("project_name")) project_name else "NA", 
    if(exists("scRNAAutofilted")) scRNAAutofilted else "NA", 
    if(exists("nFeature_RNA_cutoff_1")) nFeature_RNA_cutoff_1 else "NA", 
    if(exists("nFeature_RNA_cutoff_2")) nFeature_RNA_cutoff_2 else "NA", 
    if(exists("threads")) threads else "NA" 
  ) 

  run_parameter <- data.frame( 
    Description = c( 
      "scRNA-seq analysis root_dir", 
      "scRNA-seq analysis save_dir", 
      "scRNA-seq analysis project_name", 
      "scRNA-seq analysis on autofited scRNA-seq data", 
      "scRNA-seq analysis raw data cutoff-1", 
      "scRNA-seq analysis raw data cutoff-2", 
      "Weather use multithreading" 
    ), 
    Value = param_values, 
    stringsAsFactors = FALSE 
  ) 
  
  # Display Parameters 
  print_color_note_UP("Please check run parameters!!!") 
  print(run_parameter) 
  print_color_note_DOWN("Please check run parameters!!!") 
  
  cat("\n") 
  if(exists("ProgressBar")) ProgressBar() 
  cat("\n") 
  
  # Process and Display Sample Information 
  if(exists("infor") && exists("list")){ 
    print_color_note_UP("Please check sample info !!!") 
    
    # Extract sample name from path: keeps the folder name immediately preceding '/Count/' 
    infor$name <- sub(".*/([^/]+)/Count/", "\\1/", list) 
    print(infor) 
    
    print_color_note_DOWN("Please check sample info !!!") 
  } else { 
    if(exists("logger")) warn(logger, "Variable 'infor' or 'list' not found. Skipping sample info display.") 
  } 
} 

# ============================================================================== 
# Function: get_run_parameterDev 
# Description: Similar to get_run_parameter but includes interactive prompts. 
#              Pauses execution and requires user confirmation ("YES") to proceed. 
# Global Variables Accessed: 
#   root_dir, input_data_scRNA_seq_dir_name, project_name, auto_set_filted_setting, 
#   nFeature_RNA_cutoff_1, nFeature_RNA_cutoff_2, percent.mt_cutoff, threads, infor, list 
# ============================================================================== 
get_run_parameterDev <- function(){ 
  # create summary dataframe 
  param_values <- c( 
    if(exists("root_dir")) root_dir else "NA", 
    if(exists("input_data_scRNA_seq_dir_name")) input_data_scRNA_seq_dir_name else "NA", 
    if(exists("project_name")) project_name else "NA", 
    if(exists("auto_set_filted_setting")) auto_set_filted_setting else "NA", 
    if(exists("nFeature_RNA_cutoff_1")) nFeature_RNA_cutoff_1 else "NA", 
    if(exists("nFeature_RNA_cutoff_2")) nFeature_RNA_cutoff_2 else "NA", 
    if(exists("percent.mt_cutoff")) percent.mt_cutoff else "NA", 
    if(exists("threads")) threads else "NA" 
  ) 

  run_parameter <- data.frame( 
    Description = c( 
      "scRNA-seq analysis root_dir", 
      "scRNA-seq analysis save_dir", 
      "scRNA-seq analysis project_name", 
      "scRNA-seq analysis on autofited scRNA-seq data", 
      "scRNA-seq analysis raw data cutoff-1", 
      "scRNA-seq analysis raw data cutoff-2", 
      "scRNA-seq analysis raw data cutoff-3", 
      "Weather use multithreading" 
    ), 
    Value = param_values, 
    stringsAsFactors = FALSE 
  ) 

  # --- Step 1: Check Parameters --- 
  print_color_note_UP("Please check run parameters!!!") 
  print(run_parameter) 
  print_color_note_DOWN("Please check run parameters!!!") 
  
  cat("\n") 
  if(exists("ProgressBar")) ProgressBar() 
  cat("\n") 
  
  # User Interaction 1 
  if (interactive()) { 
    response <- readline(prompt = paste0(bold(cyan("? Do these parameters look correct? Enter YES to continue: ")))) 
    if (toupper(trimws(response)) != "YES") { 
      cat(red("✖ User did not enter YES. Aborting execution.\n")) 
      stop("Pipeline aborted by user at parameter check.") 
    } 
    cat(green("✔ Proceeding...\n")) 
  } 

  # --- Step 2: Check Sample Info --- 
  if(exists("infor") && exists("list")){ 
    print_color_note_UP("Please check sample info !!!") 
    
    # Extract sample name logic 
    infor$cellRanger <- sub(".*/([^/]+)/Count/", "\\1/", list) 
    print(infor) 
    
    print_color_note_DOWN("Please check sample info !!!") 
    
    # User Interaction 2 
    if (interactive()) { 
      response <- readline(prompt = paste0(bold(cyan("? Does the sample info look correct? Enter YES to continue: ")))) 
      if (toupper(trimws(response)) != "YES") { 
        cat(red("✖ User did not enter YES. Aborting execution.\n")) 
        stop("Pipeline aborted by user at sample info check.") 
      } 
      cat(green("✔ All checks passed. Starting analysis...\n")) 
    } 
  } else { 
     if(exists("logger")) warn(logger, "Variable 'infor' or 'list' not found. Skipping sample info check.") 
  } 
}
# ==============================================================================
# END 
# ==============================================================================