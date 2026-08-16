# ==============================================================================
# Doublet Detection Functions (DoubletFinder)
# Author: zhang jian
# Description: Identifies potential doublet cells using DoubletFinder.
#              Automatically estimates doublet rates based on cell count (10x standard).
#              Optimized for resource management (auto-core detection).
# ==============================================================================

# ==============================================================================
# Function: Checkdoublet
# Description: Main wrapper to run DoubletFinder on a list of Seurat objects.
# Parameters:
#   PatchDeallist: List of Seurat objects.
#   num.cores: Number of threads to use. If NULL, auto-detects and uses 50%.
#   save_dir: Directory to save plots and results.
# ==============================================================================
Checkdoublet <- function(PatchDeallist, num.cores = NULL,sct_doubletFinder = FALSE,save_dir){
  
  quiet_load_package("DoubletFinder", logger)
  quiet_load_package("Seurat", logger)
  quiet_load_package("parallel", logger)
  
  if(!require(DoubletFinder, quietly = TRUE)) stop("Package 'DoubletFinder' not installed.")
  if(!require(Seurat, quietly = TRUE)) stop("Package 'Seurat' not installed.")
  if(!require(parallel, quietly = TRUE)) stop("Package 'parallel' not installed.")
  
  # --- Check save_dir existence ---
  if (!dir.exists(save_dir)) {
    error(logger, paste0("  The specified save directory does not exist: ", save_dir))
    stop(paste0("The specified save directory does not exist: ", save_dir))
  }

  info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  info(logger,crayon::bold(crayon::inverse(">>> STEP 8 : Checkdoublet cell by DoubletFinder")))

  # --- Auto-detect Cores ---
  if (is.null(num.cores)) {
    total_cores <- parallel::detectCores(logical = FALSE) # Physical cores
    num.cores <- max(1, floor(total_cores / 2)) # Use half, at least 1
    info(logger, paste0("  Auto-detected cores: ", total_cores, ". Using: ", num.cores, " for DoubletFinder."))
  } else {
    info(logger, paste0("  Using user-specified cores: ", num.cores))
  }

  # --- Internal Helper: Estimate Doublet Rate ---
  # Based on 10x Genomics User Guide for V3/V3.1
  Assume_doublet_prop <- function(scData){
    cell_count <- ncol(scData)
    # Linear approximation of 10x doublet rate: ~0.8% per 1000 cells
    # Formula: (CellCount * 0.008) / 1000 -> CellCount * 0.000008
    # However, let's stick to the standard table steps for safety or use a fitted linear model.
    # Simplified logic: 0.008 per 1000 cells.

    debug(logger, "  Assuming 10x standard doublet rate (0.008 per 1000 cells )")
    assum_prop <- (cell_count / 1000) * 0.008
    
    # Cap at reasonable bounds if needed (e.g., rarely exceeds 10% in standard runs)
    # But 10x allows high loading.
    
    info(logger, paste0("  Cells: ", cell_count, " | Estimated Doublet Rate: ", round(assum_prop * 100, 2), "% "))
    return(assum_prop)
  }

  # debug(logger, "Cretae doubletFinder queut function by purrr::quietly")
  # quiet_doubletFinder <- purrr::quietly(doubletFinder)

  Checkdoubletllist <- list()
  
  for (i in seq_along(PatchDeallist)){
    
    # Extract sample data
    debug(logger, "  Extracting sample data...")
    scData <- PatchDeallist[[i]]
    sample_name <- unique(as.character(scData$orig.ident))[1]
    info(logger, crayon::yellow(crayon::bold(paste0("    ============ ", sample_name," ============    "))))

    info(logger, "  Checking Doublets for: ", sample_name)

    # Ensure unique identity
    
    if(is.na(sample_name)) sample_name <- paste0("Sample_", i)
  
    # Pre-process for DoubletFinder (PCA/UMAP required)
    # We work on a copy to avoid altering the main object's normalization state if not desired,
    # but usually standard pipeline requires standard norm for DF.
    debug(logger, "  Pre-processing for DoubletFinder...")
    seu_copy <- NormalizeData(scData, verbose = FALSE)
    debug(logger, "  Finding Variable Features method vst & nfeatures = 2000")
    seu_copy <- FindVariableFeatures(seu_copy, selection.method = "vst", nfeatures = 2000, verbose = FALSE)
    seu_copy <- ScaleData(seu_copy, verbose = FALSE)
    seu_copy <- RunPCA(seu_copy, verbose = FALSE)
    seu_copy <- RunUMAP(seu_copy, dims = 1:30, verbose = FALSE)
    
    ## 1. pK Identification ----------------------------------------------------------------
    info(logger, "  Running paramSweep...")
    # Using with_logging to capture all internal output from DoubletFinder/Seurat
    sweep.res.list <- with_logging(logger, {
      paramSweep(seu_copy, PCs = 1:30, sct = FALSE, num.cores = num.cores)
    }, level = "DEBUG")
    
    sweep.stats <- summarizeSweep(sweep.res.list, GT = FALSE)
    bcmvn <- find.pK(sweep.stats)
    
    # Get best pK (max BCmetric)
    pk_best <- as.numeric(as.character(bcmvn$pK[which.max(bcmvn$BCmetric)]))
    info(logger, paste0("  Best pK found: ", pk_best))
    
    # Plot pK Selection
    debug(logger, "  Draw Plot of pK Selection...")
    p_pk <- ggplot(bcmvn, aes(x=pK, y=BCmetric, group=1)) + 
      geom_point(color = "blue") + 
      geom_line(color = "blue") + 
      labs(title = paste0("Optimal pK Selection: ", sample_name), subtitle = paste0("Best pK: ", pk_best)) + 
      theme_bw() + 
      theme(axis.text.x = element_text(angle = 45, hjust = 1))
    
    ggsave(file.path(save_dir, paste0(sample_name, "_Doublet_pk_best.pdf")), plot = p_pk, width = 8, height = 5)
    
    ## 2. Doublet Classification -----------------------------------------------------------
    # Estimate homotypic doublets (doublets formed by same cell type)
    # Requires clustering
    seu_copy <- FindNeighbors(seu_copy, dims = 1:30, verbose = FALSE)
    seu_copy <- FindClusters(seu_copy, resolution = 0.5, verbose = FALSE)
    
    annotations <- seu_copy@meta.data$seurat_clusters
    homotypic.prop <- modelHomotypic(annotations)
    
    # Estimate nExp
    assum_prop <- Assume_doublet_prop(seu_copy)
    nExp_poi <- round(assum_prop * ncol(seu_copy))
    nExp_poi.adj <- round(nExp_poi * (1 - homotypic.prop))

    # [Fix] Check if nExp is valid
    if(is.na(nExp_poi.adj) || length(nExp_poi.adj) == 0){
      warn(logger, paste0("  nExp calculation failed (NA or empty). Defaulting to unadjusted nExp: ", nExp_poi))
      nExp_poi.adj <- nExp_poi
    }

    info(logger, paste0("  Expected Doublets: ", nExp_poi, " | Adjusted for Homotypic: ", nExp_poi.adj))

    # [Fix] Clean existing DoubletFinder columns BEFORE running to avoid 'xtfrm.data.frame' errors
    # If multiple pANN columns exist, they might be fetched as a dataframe, causing sort/order errors.
    existing_meta <- colnames(seu_copy@meta.data)
    cols_to_remove <- grep("^DF.classifications|^pANN", existing_meta, value = TRUE)
    if(length(cols_to_remove) > 0){
      debug(logger, paste0("  [Debug] Removing existing DoubletFinder columns: ", paste(cols_to_remove, collapse=", ")))
      seu_copy@meta.data <- seu_copy@meta.data[, !colnames(seu_copy@meta.data) %in% cols_to_remove, drop = FALSE]
    }

    # Additional Debug: Inspect metadata to find potential causes of 'xtfrm.data.frame' error
    debug(logger, "  Inspecting metadata column types...")
    col_types <- sapply(seu_copy@meta.data, function(x) class(x)[1])
    for(cn in names(col_types)) {
      debug(logger, paste0("  Column: ", cn, " | Type: ", col_types[cn]))
    }

    # Run DoubletFinder
    debug(logger, paste0("  Running doubletFinder main function... (pK=", pk_best, ", nExp=", nExp_poi.adj, ", sct=", sct_doubletFinder, ")"))

    seu_copy <- with_logging(logger, {
      doubletFinder(seu_copy, PCs = 1:30, pN = 0.25, pK = pk_best, nExp = nExp_poi.adj, reuse.pANN = FALSE, sct = FALSE)
    }, level = "DEBUG")

    # seu_copy <- doubletFinder(seu_copy, PCs = 1:30, pN = 0.25, pK = pk_best,
    #                           nExp = nExp_poi.adj, reuse.pANN = NULL, sct = sct_doubletFinder)

    # Clean Metadata Names
    # DF creates columns like "DF.classifications_..." and "pANN_..."
    # We standardize them to "Doublet" and "pANN_Score"
    meta_cols <- colnames(seu_copy@meta.data)
    df_col <- grep("^DF.classifications", meta_cols, value = TRUE)
    pann_col <- grep("^pANN", meta_cols, value = TRUE)

    if(length(df_col) > 0) {
      seu_copy$Doublet <- seu_copy@meta.data[[df_col[1]]]
      seu_copy[[df_col]] <- NULL # Remove original
    }
    if(length(pann_col) > 0) {
      seu_copy$pANN_Score <- seu_copy@meta.data[[pann_col[1]]]
      seu_copy[[pann_col]] <- NULL # Remove original
    }

    Checkdoubletllist[[i]] <- seu_copy
    info(logger, paste0("  Finished Doublet Check for: ", sample_name))
    
    names(Checkdoubletllist)[i] <- sample_name

  }
  
  return(Checkdoubletllist)
}

# ==============================================================================
# Function: DoubletPlot
# Description: Visualizes DoubletFinder results.
# ==============================================================================
DoubletPlot <- function(Checkdoubletllist, save_dir){
  
  # Checkdoubletllist <- Seurat_list
  
  if(!require(ggplot2, quietly = TRUE)) library(ggplot2)
  if(!require(patchwork, quietly = TRUE)) library(patchwork)
  
  for (i in seq_along(Checkdoubletllist)){
    # i <- 1
    seu_scData <- Checkdoubletllist[[i]]
    name <- unique(as.character(seu_scData$orig.ident))[1]
    if(is.na(name)) name <- paste0("Sample_", i)
    
    info(logger, paste0("  Plotting Doublet Results: ", name))
    
    # Ensure "Doublet" column exists
    if (!"Doublet" %in% colnames(seu_scData@meta.data)){
      warn(logger, paste0("  Skipping plot for ", name, ": 'Doublet' column not found."))
      next
    }
    
    # Calculate Stats for Labels
    stats <- seu_scData@meta.data %>%
      group_by(Doublet) %>%
      summarise(Count = n()) %>%
      mutate(Rate = round(Count / sum(Count) * 100, 2)) %>%
      mutate(Label = paste0(Doublet, ": ", Rate, "%"))
    
    # Map labels back to metadata for plotting legend
    # Simple way: create a named vector
    label_map <- stats$Label
    names(label_map) <- stats$Doublet
    seu_scData$Doublet_Label <- unname(label_map[seu_scData$Doublet])
    
    # Save Metadata Stats
    write.table(seu_scData@meta.data, file.path(save_dir, paste0(name, "-Doublet.tsv") ), sep = "\t")
    
    # Colors: Singlet=Black, Doublet=Red/Green
    # Using specific colors for contrast
    cols <- c("Singlet" = "grey30", "Doublet" = "#E41A1C") # Red for danger/doublet
    
    # Plot 1: DimPlot
    p1 <- DimPlot(seu_scData, group.by = "Doublet", cols = cols, pt.size = 0.5) + 
      labs(title = paste0(name, ": Doublet Distribution")) + 
      theme_pubclean() +
      theme(legend.position = "none",
            plot.title = element_text(hjust = 0.5))
    # Plot 2: BarPlot Ratio
    p2 <- ggplot(stats, aes(x = "", y = Count, fill = Doublet)) + 
      geom_bar(stat = "identity", position = "fill", width = 0.5) + 
      scale_fill_manual(values = cols) + 
      scale_y_continuous(labels = scales::percent) + 
      labs(y = "Percentage", x = "", title = "Rate") + 
      theme_pubclean() + 
      theme(plot.title = element_text(hjust = 0.5),
            legend.position = 'bottom',
            axis.line.x = element_blank(),
            axis.ticks.x = element_blank())
    
    # Combine
    combined_plot <- (p1 + p2) + plot_layout(widths = c(3, 1),guides = 'collect') &
    theme(legend.position = 'bottom')
    
    ggsave(file.path(save_dir, paste0(name, "_Doublet_Cells.pdf")), plot = combined_plot, width = 10, height = 6)
    ggsave(file.path(save_dir, paste0(name, "_Doublet_Cells.png")), plot = combined_plot, width = 10, height = 6, dpi = 300)
    
    info(logger, paste0("  Saved plots for: ", name))
  }
}

# ==============================================================================
# END 
# ==============================================================================