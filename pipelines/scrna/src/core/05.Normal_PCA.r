# ==============================================================================
# Normalization & Dimensionality Reduction (PCA) Functions
# Author: zhang jian
# Description: Handles data normalization (Standard vs SCTransform), variable feature selection,
#              PCA calculation, and automatic PC cutoff determination.
#              Optimized for SCTransform support and Plant analysis.
# ==============================================================================

# ==============================================================================
# Function: NormalFeature
# Description: Performs normalization and feature selection on a list of Seurat objects.
#              Supports both 'Standard' (LogNormalize) and 'SCT' (SCTransform) methods.
# Parameters:
#   PatchDeallist: List of Seurat objects.
#   method: "Standard" (default) or "SCT".
#   vars.to.regress: Variables to regress out (e.g., "percent.mt"). Automatically adjusted if var is constant.
# ==============================================================================
NormalFeature <- function(PatchDeallist, method = "Standard", vars.to.regress = "percent.mt"){
  
  if(!require(Seurat, quietly = TRUE)) stop("Package 'Seurat' not installed.")
  if(!require(sctransform, quietly = TRUE)) warn(logger, "  Package 'sctransform' might be needed for SCT method.")
  
  processed_list <- list()
  
  for (i in seq_along(PatchDeallist)) {
    obj <- PatchDeallist[[i]]
    sample_name <- unique(as.character(obj$orig.ident))[1]
    info(logger, paste0("  Normalizing Sample: ", sample_name, " | Method: ", method))
    
    # Check if vars.to.regress exists and has variance
    # For plants, percent.mt might be all 0.
    valid_regress_vars <- c()
    if(!is.null(vars.to.regress)){
      for(v in vars.to.regress){
        if(v %in% colnames(obj@meta.data)){
          if(var(obj@meta.data[[v]], na.rm = TRUE) > 0){
            valid_regress_vars <- c(valid_regress_vars, v)
          } else {
             warn(logger, paste0("  Variable '", v, "' has zero variance (e.g. Plant MT%). Skipping regression for this variable."))
          }
        }
      }
    }
    
    if (method == "SCT") {
      # SCTransform replaces NormalizeData, ScaleData, and FindVariableFeatures
      # It creates a new assay 'SCT'
      tryCatch({
        obj <- SCTransform(obj, vars.to.regress = valid_regress_vars, verbose = FALSE, vst.flavor = "v2")
        info(logger, "   SCTransform completed.")
      }, error = function(e) {
        error(logger, paste0("  SCTransform failed for ", sample_name, ": ", e$message))
        # Fallback to Standard? Or stop? Let's stop to be safe.
        stop("SCTransform failed.")
      })
      
    } else {
      # Standard Workflow: LogNormalize -> FindVariableFeatures
      obj <- NormalizeData(obj, normalization.method = "LogNormalize", scale.factor = 10000, verbose = FALSE)
      
      warn(logger, paste0("  Finding 2000 Variable Features (VST)..."))
      obj <- FindVariableFeatures(obj, selection.method = "vst", nfeatures = 2000, verbose = FALSE)
      
      # Note: ScaleData usually happens BEFORE PCA, often on all genes or var features.
      # Here we typically run ScaleData just on VariableFeatures to save memory before PCA.
      # But usually ScaleData is run separately before RunPCA. 
      # To keep this function focused on "Normalization & Features", we can optionally run ScaleData here 
      # or leave it for the PCA step. 
      # Most pipelines run ScaleData right before PCA.
      # However, for consistency with the previous script structure, let's keep it minimal here.
    }
    
    processed_list[[i]] <- obj
  }
  
  return(processed_list)
}

# ==============================================================================
# Function: RunPCA_Wrapper
# Description: Helper function to streamline the ScaleData and RunPCA steps.
#              It automatically checks the default assay:
#              - For 'RNA': Runs ScaleData on VariableFeatures before PCA.
#              - For 'SCT': Directly runs PCA (as scaling is implicit in SCT).
# @ obj : Seurat object.
# @ npcs : Number of principal components to compute (default: 50).
# ==============================================================================
RunPCA_Wrapper <- function(obj, npcs = 50){
  # Check Default Assay
  assay_use <- DefaultAssay(obj)
  
  # For Standard assay (RNA), ScaleData is needed if not done.
  # For SCT, ScaleData is implicit in SCTransform (residulas are scaled), but RunPCA uses 'scale.data' slot.
  
  if(assay_use == "RNA") {
    # If scale.data slot is empty or incomplete, run ScaleData
    # Usually we scale variable features
    features <- VariableFeatures(obj)
    obj <- ScaleData(obj, features = features, verbose = FALSE)
  }
  
  info(logger, paste0("  Running PCA on assay: ", assay_use))
  obj <- RunPCA(obj, npcs = npcs, verbose = FALSE)
  return(obj)
}

# ==============================================================================
# Function: AutoSettingPcCutoff
# Description: Automatically determines the optimal PC cutoff for downstream analysis.
#              It uses two heuristic methods based on variance explained:
#              1. Cumulative variance > 90% AND single PC variance < 5%.
#              2. The 'elbow' point where the drop in variance stabilizes (< 0.1%).
#              Generates a custom visualization of cumulative variance.
# @ data : Seurat object with PCA computed.
# @ plot_name : Title prefix for the generated plots.
# @ save_dir : Directory to save the plots.
# ==============================================================================
AutoSettingPcCutoff <- function(data, plot_name, save_dir){
  
  # Calculate variance explained
  # stdev is in the 'pca' reduction object
  stdev <- data[["pca"]]@stdev
  pct <- stdev^2 / sum(stdev^2) * 100 # Correct calculation is Variance / Sum(Variance), stdev^2 = Variance
  # Note: The original script used stdev / sum(stdev), which is technically incorrect for % Variance Explained,
  # but widely used in heuristic elbow plots. Seurat's ElbowPlot uses stdev directly.
  # Let's stick to % Variance for the cumulative logic.
  
  cumu <- cumsum(pct)
  
  # Logic 1: Cumulative variance > 90% AND single PC variance < 5% (heuristic)
  co1 <- which(cumu > 90 & pct < 5)[1]
  
  # Logic 2: Difference between consecutive PCs < 0.1% (flattening point)
  # Find last point where drop is significant (> 0.1%)
  diffs <- pct[1:(length(pct)-1)] - pct[2:length(pct)]
  co2 <- sort(which(diffs > 0.1), decreasing = TRUE)[1] + 1
  
  # Handle NAs if criteria not met
  if(is.na(co1)) co1 <- 50
  if(is.na(co2)) co2 <- 10
  
  pcs <- min(max(co1, co2), 50) # Conservative max
  
  # Visual Dataframe
  plot_df <- data.frame(pct = pct, cumu = cumu, rank = 1:length(pct))
  
  # Plot
  p3 <- ggplot(plot_df, aes(cumu, pct, label = rank, color = rank > pcs)) +
    ggtitle(paste0(plot_name, " PCA Cutoff Selection")) +
    xlab("Cumulative Variance (%)") +
    ylab("Variance Explained per PC (%)") +
    geom_point() + 
    geom_text(vjust = -0.5, size = 3) +
    geom_vline(xintercept = plot_df$cumu[pcs], color = "red", linetype = "dashed") +
    annotate("text", x = plot_df$cumu[pcs], y = max(pct), label = paste0("Cutoff: PC", pcs), color = "red", vjust = 2) +
    theme_classic() +
    theme(legend.position = "none", plot.title = element_text(hjust = 0.5, face="bold"))
    
  ggsave(file.path(save_dir, paste0(plot_name, "-PCT-ElbowPlot.pdf")), width = 7, height = 4, plot = p3)
  ggsave(file.path(save_dir, paste0(plot_name, "-PCT-ElbowPlot.png")), width = 7, height = 4, plot = p3, dpi = 300)
  
  info(logger, paste0("  Optimal PCA Cutoff for ", plot_name, " is : ", pcs))
  return(pcs)
}

# ==============================================================================
# Function: DrawElbowPlot
# Description: Wrapper function that ensures PCA is run, calculates the optimal 
#              PC cutoff using 'AutoSettingPcCutoff', and generates a standard 
#              Seurat ElbowPlot with the cutoff line annotated.
# @ data : Seurat object.
# @ plot_name : Title prefix for the generated plots.
# @ save_dir : Directory to save the plots.
# ==============================================================================
DrawElbowPlot <- function(data, plot_name, save_dir){
  
  # Ensure PCA exists
  if (!"pca" %in% names(data@reductions)){
     data <- RunPCA_Wrapper(data)
  }

  pcs <- AutoSettingPcCutoff(data, plot_name, save_dir)
  
  # Standard Seurat Elbow Plot (SD based)
  p1 <- ElbowPlot(data, ndims = 50, reduction = "pca") +
    ggtitle(paste0(plot_name, " Elbow Plot")) +
    geom_vline(xintercept = pcs, color = "red", linetype = "dashed") +
    annotate("text", x = pcs + 5, y = data[["pca"]]@stdev[1], label = paste0("Cutoff: ", pcs), color = "red") +
    theme_classic() +
    theme(plot.title = element_text(hjust = 0.5, face = "bold"))
    
  ggsave(file.path(save_dir, paste0(plot_name, "-Standard-ElbowPlot.pdf")), width = 6, height = 4, plot = p1)
  ggsave(file.path(save_dir, paste0(plot_name, "-Standard-ElbowPlot.png")), width = 6, height = 4, plot = p1, dpi = 300)
  
  return(pcs)
}
# ==============================================================================
# END 
# ==============================================================================
