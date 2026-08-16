# ==============================================================================
# Differential Expression Analysis (DEG) & Visualization
# Author: zhang jian
# Description: Modular functions for finding marker genes (FindMarkers/FindConservedMarkers)
#              and visualizing results (Volcano Plots).
#              Supports multithreading and Plant analysis adjustments.
# ==============================================================================

# ==============================================================================
# Helper: Check Dependencies
# ==============================================================================
CheckDEGDeps <- function(){
  req_pkgs <- c("Seurat", "ggplot2", "dplyr", "ggrepel", "parallel", "patchwork", "plotly", "htmlwidgets", "crayon")
  missing <- req_pkgs[!sapply(req_pkgs, require, character.only = TRUE, quiet = TRUE)]
  if(length(missing) > 0) stop("Missing DEG dependencies: ", paste(missing, collapse=", "))
}

# ==============================================================================
# Function: PlotVolcano
# Description: A unified, publication-ready volcano plot generator.
# Parameters:
#   deg_result: Dataframe from FindMarkers.
#   name: Title/Prefix for the plot.
#   save_dir: Directory to save output.
#   pval_cutoff: Cutoff for p-value (default 0.05).
#   logfc_cutoff: Cutoff for log2FC (default 0.5).
#   top_n_label: Number of top genes to label (default 15).
# ==============================================================================
PlotVolcano <- function(deg_result, name, save_dir, pval_cutoff = 0.05, logfc_cutoff = 0.5, top_n_label = 15){
  
  # Ensure necessary columns
  if(!"p_val" %in% colnames(deg_result)) stop("DEG result missing 'p_val' column")
  if(!"avg_log2FC" %in% colnames(deg_result)) stop("DEG result missing 'avg_log2FC' column")
  
  # Prepare Data
  # Handle p-value = 0 (replace with min non-zero or just use a high limit)
  min_pval <- min(deg_result$p_val[deg_result$p_val > 0], na.rm = TRUE)
  plot_data <- deg_result %>%
    mutate(
      log10pval = -log10(pmax(p_val, min_pval * 1e-2)), # Avoid Inf
      Symbol = rownames(.),
      Group = case_when(
        p_val < pval_cutoff & avg_log2FC > logfc_cutoff ~ "Up-regulated",
        p_val < pval_cutoff & avg_log2FC < -logfc_cutoff ~ "Down-regulated",
        TRUE ~ "Non-significant"
      )
    )
  
  # Save Summaries
  up_genes <- filter(plot_data, Group == "Up-regulated")
  down_genes <- filter(plot_data, Group == "Down-regulated")
  
  write.csv(up_genes, file.path(save_dir, paste0(name, "-DEG-Up.csv")))
  write.csv(down_genes, file.path(save_dir, paste0(name, "-DEG-Down.csv")))
  
  # Top Genes for Labeling
  top_up <- up_genes %>% arrange(desc(avg_log2FC)) %>% head(top_n_label)
  top_down <- down_genes %>% arrange(avg_log2FC) %>% head(top_n_label)
  label_data <- rbind(top_up, top_down)
  
  # Dynamic Axis Limits
  max_fc <- max(abs(plot_data$avg_log2FC), na.rm=T) * 1.1
  max_pval <- max(plot_data$log10pval, na.rm=T) * 1.1
  
  # Colors
  cols <- c("Up-regulated" = "#E41749", "Down-regulated" = "#41B6E6", "Non-significant" = "grey80")
  
  # Plot
  p <- ggplot(plot_data, aes(x = avg_log2FC, y = log10pval)) +
    geom_point(aes(fill = Group, color = Group), size = 1, shape = 21, alpha = 0.6) +
    scale_fill_manual(values = cols) +
    scale_color_manual(values = cols) +
    geom_vline(xintercept = c(-logfc_cutoff, logfc_cutoff), linetype = "dashed", color = "black", size = 0.3) +
    geom_hline(yintercept = -log10(pval_cutoff), linetype = "dashed", color = "black", size = 0.3) +
    labs(
      title = paste0(name, " Volcano Plot"),
      x = bquote(~Log[2] ~ "Fold Change"),
      y = bquote(~-Log[10] ~ "P-value"),
      subtitle = paste0("Up: ", nrow(up_genes), " | Down: ", nrow(down_genes))
    ) +
    geom_text_repel(
      data = label_data, aes(label = Symbol),
      size = 3, fontface = "italic", max.overlaps = 20,
      box.padding = 0.5
    ) +
    theme_classic() +
    theme(
      plot.title = element_text(hjust = 0.5, face = "bold"),
      legend.position = "top"
    )
  
  # Save
  ggsave(file.path(save_dir, paste0(name, "-Volcano.pdf")), plot = p, width = 6, height = 6)
  ggsave(file.path(save_dir, paste0(name, "-Volcano.png")), plot = p, width = 6, height = 6, dpi = 300)
  
  return(p)
}

# ==============================================================================
# Core DEG Function: RunDiffExp
# Description: Wrapper to run FindMarkers/FindConservedMarkers and save results.
# ==============================================================================
RunDiffExp <- function(obj, ident.1, ident.2 = NULL, method = "wilcox", save_dir_root, cluster_id, conserved = FALSE, grouping.var = NULL){
  
  save_dir <- file.path(save_dir_root, paste0("Cluster-", cluster_id))
  if(!dir.exists(save_dir)) dir.create(save_dir, recursive = TRUE)
  
  info(logger, paste0("Running DEG for Cluster ", cluster_id, " | Method: ", method))
  
  tryCatch({
    if (conserved) {
      if (is.null(grouping.var)) stop("grouping.var required for Conserved Markers")
      
      # Plant Support: If grouping var has only 1 level in this cluster, FindConserved fails.
      # Fallback to standard FindMarkers
      cells <- WhichCells(obj, idents = ident.1)
      if (length(unique(obj@meta.data[cells, grouping.var])) < 2) {
        warn(logger, paste0("Cluster ", cluster_id, " does not have multiple groups for conserved analysis. Falling back to FindMarkers."))
        deg <- FindMarkers(obj, ident.1 = ident.1, ident.2 = ident.2, test.use = method, min.pct = 0.25)
      } else {
        deg <- FindConservedMarkers(obj, ident.1 = ident.1, grouping.var = grouping.var, test.use = method, verbose = FALSE)
        # Conserved markers output structure is different (p_val per group), need to unify for plotting
        # Strategy: Use max p_val or combined p_val. For simplicity, we create pseudo columns.
        # But usually we don't draw standard volcano for conserved markers because they have p-vals for each group.
        # We save the raw table and skip volcano or plot one group.
        write.csv(deg, file.path(save_dir, paste0(cluster_id, "-Conserved-DEG.csv")))
        return(NULL) # Skip volcano for conserved for now
      }
    } else {
      deg <- FindMarkers(obj, ident.1 = ident.1, ident.2 = ident.2, test.use = method, min.pct = 0.25, verbose = FALSE)
    }
    
    # Save & Plot
    write.csv(deg, file.path(save_dir, paste0(cluster_id, "-DEG-All.csv")))
    
    # Filter valid results for plotting
    deg_valid <- deg[!is.na(deg$p_val) & !is.na(deg$avg_log2FC), ]
    if(nrow(deg_valid) > 0){
      PlotVolcano(deg_valid, name = as.character(cluster_id), save_dir = save_dir)
    }
    
  }, error = function(e){
    warn(logger, paste0("DEG failed for Cluster ", cluster_id, ": ", e$message))
  })
}

# ==============================================================================
# Wrapper: Multithreading Find All Markers
# ==============================================================================
MultithreadingFindMarkers <- function(obj, save_dir, test_method = "wilcox", threads = TRUE, conserved = FALSE){
  
  CheckDEGDeps()
  
  # Ensure Idents are set
  clusters <- levels(Idents(obj))
  if(length(clusters) == 0) stop("No active identity found in Seurat object.")
  
  info(logger, paste0("Starting DEG Analysis for ", length(clusters), " clusters."))
  
  # Define Worker Function
  worker_func <- function(cluster_id){
    RunDiffExp(
      obj = obj, 
      ident.1 = cluster_id, 
      method = test_method, 
      save_dir_root = save_dir, 
      cluster_id = cluster_id,
      conserved = conserved,
      grouping.var = if(conserved) "orig.ident" else NULL
    )
  }
  
  if (threads && .Platform$OS.type != "windows"){
    num_cores <- max(1, floor(parallel::detectCores() / 2)) # Use 50% cores
    info(logger, paste0("Using Multithreading: ", num_cores, " cores."))
    parallel::mclapply(clusters, worker_func, mc.cores = num_cores)
  } else {
    if(threads && .Platform$OS.type == "windows") warn(logger, "Multithreading not supported on Windows. Running sequentially.")
    info(logger, "Running sequentially...")
    lapply(clusters, worker_func)
  }
  
  info(logger, "DEG Analysis Completed.")
}

# ==============================================================================
# Special Function: Pairwise DEG (Control vs Treatment within a Cluster)
# ==============================================================================
DEG_Pairwise_Parallel <- function(obj, group_col, ident_1, ident_2, save_dir){
  # E.g. Compare 'Treatment' vs 'Control' for each 'CellType'
  
  # obj: Seurat object
  # group_col: Metadata column for clusters (e.g. "celltype")
  # ident_1: Treatment group name
  # ident_2: Control group name
  
  # Setup groups
  clusters <- unique(obj@meta.data[[group_col]])
  num_cores <- max(1, floor(parallel::detectCores() / 2))
  
  worker_func <- function(cluster){
    sub_obj <- subset(obj, cells = rownames(obj@meta.data)[obj@meta.data[[group_col]] == cluster])
    
    # Check if both idents exist in this cluster
    # Assuming the condition is in "orig.ident" or another column. 
    # Here we assume the user sets Idents(sub_obj) to the condition column before calling, 
    # OR we need the condition column name. 
    # Let's assume the user passes an object where we can select cells.
    
    # Better approach: Use FindMarkers on the subset
    # We need the condition column. Let's assume it's "group" based on original script context.
    condition_col <- "group" # Hardcoded based on legacy script logic, or pass as arg.
    
    if(!condition_col %in% colnames(sub_obj@meta.data)){
       warn(logger, paste0("Condition column '", condition_col, "' not found. Skipping ", cluster))
       return(NULL)
    }
    
    Idents(sub_obj) <- condition_col
    
    if(!ident_1 %in% unique(Idents(sub_obj)) || !ident_2 %in% unique(Idents(sub_obj))){
      # Skip if one group missing
      return(NULL) 
    }
    
    save_subdir <- file.path(save_dir, paste0("DEG-", cluster, "-", ident_1, "_vs_", ident_2))
    if(!dir.exists(save_subdir)) dir.create(save_subdir, recursive = TRUE)
    
    tryCatch({
      deg <- FindMarkers(sub_obj, ident.1 = ident_1, ident.2 = ident_2, verbose = FALSE)
      write.csv(deg, file.path(save_subdir, "DEG-Result.csv"))
      PlotVolcano(deg, name = paste0(cluster, ": ", ident_1, " vs ", ident_2), save_dir = save_subdir)
    }, error = function(e){
      warn(logger, paste0("Pairwise DEG failed for ", cluster, ": ", e$message))
    })
  }
  
  if (.Platform$OS.type != "windows"){
    mclapply(clusters, worker_func, mc.cores = num_cores)
  } else {
    lapply(clusters, worker_func)
  }
}
# ==============================================================================
# END 
# ==============================================================================
