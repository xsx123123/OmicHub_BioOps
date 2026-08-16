# ==============================================================================
# Seurat Object Subsetting & Re-analysis
# Author: zhang jian
# Description: Functions to subset Seurat objects by identity or cell ID, 
#              perform re-analysis (PCA, UMAP, Clustering), and link scVDJ data.
# ==============================================================================

# ==============================================================================
# Helper: Check Dependencies
# ==============================================================================
CheckSubsetDeps <- function(){
  req_pkgs <- c("Seurat", "ggplot2", "dplyr", "patchwork", "crayon")
  missing <- req_pkgs[!sapply(req_pkgs, require, character.only = TRUE, quiet = TRUE)]
  if(length(missing) > 0) stop("Missing dependencies: ", paste(missing, collapse=", "))
}

# ==============================================================================
# Core Function: ReanalyzeSubset
# Description: Performs standard re-analysis on a subsetted Seurat object.
#              (FindVariableFeatures -> Scale -> PCA -> UMAP -> Cluster)
# ==============================================================================
ReanalyzeSubset <- function(obj, save_dir, dims = 1:20, resolution = 0.8, n_features = 2000){
  
  info(logger, paste0("Re-analyzing subset with ", ncol(obj), " cells..."))
  
  # 1. Variable Features
  # Re-calculate variable features for the subset, as variance structure changes
  obj <- FindVariableFeatures(obj, selection.method = "vst", nfeatures = n_features, verbose = FALSE)
  
  # 2. Scale Data
  # Scaling all genes or just variable features? 
  # Scaling all genes can be slow. Defaulting to variable features is standard.
  obj <- ScaleData(obj, features = VariableFeatures(obj), verbose = FALSE)
  
  # 3. PCA
  obj <- RunPCA(obj, npcs = max(30, max(dims)), verbose = FALSE)
  
  # 4. Neighbors & Clusters
  obj <- FindNeighbors(obj, dims = dims, verbose = FALSE)
  obj <- FindClusters(obj, resolution = resolution, verbose = FALSE)
  
  # 5. UMAP & tSNE
  obj <- RunUMAP(obj, dims = dims, verbose = FALSE)
  tryCatch({
    obj <- RunTSNE(obj, dims = dims, check_duplicates = FALSE, verbose = FALSE)
  }, error = function(e){
    warn(logger, paste0("tSNE skipped: ", e$message))
  })
  
  # 6. Visualization
  p1 <- DimPlot(obj, reduction = "umap", group.by = "orig.ident") + ggtitle("Batch (UMAP)")
  p2 <- DimPlot(obj, reduction = "umap", label = TRUE) + NoLegend() + ggtitle("Clusters (UMAP)")
  
  # Only plot tSNE if it exists
  if("tsne" %in% names(obj@reductions)){
    p3 <- DimPlot(obj, reduction = "tsne", group.by = "orig.ident") + ggtitle("Batch (tSNE)")
    p4 <- DimPlot(obj, reduction = "tsne", label = TRUE) + NoLegend() + ggtitle("Clusters (tSNE)")
    combined_plot <- (p1 | p2) / (p3 | p4)
  } else {
    combined_plot <- p1 | p2
  }
  
  # Save
  if(!dir.exists(save_dir)) dir.create(save_dir, recursive = TRUE)
  ggsave(file.path(save_dir, "Subset_Reanalysis_Check.pdf"), plot = combined_plot, width = 10, height = 8)
  ggsave(file.path(save_dir, "Subset_Reanalysis_Check.png"), plot = combined_plot, width = 10, height = 8, dpi = 300)
  
  return(obj)
}

# ==============================================================================
# Wrapper: Subset by Identity (e.g., Cell Type)
# ==============================================================================
SubsetByIdent <- function(obj, idents_keep, save_dir){
  
  CheckSubsetDeps()
  
  # Verify idents
  valid_idents <- idents_keep[idents_keep %in% levels(Idents(obj))]
  if(length(valid_idents) == 0) stop("No valid identities found to subset.")
  
  info(logger, paste0("Subsetting object. Keeping identities: ", paste(valid_idents, collapse = ", ")))
  
  subset_obj <- subset(obj, idents = valid_idents)
  
  subset_obj <- ReanalyzeSubset(subset_obj, save_dir)
  return(subset_obj)
}

# ==============================================================================
# Wrapper: Subset by Cell IDs
# ==============================================================================
SubsetByCells <- function(obj, cell_ids, save_dir){
  
  CheckSubsetDeps()
  
  valid_cells <- intersect(cell_ids, colnames(obj))
  if(length(valid_cells) == 0) stop("No valid cell IDs found to subset.")
  
  info(logger, paste0("Subsetting object. Keeping ", length(valid_cells), " cells."))
  
  subset_obj <- subset(obj, cells = valid_cells)
  
  subset_obj <- ReanalyzeSubset(subset_obj, save_dir)
  return(subset_obj)
}


# ==============================================================================
# Function: Link_scVDJ
# Description: Processes AIRR rearrangement data and links it to the Seurat object.
# ==============================================================================
Link_scVDJ <- function(seurat_obj, airr_path, output_dir){
  
  if(!file.exists(airr_path)) stop("AIRR rearrangement file not found: ", airr_path)
  
  info(logger, "Processing scVDJ data...")
  
  # Read Data
  vdj_data <- read.csv(airr_path, sep = "\t", stringsAsFactors = FALSE)
  
  # Filter: Productive only
  if("productive" %in% colnames(vdj_data)){
    vdj_data <- vdj_data[vdj_data$productive == "TRUE" | vdj_data$productive == TRUE, ]
  }
  
  # Extract V, J, Chain info safely
  # Some AIRR formats use '|' separators or different naming.
  # Assuming standard 10x output or similar AIRR format.
  
  if("v_call" %in% colnames(vdj_data)){
    vdj_data$V_gene <- sapply(strsplit(vdj_data$v_call, "[*]"), `[`, 1) # Remove allele info
    vdj_data$chain <- substr(vdj_data$v_call, 1, 3) # e.g. TRA, TRB, IGH
  }
  
  # Select key columns
  cols_keep <- c("cell_id", "clone_id", "sequence", "sequence_aa", "v_call", "j_call", "c_call", "chain")
  cols_keep <- intersect(cols_keep, colnames(vdj_data))
  vdj_clean <- vdj_data[, cols_keep]
  
  # Rename cell_id to barcode match Seurat (usually suffixed with -1)
  # Check format. 10x usually is AAACCC...-1
  if(length(grep("-1$", colnames(seurat_obj)[1])) > 0 && length(grep("-1$", vdj_clean$cell_id[1])) == 0){
     vdj_clean$barcode <- paste0(vdj_clean$cell_id, "-1")
  } else {
     vdj_clean$barcode <- vdj_clean$cell_id
  }
  
  # Save cleaned VDJ info
  if(!dir.exists(output_dir)) dir.create(output_dir, recursive = TRUE)
  write.csv(vdj_clean, file.path(output_dir, "scVDJ_Cleaned_Info.csv"), row.names = FALSE)
  
  # Calculate Frequency
  if("clone_id" %in% colnames(vdj_clean)){
    freq_table <- as.data.frame(table(vdj_clean$clone_id))
    colnames(freq_table) <- c("CloneID", "Frequency")
    freq_table$Proportion <- prop.table(freq_table$Frequency)
    write.csv(freq_table, file.path(output_dir, "Clonotype_Frequency.csv"), row.names = FALSE)
  }
  
  # Link to Seurat Subset
  # Only keep VDJ info for cells in the Seurat object
  vdj_subset <- vdj_clean[vdj_clean$barcode %in% colnames(seurat_obj), ]
  
  if(nrow(vdj_subset) > 0){
    write.csv(vdj_subset, file.path(output_dir, "scVDJ_Linked_Subset.csv"), row.names = FALSE)
    info(logger, paste0("Linked ", nrow(vdj_subset), " VDJ records to the subsetted Seurat object."))
  } else {
    warn(logger, "No overlapping cells found between Seurat subset and VDJ data.")
  }
}
# ==============================================================================
# END 
# ==============================================================================
