# ==============================================================================
# Cell Quality Control (QC) & Filtering Functions
# Author: zhang jian
# Date: 2025-12-23 (Refactored for Adaptive MAD QC)
# Description: Handles data loading (10x, DNBC4, Seurat), QC metrics calculation 
#              (nFeature, nCount, MT%), visualization, and automated filtering.
#              Optimized for Plant support (handles missing MT annotations gracefully).
# ==============================================================================

# ==============================================================================
# Function: scRAWqc
# Description: Generates Violin plots for raw data QC metrics (nFeature, nCount, MT%).
#              Automatically hides 'percent.mt' plot if values are all zero (e.g. Plants).
# @ data : Seurat object containing raw data.
# @ name : Sample name used for file naming.
# @ figure_dir : Directory to save the QC plots.
# ==============================================================================
scRAWqc <- function(data, name, figure_dir){
  # Check if MT percent is available/meaningful
  has_mt <- any(data$percent.mt > 0)
  
  feats <- c("nFeature_RNA", "nCount_RNA")
  if (has_mt) feats <- c(feats, "percent.mt")
  
  p <- VlnPlot(data, group.by = "orig.ident",
               features = feats,
               ncol = length(feats),
               pt.size = 0.05,
               layer = "counts",
               combine = TRUE)
  
  # Save plots
  ggsave(file.path(figure_dir, paste0("1.", name, " raw data qc.pdf")), plot = p, width = 20, height = 20, units = "cm", device = "pdf")
  ggsave(file.path(figure_dir, paste0("1.", name, " raw data qc.png")), plot = p, width = 20, height = 20, units = "cm", device = "png", dpi = 300)
}

# ==============================================================================
# Function: scFiltedqc
# Description: Generates Violin plots for filtered data QC metrics.
#              Visualizes the distribution of features after QC filtering steps.
# @ data : Seurat object containing filtered data.
# @ name : Sample name used for file naming.
# @ figure_dir : Directory to save the QC plots.
# ==============================================================================
scFiltedqc <- function(data, name, figure_dir){
  # Check if MT percent is available
  has_mt <- any(data$percent.mt > 0)
  
  feats <- c("nFeature_RNA", "nCount_RNA")
  if (has_mt) feats <- c(feats, "percent.mt")
  
  p <- VlnPlot(data, group.by = "orig.ident",
               features = feats,
               ncol = length(feats),
               layer = "counts",
               pt.size = 0.05,
               combine = TRUE)
  
  # Save plots
  ggsave(file.path(figure_dir, paste0("2.", name, " filted data qc.pdf")), plot = p, width = 20, height = 20, units = "cm", device = "pdf")
  ggsave(file.path(figure_dir, paste0("2.", name, " filted data qc.png")), plot = p, width = 20, height = 20, units = "cm", device = "png", dpi = 300)
}

# ==============================================================================
# Function: AutocheckMTprop
# Description: Automatically calculates mitochondrial gene percentage based on TaxID.
#              - Human (9606): Matches "^MT-"
#              - Mouse (10090): Matches "^mt-"
#              - Plants/Others: Sets MT% to 0 by default to avoid filtering errors.
# @ origin_tax_ID : Taxonomy ID of the organism (e.g., 9606, 10090).
# @ data : Seurat object to calculate MT percentage for.
# ==============================================================================
AutocheckMTprop <- function(origin_tax_ID, data){
  if (origin_tax_ID == 10090) {
    # Mouse
    if (any(grepl("^mt-", rownames(data)))) {
      data[["percent.mt"]] <- PercentageFeatureSet(data, pattern = "^mt-")
    } else {
      warn(logger, "  TaxID is Mouse (10090) but no '^mt-' genes found. Setting MT% to 0.")
      data[["percent.mt"]] <- 0
    }
  } else if (origin_tax_ID == 9606) {
    # Human
    if (any(grepl("^MT-", rownames(data)))) {
      data[["percent.mt"]] <- PercentageFeatureSet(data, pattern = "^MT-")
    } else {
      warn(logger, "  TaxID is Human (9606) but no '^MT-' genes found. Setting MT% to 0.")
      data[["percent.mt"]] <- 0
    }
  } else {
    # Plants or Others
    info(logger, crayon::bgRed(paste0("  TaxID ", origin_tax_ID, "(Non-Human/Mouse). Skipping automatic MT% calculation. Setting MT% to 0.")))
    # Future improvement: Allow passing custom regex for Plant MT genes (e.g. "ATM", "pt-")
    data[["percent.mt"]] <- 0
  }
  return(data)
}

# ==============================================================================
# Helper Function: calculate_mad_thresholds
# Description: Calculates adaptive QC thresholds using Median Absolute Deviation (MAD).
#              Returns a list containing suggested lower and upper bounds.
# @ metrics : Numeric vector of QC metrics (e.g., nFeature_RNA).
# @ nmads : Number of MADs to use for outlier detection (Default: 3).
# @ type : "both", "lower", or "higher".
# ==============================================================================
calculate_mad_thresholds <- function(metrics, nmads = 3, type = "both") {
  # Handle case with all zeros or constant values
  if (all(metrics == 0) || length(unique(metrics)) == 1) {
    return(list(lower = -Inf, upper = Inf))
  }
  
  # Use scater::isOutlier logic manually to avoid dependency issues or for transparency
  med_val <- median(metrics, na.rm = TRUE)
  mad_val <- mad(metrics, constant = 1.4826, na.rm = TRUE)
  
  upper_cut <- Inf
  lower_cut <- -Inf
  
  if (type %in% c("both", "higher")) {
    upper_cut <- med_val + (nmads * mad_val)
  }
  if (type %in% c("both", "lower")) {
    lower_cut <- med_val - (nmads * mad_val)
  }
  
  return(list(lower = lower_cut, upper = upper_cut))
}

# ==============================================================================
# Helper Function: process_single_sample_qc
# Description: Internal unified function to handle QC logic for a single Seurat object.
#              Performs MT calculation, raw QC plotting, auto/manual threshold determination,
#              filtering, settings export, and post-filtering QC plotting.
#              UPDATED: Now supports MAD-based adaptive filtering.
# ==============================================================================
process_single_sample_qc <- function(seurat_obj, sample_name,
                                     scRNAAutofilted,
                                     Standard_dir,
                                     origin_tax_ID,
                                     nFeature_RNA_cutoff_1_default=200){

  # origin cell count
  origin_cell_count <- ncol(seurat_obj)
  
  # 1. Calculate MT prop
  seurat_obj <- AutocheckMTprop(origin_tax_ID, seurat_obj)
  debug(logger,  paste0("  MT prop calculated : ", sample_name))
  
  # 2. Raw QC Plot
  scRAWqc(seurat_obj, sample_name, Standard_dir)
  debug(logger,  paste0("  Raw QC Plot : ", sample_name))
  
  # 3. Determine Cutoffs (Adaptive vs Manual)
  # Initialize defaults
  percent_mt_cutoff <- 100
  nFeature_upper <- Inf
  nFeature_lower <- nFeature_RNA_cutoff_1_default # Default hard lower bound
  nCount_upper <- Inf
  nCount_lower <- -Inf
  
  if (scRNAAutofilted == TRUE) {
    info(logger, crayon::bold(crayon::cyan("  [Adaptive QC] Calculating MAD-based thresholds (nmads=3)...")))
    
    # --- Feature (Gene) Counts ---
    # Detect both low quality cells (low genes) and potential doublets (high genes)
    gene_thresh <- calculate_mad_thresholds(seurat_obj$nFeature_RNA, nmads = 3, type = "both")
    
    # Ensure lower bound isn't ridiculously low (e.g. < 200) even if MAD suggests it
    # We keep a 'safety net' hard floor of 200, unless MAD suggests higher.
    nFeature_lower <- max(200, gene_thresh$lower) 
    nFeature_upper <- gene_thresh$upper
    
    # --- Mitochondrial Percentage ---
    # Only filter high MT
    if (any(seurat_obj$percent.mt > 0)) {
       mt_thresh <- calculate_mad_thresholds(seurat_obj$percent.mt, nmads = 3, type = "higher")
       percent_mt_cutoff <- min(100, mt_thresh$upper) # Cap at 100%
    } else {
       info(logger, "  No MT genes detected. Skipping MT filtering.")
       percent_mt_cutoff <- 100
    }
    
    info(logger, paste0("  [Auto] Gene Lower: ", round(nFeature_lower,0), " | Gene Upper: ", round(nFeature_upper,0)))
    info(logger, paste0("  [Auto] MT Upper: ", round(percent_mt_cutoff,2), "%"))
    
  } else {
    # --- Manual Mode ---
    # Fallback to global variables or defaults
    percent_mt_cutoff <- if(exists("percent.mt_cutoff")) get("percent.mt_cutoff") else 20
    nFeature_upper <- if(exists("nFeature_RNA_cutoff_2")) get("nFeature_RNA_cutoff_2") else 10000
    nFeature_lower <- if(exists("nFeature_RNA_cutoff_1") && !is.na(get("nFeature_RNA_cutoff_1"))) get("nFeature_RNA_cutoff_1") else nFeature_RNA_cutoff_1_default
    
    info(logger, paste0("  [Manual] QC Thresholds | Gene: ", nFeature_lower, "-", nFeature_upper, " | Mito: <", percent_mt_cutoff, "%"))
  }
  
  # 4. Filter Data
  # Apply all filters
  seurat_obj <- subset(seurat_obj, 
                       subset = nFeature_RNA > nFeature_lower & 
                                nFeature_RNA < nFeature_upper & 
                                percent.mt < percent_mt_cutoff)

  # 5. Save Settings
  filted_setting <- data.frame(
    "MT_cutoff_upper" = percent_mt_cutoff,
    "nFeature_cutoff_upper" = nFeature_upper,
    "nFeature_cutoff_lower" = nFeature_lower,
    "Mode" = if(scRNAAutofilted) "Adaptive_MAD" else "Manual_Fixed"
  )
  write.csv(filted_setting, file.path(Standard_dir, paste0(sample_name, "_filted_setting.csv")))
  
  # 6. Filtered QC Plot
  debug(logger,  paste0("  Filtered QC Plot : ",sample_name) )
  scFiltedqc(seurat_obj, sample_name, Standard_dir)
  
  info(logger, paste0("  QC & Filtering Done for: ", sample_name))

  # filter_cell_count
  filter_cell_count <- ncol(seurat_obj)

  info(logger, paste0("  Cell Count | Origin: ", crayon::yellow(origin_cell_count), 
              " | Filtered: ", crayon::green(filter_cell_count), 
              " | Removed: ", crayon::red(origin_cell_count - filter_cell_count)))
  
  return(seurat_obj)
}


# ==============================================================================
# Function: PatchDealform10X
# Description: Loads and processes 10x Genomics data from raw directories.
#              Reads 10x matrix, creates Seurat objects, standardizes gene names,
#              adds group metadata, and runs the unified QC pipeline.
# @ CellrangerList : Named list of paths to 10x data directories.
# @ group_data : Dataframe containing group info for each sample.
# @ scRNAAutofilted : Boolean, whether to use automated filtering.
# @ Standard_dir : Output directory for QC results.
# @ origin_tax_ID : Taxonomy ID (e.g., 9606) for MT pattern matching.
# ==============================================================================
PatchDealform10X <- function(CellrangerList,group_data,scRNAAutofilted, Standard_dir, origin_tax_ID){

  scrna_seq_list <- list()

  info(logger, '  Loading and processing 10x scRNA-seq data...')
  for(i in 1:length(CellrangerList)){
    sample_name <- names(CellrangerList[i])
    data_path <- CellrangerList[i]

    info(logger, crayon::yellow(crayon::bold(paste0("    ============ ", sample_name," ============    "))))

    info(logger, paste0("  Processing 10x Sample: ", sample_name))
    if (!dir.exists(data_path)) {
      error(logger, paste0("  Data directory not found: ", data_path))
      next 
    }
    
    debug(logger, paste0("  Reading 10x Sample: ", sample_name))
    counts <- Read10X(data.dir = data_path)

    debug(logger, "  Fixing gene names replacing '_' with '-")
    rownames(counts) <- gsub("_", "-", rownames(counts))

    debug(logger, paste0("  Create Seurat Object: ", sample_name,'min.cells = 3 & min.features = 200'))
    seurat_obj <- CreateSeuratObject(counts, min.cells = 3, min.features = 200,
                                     project = sample_name, names.delim = "-", names.field = c(1:2))

    group_info <- group_data |> filter(name == sample_name)
    seurat_obj@meta.data$group <- group_info$group
    info(logger, crayon::blue(crayon::bold(paste0('  Adding group info: ', group_info$group, ' to ', sample_name))))

    debug(logger, paste0("  Sample qc: ", sample_name))
    scrna_seq_list[[i]] <- process_single_sample_qc(seurat_obj, sample_name, scRNAAutofilted, Standard_dir, origin_tax_ID)

    debug(logger, "  Add Sample name to scrna_seq_list ")
    names(scrna_seq_list)[i] <- sample_name

    # info(logger, crayon::blue(crayon::bold(paste0("                ", sample_name,"                 "))))
  }
  return(scrna_seq_list)
}

# ==============================================================================
# Function: PatchDealformDNB
# Description: Loads and processes DNBC4 (MGI) data from raw directories.
#              Reads data (using gene column 1), creates Seurat objects, 
#              standardizes gene names, adds group metadata, and runs unified QC.
# @ CellrangerList : Named list of paths to DNBC4 data directories.
# @ group_data : Dataframe containing group info for each sample.
# @ scRNAAutofilted : Boolean, whether to use automated filtering.
# @ Standard_dir : Output directory for QC results.
# @ origin_tax_ID : Taxonomy ID (e.g., 9606) for MT pattern matching.
# ==============================================================================
PatchDealformDNB <- function(CellrangerList,group_data,scRNAAutofilted, Standard_dir, origin_tax_ID){
  scrna_seq_list <- list()
  
  info(logger, '  Loading and processing DNB scRNA-seq data...')
  for(i in 1:length(CellrangerList)){
    sample_name <- names(CellrangerList[i])
    data_path <- CellrangerList[i]

    info(logger, crayon::yellow(crayon::bold(paste0("    ============ ", sample_name," ============    "))))
    
    info(logger, paste0("  Processing DNBC4 Sample: ", sample_name))
    
    if (!dir.exists(data_path)) {
      error(logger, paste0("  Data directory not found: ", data_path))
      next
    }
    
    debug(logger, paste0("  Reading DNB Sample: ", sample_name))
    counts <- Read10X(data.dir = data_path, gene.column = 1)

    debug(logger, "  Fixing gene names replacing '_' with '-")
    rownames(counts) <- gsub("_", "-", rownames(counts))

    debug(logger, paste0("  Create Seurat Object: ", sample_name,'min.cells = 3 & min.features = 200'))
    seurat_obj <- CreateSeuratObject(counts, min.cells = 3, min.features = 200,
                                     project = sample_name, names.delim = "-", names.field = c(1:2))

    group_info <- group_data |> filter(name == sample_name)
    seurat_obj@meta.data$group <- group_info$group
    info(logger, crayon::blue(crayon::bold(paste0('  Adding group info: ', group_info$group, ' to ', sample_name))))
    
    debug(logger, paste0("  Sample qc: ", sample_name))
    scrna_seq_list[[i]] <- process_single_sample_qc(seurat_obj, sample_name, scRNAAutofilted, Standard_dir, origin_tax_ID)

    debug(logger, "  Add Sample name to scrna_seq_list ")
    names(scrna_seq_list)[i] <- sample_name

    # info(logger, crayon::blue(crayon::bold(paste0("                ", sample_name,"                 "))))
  }
  return(scrna_seq_list)
}

# ==============================================================================
# Function: DNBC4_10X
# Description: Wrapper to route analysis based on library type (10x vs DNBC4).
#              Acts as a single entry point for processing raw data directories.
#              Supports per-sample library types if cellRangerlist_dataframe is provided.
# @ scRNAtype : Default library type string ('10x' or 'DNBC4') - used if per-sample type not available.
# @ scRNAAutofilted : Boolean, whether to use automated filtering.
# @ list : Named list of input data paths.
# @ group_data : Dataframe containing group info.
# @ Cellranger_dir : Output directory for QC (passed as Standard_dir).
# @ origin_tax_ID : Taxonomy ID for QC logic.
# @ cellRangerlist_dataframe : Optional dataframe with library_type column for per-sample types.
# ==============================================================================
DNBC4_10X <- function(scRNAtype = '10x',scRNAAutofilted = TRUE,
                       list,group_data,Cellranger_dir,origin_tax_ID,
                       cellRangerlist_dataframe = NULL){
  
  # Check if we have per-sample library types
  if (!is.null(cellRangerlist_dataframe) && "library_type" %in% colnames(cellRangerlist_dataframe)) {
    info(logger, '  Processing samples with per-sample library types...')
    
    # Split samples by library type
    samples_10x <- c()
    samples_dnb <- c()
    
    for (sample_name in names(list)) {
      sample_type <- cellRangerlist_dataframe$library_type[cellRangerlist_dataframe$name == sample_name]
      if (length(sample_type) > 0 && sample_type == "DNBC4") {
        samples_dnb <- c(samples_dnb, sample_name)
      } else {
        samples_10x <- c(samples_10x, sample_name)
      }
    }
    
    # Process 10x samples
    PatchDeallist_10x <- list()
    if (length(samples_10x) > 0) {
      info(logger, paste0('  Processing ', length(samples_10x), ' 10x sample(s)...'))
      list_10x <- list[samples_10x]
      PatchDeallist_10x <- PatchDealform10X(list_10x, group_data, scRNAAutofilted, Cellranger_dir, origin_tax_ID)
    }
    
    # Process DNBC4 samples
    PatchDeallist_dnb <- list()
    if (length(samples_dnb) > 0) {
      info(logger, paste0('  Processing ', length(samples_dnb), ' DNBC4 sample(s)...'))
      list_dnb <- list[samples_dnb]
      PatchDeallist_dnb <- PatchDealformDNB(list_dnb, group_data, scRNAAutofilted, Cellranger_dir, origin_tax_ID)
    }
    
    # Combine results
    PatchDeallist <- c(PatchDeallist_10x, PatchDeallist_dnb)
    # Reorder to match original input order
    PatchDeallist <- PatchDeallist[names(list)]
    
  } else {
    # Original behavior - single library type for all samples
    if (scRNAtype == '10x'){
      info(logger, '  Processing 10x scRNA-seq gene matrix...')
      PatchDeallist <- PatchDealform10X(list,group_data,scRNAAutofilted, Cellranger_dir, origin_tax_ID)
    } else if (scRNAtype == 'DNBC4') {
      info(logger, '  Processing DNBC4 scRNA-seq gene matrix...')
      PatchDeallist <- PatchDealformDNB(list,group_data,scRNAAutofilted, Cellranger_dir, origin_tax_ID)
    } else {
      error(logger,"  Please use '10x' or 'DNBC4'")
      stop(paste0("Unsupported scRNAtype: ", scRNAtype, ". Please use '10x' or 'DNBC4'."))
    }
  }
  return(PatchDeallist)
}

# ==============================================================================
# Function: PatchDealformSeurat
# Description: Processes existing Seurat objects through the unified QC pipeline.
#              This is used when data is already loaded as R objects rather than
#              raw file paths. It ensures consistent QC metrics, visualization,
#              and filtering regardless of the initial data source.
# @ PatchDeallist : A list of existing Seurat objects, named by sample.
# @ scRNAAutofilted : Whether to use automated outlier detection for filtering.
# @ Standard_dir : Output directory for QC plots and settings.
# ==============================================================================
PatchDealformSeurat <- function(PatchDeallist, scRNAAutofilted, Standard_dir){
  # Infer TaxID from metadata or default to 'Other' (0) if unknown to skip strict MT checks
  # Or rely on existing percent.mt
  
  for(i in 1:length(PatchDeallist)){
    sample_name <- names(PatchDeallist[i])
    info(logger, paste0("  Re-processing Seurat Object: ", sample_name))
    
    # Re-calculate MT if missing, default to Human/Mouse pattern if not specified
    # Note: This function signature didn't include origin_tax_ID originally.
    # We assume objects might already have percent.mt or we default to a safe check.
    if (!"percent.mt" %in% colnames(PatchDeallist[[i]]@meta.data)) {
        PatchDeallist[[i]][["percent.mt"]] <- PercentageFeatureSet(PatchDeallist[[i]], pattern = "^[Mm][Tt]-")
    }

    # Re-use the unified processor
    # passing origin_tax_ID = 9606 (Human) as a safe-guard for pattern check, 
    # ensuring existing or newly calculated MT% is used in filtering logic.
    PatchDeallist[[i]] <- process_single_sample_qc(
        PatchDeallist[[i]], 
        sample_name, 
        scRNAAutofilted, 
        Standard_dir, 
        origin_tax_ID = 9606 
    )
  }
  return(PatchDeallist)
}
# ==============================================================================
# END 
# ==============================================================================