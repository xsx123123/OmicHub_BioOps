# ==============================================================================
# scRNA-seq Multi-Sample Command Parser
# Author: zhang jian
# Description: Parses command-line arguments for the multi-sample scRNA-seq pipeline.
#              Validates inputs, sets defaults, and prepares the configuration for downstream analysis.
#              Supports Human (9606), Mouse (10090), and Plant/Other species.
# ==============================================================================

suppressMessages(library("yaml"))
suppressMessages(library("log4r"))
suppressMessages(library("getopt"))
suppressMessages(library("stringr"))
suppressMessages(library("crayon"))
suppressMessages(library("praise"))

# Force enable colors for Rscript execution
options(crayon.enabled = TRUE)

# ==============================================================================
# Function: print_help_message
# Description: Displays a beautified help message with usage examples and color coding.
# ==============================================================================
print_help_message <- function() {
  cat(bold(cyan("\n╔═════════════════════════════════════════════════════════════════════════════╗\n")))
  cat(bold(cyan("║                                                                             ║\n")))
  cat(bold(cyan("║                scRNA-seq Multi-Sample Analysis Pipeline                     ║\n")))
  cat(bold(cyan("║                                                                             ║\n")))
  cat(bold(cyan("╚═════════════════════════════════════════════════════════════════════════════╝\n\n")))
  
  cat(bold(green("Usage:")), "\n")
  cat("  Rscript scRNAseqMulticommand.r -c config.csv -o ./results -n MyProject -I 9606 [options]\n\n")
  
  # Helper function to print aligned options with color
  p_opt <- function(short, long, desc) {
    # 1. Highlight options like (A | B) -> Magenta
    if (grepl("(", desc, fixed = TRUE)) {
      parts <- strsplit(desc, "(", fixed = TRUE)[[1]]
      # parts[1] is text before (, parts[2] is text after (
      if (length(parts) > 1) {
        # We assume the format is always "Description (Options)"
        # So parts[2] contains "Options)"
        # We remove the last character ")" to get options
        opts_part <- parts[2]
        if (grepl(")", opts_part, fixed = TRUE)) {
           opts_clean <- gsub(")", "", opts_part, fixed = TRUE)
           # Reconstruct: "Description " + "(" + Magenta("Options") + ")"
           desc <- paste0(parts[1], "(", magenta(opts_clean), ")")
        }
      }
    }
    
    # 2. Highlight defaults like [Default: X] -> Green
    if (grepl("[Default:", desc, fixed = TRUE)) {
      parts <- strsplit(desc, "[Default:", fixed = TRUE)[[1]]
      if (length(parts) > 1) {
        # parts[1] is text before, parts[2] is " X]"
        def_part <- parts[2]
        if (grepl("]", def_part, fixed = TRUE)) {
           def_clean <- gsub("]", "", def_part, fixed = TRUE)
           # Trim leading space if any
           # Reconstruct: "Prefix " + "[" + Green("Default:" + value) + "]"
           desc <- paste0(parts[1], "[", green(paste0("Default:", def_clean)), "]")
        }
      }
    }

    # Print aligned
    cat(sprintf("  %-5s %-22s %s\n", short, long, desc))
  }

  cat(bold(yellow("Required Parameters:")), "\n")
  p_opt("-c", "--scRNAseqdataframe", "Input sample sheet (.csv/tsv format)")
  p_opt("-o", "--outputdir",    "Output directory path")
  p_opt("-n", "--projectname",  "Project Name / ID")
  p_opt("-I", "--origintaxID",  "Tax ID (Human:9606, Mouse:10090, Plant:3702...)")
  p_opt("-F", "--scRNAref",     "Marker DB (Cellmarker | PanglaoDB | Custom)")
  p_opt("-O", "--organ",        "Target Organ (e.g., Blood, Root, Leaf)")

  cat("\n")
  cat(bold(yellow("Optional Parameters:")), "\n")
  p_opt("-A", "--AnnReference",    "SingleR Ref (HumanPrimaryCellAtla | MouseRNAref | None)")
  p_opt("-i", "--intergetmethods", "Integration (CCA | Harmony | RPCA | SCVI | ALL) [Default: Harmony]")
  p_opt("-a", "--autofiltedcell",  "Auto-filter cells (TRUE | FALSE) [Default: TRUE]")
  p_opt("-r", "--reduceType",      "Use tSNE reduction (TRUE | FALSE) [Default: FALSE]")
  p_opt("-m", "--maxmt",           "Max Mitochondrial % (numeric or 'Auto')")
  p_opt("-L", "--nFeatureRNAmin",  "Min Gene Count [Default: 200]")
  p_opt("-H", "--nFeatureRNAmax",  "Max Gene Count")
  p_opt("-g", "--log",             "Log Level (DEBUG | INFO | WARN | ERROR) [Default: INFO]")
  p_opt("-t", "--threads",         "Use Multithreading (TRUE | FALSE) [Default: TRUE]")
  p_opt("-f", "--PCscutoff",       "PCA Cutoff [Default: 50]")
  p_opt("-y", "--yaml",            "YAML Config [Default: ./scRNAseqMulticommand.yaml]")
  
  cat("\n")
  cat(bold(white("General:")), "\n")
  p_opt("-h", "--help",    "Show this help message")
  p_opt("-v", "--version", "Show script version")
  cat("\n")
}

# ==============================================================================
# Function: scRNAseqmultiSampleCommand
# Description: Main function to parse and validate arguments.
# ==============================================================================
scRNAseqmultiSampleCommand <- function() {
  # Define command line options
  spec <- matrix(
    c(
      "scRNAseqdataframe","c", 2, "character", "Input File",
      "outputdir",       "o", 2, "character", "Output Directory",
      "projectname",     "n", 2, "character", "Project Name",
      "origintaxID",     "I", 2, "numeric",   "Tax ID",
      "scRNAref",        "F", 2, "character", "Marker Database",
      "organ",           "O", 2, "character", "Organ",
      "AnnReference",    "A", 1, "character", "SingleR Reference",
      "reduceType",      "r", 1, "character", "Reduce Method",
      "autofiltedcell",  "a", 1, "logical",   "Auto Filter",
      "intergetmethods", "i", 1, "character", "Integration Method",
      "maxmt",           "m", 1, "numeric",   "Max Mito %",
      "nFeatureRNAmin",  "L", 1, "numeric",   "Min Features",
      "log",             "g", 1, "character",   "log level",
      "nFeatureRNAmax",  "H", 1, "numeric",   "Max Features",
      "threads",         "t", 1, "logical",   "Threads",
      "PCscutoff",       "f", 1, "numeric",   "PCA Cutoff",
      "yaml",            "y", 1, "character", "YAML Config",
      "help",            "h", 0, "logical",   "Help",
      "version",         "v", 0, "logical",   "Version"
    ),
    byrow = TRUE, ncol = 5
  )
  
  opt <- getopt(spec = spec)
  
  # Handle Help and Version
  if (length(opt) == 0 || !is.null(opt$help)) {
    print_help_message()
    quit(status = 0)
  }
  
  if (!is.null(opt$version)) {
    # Assuming ScriptsVersion is defined globally or we define a default here
    v_str <- if(exists("ScriptsVersion")) ScriptsVersion else "v2.0"
    cat(bold(blue(paste0("scRNAseqMulticommand Version: ", v_str, "\n"))))
    quit(status = 0)
  }
  
  # Check Mandatory Parameters
  required_params <- c("scRNAseqdataframe", "outputdir", "projectname", "origintaxID", "scRNAref", "organ")
  missing_params <- required_params[!required_params %in% names(opt)]
  
  if (length(missing_params) > 0) {
    cat(bold(red("\nError: Missing required parameters:\n")))
    for (p in missing_params) {
      cat(red(paste0("  - ", p, "\n")))
    }
    cat(yellow("\nRun with --help for usage details.\n"))
    quit(status = 1)
  }
  
  # --- Set Defaults & Logic ---
  
  # Auto-filter settings
  if (is.null(opt$autofiltedcell)) opt$autofiltedcell <- TRUE
  
  if (opt$autofiltedcell) {
    opt$maxmt <- "Auto-filtered"
    opt$nFeature_RNA_parameter_min <- 200
    opt$nFeature_RNA_parameter_max <- "Auto-filtered"
  } else {
    # If not auto-filtered, ensure user inputs are preserved or set reasonable fallbacks
    opt$maxmt <- if(!is.null(opt$maxmt)) opt$maxmt else 10  # Default 10% if not specified
    opt$nFeature_RNA_parameter_min <- if(!is.null(opt$nFeatureRNAmin)) opt$nFeatureRNAmin else 200
    opt$nFeature_RNA_parameter_max <- if(!is.null(opt$nFeatureRNAmax)) opt$nFeatureRNAmax else 10000 # High cap default
  }
  
  if (is.null(opt$threads)) opt$threads <- TRUE
  if (is.null(opt$reduceType)) opt$reduceType <- "FALSE"
  if (is.null(opt$PCscutoff)) opt$PCscutoff <- 50
  if (is.null(opt$intergetmethods)) opt$intergetmethods <- 'Harmony'
  if (is.null(opt$yaml)) opt$yaml <- './scRNAseqMulticommand.yaml'
  if (is.null(opt$log)) opt$log <- 'INFO'
  
  # Smart SingleR Reference Default
  if (is.null(opt$AnnReference)) {
    if (opt$origintaxID == 9606) {
      opt$AnnReference <- 'HumanPrimaryCellAtla'
    } else if (opt$origintaxID == 10090) {
      opt$AnnReference <- 'MouseRNAref'
    } else {
      # For plants or other species, default to None or Custom
      opt$AnnReference <- 'None'
    }
  }

  return(opt)
}

# ==============================================================================
# Function: Getspecies
# Description: Maps Taxonomy ID to species abbreviation.
#              Enhanced to support broader species classification.
# ==============================================================================
Getspecies <- function(origin_tax_ID){
  if (origin_tax_ID == 10090){
    species <- "Mm"  # Mouse
  } else if (origin_tax_ID == 9606){
    species <- "Hs"  # Human
  } else {
    # Default for Plants/Others
    species <- "Other" 
  }
  return(species)
}

# ==============================================================================
# Function: Check_input_parameter
# Description: Validates the consistency and correctness of input parameters.
#              Adaptable for non-model organisms (plants).
# ==============================================================================
Check_input_parameter <- function(origintaxID, scRNAref, intergetmethods, AnnReference, reduceType){
  
  info(logger, "")
  info(logger, "Validating analysis parameters...")
  log_divider(logger)

  # 2. Validate Taxonomy ID (Soft Check for flexibility)
  if (!origintaxID %in% c(10090, 9606)){
    warn(logger, paste0('TaxID ', origintaxID, ' is not Human(9606) or Mouse(10090). Assuming Plant or Custom species. Some automated annotations may be skipped.'))
  }
  info(logger, paste0('Taxonomy ID          : ', green(origintaxID)))

  # 3. Validate Marker Database
  # Added "Custom" option for plants/others
  valid_refs <- c("Cellmarker", "PanglaoDB", "Custom")
  if (!scRNAref %in% valid_refs){
    error(logger, paste0('Invalid Marker DB: ', scRNAref, '. Expected: ', paste(valid_refs, collapse=" | ")))
    stop("Parameter Check Failed")
  }
  info(logger, paste0('Marker Database      : ', green(scRNAref)))

  # 4. Validate SingleR Reference
  human_refs <- c("HuamnBlueprintEncode", "HumanDICEImmuneCell", "HumanMonacoImmune", "HumanNovershternHematopoietic", "HumanPrimaryCellAtla")
  mouse_refs <- c("MouseRNAref", "MouseImmGenref")
  
  if (origintaxID == 9606 && AnnReference != "None") {
    if (!AnnReference %in% human_refs) {
      error(logger, paste0('Invalid Human Reference. Options: ', paste(human_refs, collapse=", ")))
      stop("Parameter Check Failed")
    }
  } else if (origintaxID == 10090 && AnnReference != "None") {
    if (!AnnReference %in% mouse_refs) {
      error(logger, paste0('Invalid Mouse Reference. Options: ', paste(mouse_refs, collapse=", ")))
      stop("Parameter Check Failed")
    }
  } else {
    # For plants/others, usually AnnReference is None or Custom. 
    # If user provides something specific, we trust them but log a warning if it's not standard.
    if (AnnReference != "None" && !(AnnReference %in% c(human_refs, mouse_refs))) {
       info(logger, paste0('Using custom or cross-species annotation reference: ', AnnReference))
    }
  }
  info(logger, paste0('SingleR Reference    : ', green(AnnReference)))

  # 5. Validate Integration Methods
  # if (!intergetmethods %in% c("CCA", "ALL","Harmony","RPCA",'SCVI')){
  #  error(logger, paste0('  Invalid Integration Method: ', intergetmethods, '. Expected: CCA | Harmony | ALL'))
  #  stop("Parameter Check Failed")
  #} else {
  #  if (intergetmethods == 'SCVI' && is.null(opt$scvi_path)){
  #    error(logger, paste0('  Please specify the path to scvi-tools using --scvi_path'))
  #    stop("Parameter Check Failed")
  #  }
  #}
  info(logger, paste0('Integration Method   : ', green(intergetmethods)))

  # 6. Validate Reduce Type
  if (!reduceType %in% c("TRUE", "FALSE")){
    error(logger, paste0('Invalid reduceType: ', reduceType, '. Expected: TRUE | FALSE (as string)'))
    stop("Parameter Check Failed")
  }
  info(logger, paste0('Reduce Type (tSNE)  : ', green(reduceType)))

  log_divider(logger)
  info(logger, "All parameters validated successfully!")
  info(logger, "")
}
# ==============================================================================
# END 
# ==============================================================================
