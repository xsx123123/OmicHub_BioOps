# ==============================================================================
# Automated Cell Type Annotation (ScType & SingleR)
# Author: zhang jian
# Description: Modular functions for automated cell type annotation using 
#              ScType (marker-based) and SingleR (reference-based).
#              Optimized for flexibility, resource management, and multi-species support.
# ==============================================================================

# ==============================================================================
# Helper: Check Dependencies
# ==============================================================================
CheckAnnotationDeps <- function(){
  req_pkgs <- c("Seurat", "dplyr", "ggplot2", "HGNChelper", "openxlsx")
  # SingleR is Bioconductor, check separately if needed, but 'require' handles it
  missing <- req_pkgs[!sapply(req_pkgs, require, character.only = TRUE, quiet = TRUE)]
  if(length(missing) > 0) stop("Missing annotation dependencies: ", paste(missing, collapse=", "))
}

# ==============================================================================
# Module 1: ScType Annotation
# Description: Runs ScType scoring and assigns labels to clusters.
# ==============================================================================
RunScType <- function(data, ScTypeDB, tissue_list = c("Immune system"), save_dir, reduction = "umap"){
  
  CheckAnnotationDeps()
  # Load ScType functions source if not loaded (assuming they are in environment or sourced)
  # Ideally, these should be in a package or sourced explicitly. 
  # For now, we assume `gene_sets_prepare` and `sctype_score` are available.
  
  if(!exists("gene_sets_prepare") || !exists("sctype_score")) {
    stop("ScType helper functions (gene_sets_prepare, sctype_score) not found in environment.")
  }

  for (tissue in tissue_list){
    info(logger, paste0("Running ScType for tissue: ", tissue))
    
    # 1. Prepare Gene Sets
    # tryCatch to handle cases where tissue is not in DB
    gs_list <- tryCatch({
      gene_sets_prepare(ScTypeDB, tissue)
    }, error = function(e) {
      warn(logger, paste0("ScType preparation failed for ", tissue, ": ", e$message))
      return(NULL)
    })
    
    if(is.null(gs_list)) next
    
    # 2. Score Cells
    # Check scale.data availability
    if(sum(dim(data[["RNA"]]$scale.data)) == 0) {
      warn(logger, "Scale data missing. Running ScaleData...")
      data <- ScaleData(data, features = rownames(data))
    }
    
    es.max <- sctype_score(scRNAseqData = data[["RNA"]]$scale.data, scaled = TRUE,
                           gs = gs_list$gs_positive, gs2 = gs_list$gs_negative)
    
    # 3. Merge by Cluster
    cL_results <- do.call("rbind", lapply(unique(data@meta.data$seurat_clusters), function(cl){
      cluster_cells <- rownames(data@meta.data[data@meta.data$seurat_clusters == cl, ])
      es.max.cl <- sort(rowSums(es.max[, cluster_cells, drop=FALSE]), decreasing = TRUE)
      
      head(data.frame(cluster = cl, type = names(es.max.cl), scores = es.max.cl, 
                      ncells = length(cluster_cells)), 10)
    }))
    
    # 4. Top assignments
    sctype_scores <- cL_results %>% group_by(cluster) %>% top_n(n = 1, wt = scores)
    
    # Low confidence filter
    sctype_scores$type[as.numeric(as.character(sctype_scores$scores)) < sctype_scores$ncells/4] <- "Unknown"
    
    # 5. Save Results
    tissue_dir <- file.path(save_dir, gsub(" ", "_", tissue))
    if(!dir.exists(tissue_dir)) dir.create(tissue_dir, recursive = TRUE)
    
    write.csv(sctype_scores, file.path(tissue_dir, "ScType_Scores.csv"), row.names = FALSE)
    
    # 6. Assign to Seurat
    data@meta.data[[paste0("ScType_", gsub(" ", "_", tissue))]] <- ""
    for(j in unique(sctype_scores$cluster)){
      cl_type <- sctype_scores$type[sctype_scores$cluster == j]
      data@meta.data[[paste0("ScType_", gsub(" ", "_", tissue))]][data@meta.data$seurat_clusters == j] <- as.character(cl_type[1])
    }
    
    # 7. Plot
    p <- DimPlot(data, reduction = reduction, group.by = paste0("ScType_", gsub(" ", "_", tissue)), label = TRUE, repel = TRUE) +
      ggtitle(paste0("ScType: ", tissue)) + theme_classic()
    
    ggsave(file.path(tissue_dir, paste0("ScType_Annotation_", reduction, ".pdf")), plot = p, width = 12, height = 8)
    ggsave(file.path(tissue_dir, paste0("ScType_Annotation_", reduction, ".png")), plot = p, width = 12, height = 8, dpi = 1000)
  }
  
  return(data)
}

# ==============================================================================
# Module 2: SingleR Annotation (Unified)
# Description: Runs SingleR at Cluster or Cell level.
#              Supports auto-detection of cores and multi-reference.
# ==============================================================================
RunSingleR_Unified <- function(data, tax_ID, save_dir, level = "cluster", threads = NULL){

  # Read Reference RDS
  MouseImmGenref <- readRDS(file.path(PIPELINE_PATH,"Celldex/MouseImmGen.rds"))
  MouseRNAref <- readRDS(file.path(PIPELINE_PATH,"Celldex/MouseRNA.rds"))
  HuamnBlueprintEncode  <- readRDS(file.path(PIPELINE_PATH,"Celldex/HumanBlueprintEncode.rds"))
  HumanPrimaryCellAtla <- readRDS(file.path(PIPELINE_PATH,"Celldex/HumanPrimaryCellAtla.rds"))
  HumanDICEImmuneCell <- readRDS(file.path(PIPELINE_PATH,"Celldex/HumanDICEImmuneCell.rds"))
  HumanMonacoImmune <- readRDS(file.path(PIPELINE_PATH,"Celldex/HumanMonacoImmune.rds"))
  HumanNovershternHematopoietic <- readRDS(file.path(PIPELINE_PATH,"Celldex/HumanNovershternHematopoietic.rds"))

  if(!require(SingleR, quietly = TRUE)) {
    warn(logger, "SingleR package not installed. Skipping.")
    return(data)
  }
  if(!require(BiocParallel, quietly = TRUE)) library(BiocParallel)
  
  # Set Cores
  if(is.null(threads)) threads <- max(1, floor(parallel::detectCores()/2))
  
  # Determine References based on TaxID
  refs_to_use <- list()
 
  if(tax_ID == 10090){ # Mouse
    if(exists("MouseImmGenref")) refs_to_use[["ImmGen"]] <- MouseImmGenref
    if(exists("MouseRNAref")) refs_to_use[["MouseRNA"]] <- MouseRNAref
  } else if(tax_ID == 9606){ # Human
    if(exists("HuamnBlueprintEncode")) refs_to_use[["Blueprint"]] <- HuamnBlueprintEncode
    if(exists("HumanPrimaryCellAtla")) refs_to_use[["HPCA"]] <- HumanPrimaryCellAtla
    if(exists("HumanDICEImmuneCell")) refs_to_use[["DICE"]] <- HumanDICEImmuneCell
    if(exists("HumanMonacoImmune")) refs_to_use[["Monaco"]] <- HumanMonacoImmune
    if(exists("HumanNovershternHematopoietic")) refs_to_use[["Novershtern"]] <- HumanNovershternHematopoietic
  } else {
    warn(logger, paste0("TaxID ", tax_ID, " not supported for automated SingleR reference selection (Human/Mouse only). Skipping."))
    return(data)
  }
  
  if(length(refs_to_use) == 0) {
    warn(logger, "No SingleR reference objects found in environment.")
    return(data)
  }
  
  # Convert to SingleCellExperiment once
  sce_data <- as.SingleCellExperiment(data)
  
  for(ref_name in names(refs_to_use)){
    ref <- refs_to_use[[ref_name]]
    
    info(logger, paste0("Running SingleR (", level, " level) with reference: ", ref_name))
    
    # Run SingleR
    tryCatch({
      info(logger, paste0("  Processing SingleR for: ", ref_name, "..."))
      if(level == "cluster"){
        # cluster level
        pred <- with_logging(logger, {
          SingleR(test = sce_data, ref = ref, labels = ref$label.main, 
                  clusters = Idents(data), 
                  BPPARAM = MulticoreParam(workers = threads))
        }, level = "DEBUG")
      } else {
        # cell level
        pred <- with_logging(logger, {
          SingleR(test = sce_data, ref = ref, labels = ref$label.main, 
                  BPPARAM = MulticoreParam(workers = threads))
        }, level = "DEBUG")
      }
      
      qs::qsave(pred, file.path(save_dir, paste0("SingleR_temp_", ref_name, "_", level, ".qs")))
      # saveRDS(pred, file.path(save_dir, paste0("SingleR_", ref_name, "_", level, ".rds")))
      
      # Assign Labels
      # For cluster level, we need to map back
      label_col <- paste0("SingleR_", ref_name, "_", level)
      
      if(level == "cluster"){
        # Create a named vector mapping clusters to labels
        cluster_labels <- pred$labels
        names(cluster_labels) <- rownames(pred) # rownames are clusters
        
        # Map to cells
        data@meta.data[[label_col]] <- cluster_labels[as.character(Idents(data))]
      } else {
        data@meta.data[[label_col]] <- pred$labels
      }
      
      # Plot Diagnostics
      try({
        p_score <- plotScoreHeatmap(pred)
        ggsave(file.path(save_dir, paste0("SingleR_", ref_name, "_ScoreHeatmap.png")), plot = p_score, width = 10, height = 8, dpi = 1000)
      })

      cluster.ids <- pred$labels
      names(cluster.ids) <- levels(data)
      data <- RenameIdents(data, cluster.ids)
      data$Celltype <- Idents(data)
      
      qs::qsave(data@meta.data, file.path(save_dir, paste0("SingleR_meta.data_", ref_name, "_", level, ".qs")))

      
    }, error = function(e){
      error(logger, paste0("SingleR failed for ", ref_name, ": ", e$message))
    })
  }
  
  return(data)
}

# ==============================================================================
# Function: VisualizeAnnotation
# Description: Standardized plotting for annotation results.
# ==============================================================================
VisualizeAnnotation <- function(data, group_by, save_dir, prefix, reduction = "umap"){
  
  if(!group_by %in% colnames(data@meta.data)){
    warn(logger, paste0("Group ", group_by, " not found in metadata. Skipping plot."))
    return()
  }
  
  # Validate requested reduction; fall back to an available UMAP/tSNE reduction if missing
  available_reductions <- names(data@reductions)
  if(!reduction %in% available_reductions){
    fallback <- available_reductions[grep("^umap", available_reductions, ignore.case = TRUE)][1]
    if(is.na(fallback)){
      fallback <- available_reductions[grep("^tsne|^(tSNE|tsne)$", available_reductions, ignore.case = TRUE)][1]
    }
    if(!is.na(fallback)){
      warn(logger, paste0("Reduction '", reduction, "' not found in object. Using '", fallback, "' instead for ", group_by, "."))
      reduction <- fallback
    } else {
      warn(logger, paste0("No suitable UMAP/tSNE reduction found for plotting ", group_by, ". Skipping plot."))
      return()
    }
  }
  
  p <- DimPlot(data, reduction = reduction, group.by = group_by, label = TRUE, repel = TRUE) +
    ggtitle(paste0("Annotation: ", group_by)) + theme_classic() +
    theme(legend.position = "bottom")
  
  ggsave(file.path(save_dir, paste0(prefix, "_", group_by, "_", reduction, ".pdf")), plot = p, width = 10, height = 8)
  ggsave(file.path(save_dir, paste0(prefix, "_", group_by, "_", reduction, ".png")), plot = p, width = 10, height = 8, dpi = 1000)
}

# ==============================================================================
# Module 3: Find Cluster Markers & DotPlot (Optimized)
# ==============================================================================
AutoFindMarkersAndDotPlot <- function(data, group_by, save_dir, top_n = 5){
  
  if(!require(scCustomize, quietly = TRUE)) library(scCustomize)
  
  info(logger, "Finding all markers for DotPlot...")
  
  # Find All Markers
  Idents(data) <- group_by
  markers <- FindAllMarkers(data, only.pos = TRUE, min.pct = 0.25, logfc.threshold = 0.25, verbose = FALSE)
  
  if(nrow(markers) == 0) {
    warn(logger, "No markers found.")
    return()
  }
  
  # Top N
  top_markers <- markers %>% group_by(cluster) %>% top_n(n = top_n, wt = avg_log2FC)
  
  write.csv(top_markers, file.path(save_dir, "Top_Cluster_Markers.csv"))
  
  # Plot
  p <- DotPlot_scCustom(seurat_object = data, features = unique(top_markers$gene), group.by = group_by,
                        colors_use = viridis_plasma_dark_high) +
       theme(axis.text.x = element_text(angle = 45, hjust = 1))
  
  # Dynamic size
  w <- max(8, length(unique(top_markers$gene)) * 0.2)
  h <- max(6, length(unique(data@meta.data[[group_by]])) * 0.4)
  
  ggsave(file.path(save_dir, "Annotation_DotPlot.pdf"), plot = p, width = w, height = h)
  ggsave(file.path(save_dir, "Annotation_DotPlot.png"), plot = p, width = w, height = h, dpi = 1000)
}
# ==============================================================================
# END 
# ==============================================================================
