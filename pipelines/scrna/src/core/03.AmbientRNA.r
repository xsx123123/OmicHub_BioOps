# ==============================================================================
# Ambient RNA Contamination Analysis (DecontX)
# Author: zhang jian
# Description: Uses 'celda::decontX' to estimate and remove ambient RNA contamination.
#              Provides visualization of contamination scores on UMAP.
#              Optimized for Plants (handles missing MT% gracefully).
# ==============================================================================

# ==============================================================================
# Function: AmbientRNAContamination
# Description: Runs decontX on the Seurat object to estimate contamination fractions.
# Parameters:
#   data: Seurat object.
#   savedir: Directory to save the intermediate RDS file.
# ==============================================================================
AmbientRNAContamination <- function(data, savedir){
  
  # 检查celda包是否安装，decontX功能需要此包
  if(!require(celda, quietly = TRUE)){
    error(logger, "  Package 'celda' is required for Ambient RNA removal but not installed.")
    stop("Missing dependency: celda")
  }

  info(logger, "  Starting Ambient RNA estimation using decontX...")
  
  tryCatch({
    # 提取计数矩阵数据，支持特定assay，默认为RNA
    # 这里获取的是原始 counts 数据，用于decontX分析
    counts <- GetAssayData(data, assay = "RNA", layer = "counts")
    
    info(logger, paste0("  Extracted counts matrix dimensions: ", dim(counts)[1], " genes × ", dim(counts)[2], " cells"))
    
    # 运行decontX算法进行ambient RNA污染估计
    # decontX对稀疏矩阵处理效果良好
    decontX_results <- decontX(counts)
    
    info(logger, "  decontX algorithm completed successfully")
    
    # 将污染估计结果存储到metadata中
    data$Contamination <- decontX_results$contamination
    
    # 记录平均污染水平和基本统计信息
    avg_contamination <- round(mean(data$Contamination), 4)
    max_contamination <- round(max(data$Contamination), 4)
    min_contamination <- round(min(data$Contamination), 4)
    
    info(logger, paste0("  decontX finished. Average contamination: ", avg_contamination))
    info(logger, paste0("  Contamination range: ", min_contamination, " - ", max_contamination))
    
    # 统计高污染细胞数量
    high_contam_cells <- sum(data$Contamination > 0.2)
    total_cells <- length(data$Contamination)
    high_contam_rate <- round((high_contam_cells / total_cells) * 100, 2)
    
    info(logger, paste0("  High contamination cells (>0.2): ", high_contam_cells, "/", total_cells, " (", high_contam_rate, "%)"))
    
    info(logger, paste0("  decontX finished. Average contamination: ", avg_contamination))
    
    # 保存中间结果到RDS文件，便于后续分析使用
    save_path <- file.path(savedir, paste0(project_name, "_decontX_results.qs"))
    qs::qsave(data, save_path)
    info(logger, paste0("  Saved DecontX results to: ", save_path))
    
  }, error = function(e){
    # 错误处理，decontX失败时的处理
    error(logger, paste0("  decontX failed: ", e$message))
    stop(e)
  })
  
  return(data)
}

# ==============================================================================
# Function: DrawAmbientRNAContamination_UMAP
# Description: Wrapper to route plotting based on integration method.
# ==============================================================================
DrawAmbientRNAContamination_UMAP <- function(Ambient, RNAContamination_dir, intergetmethods){
  
  # 设置默认的降维方法
  reduction_use <- "umap" # Default
  
  # 根据不同的整合方法选择合适的UMAP降维结果
  if (intergetmethods %in% c('CCA', 'ALL')){
    reduction_use <- "umap.cca"
    info(logger, paste0("  Using CCA integration UMAP: ", reduction_use))
  } else if (intergetmethods == 'Harmony'){
    reduction_use <- "umap.harmony"
    info(logger, paste0("  Using Harmony integration UMAP: ", reduction_use))
  } else {
    info(logger, paste0("  Using default UMAP: ", reduction_use))
  }
  
  # 检查指定的降维方法是否存在，如果不存在则回退到默认的'umap'
  if (!reduction_use %in% names(Ambient@reductions)) {
    warn(logger, paste0("  Reduction '", reduction_use, "' not found. Falling back to 'umap'."))
    reduction_use <- "umap"
    debug(logger, paste0("  Fallback to default UMAP: ", reduction_use))
  }
  
  info(logger, paste0("  Proceeding with reduction: ", reduction_use))
  
  # 调用主要的绘图函数
  DrawAmbientRNAContamination(Ambient, RNAContamination_dir, reduction_use)
}

# ==============================================================================
# Function: DrawAmbientRNAContamination
# Description: Generates a 4-panel QC plot:
#              A. Contamination Score
#              B. Clusters
#              C. Sample ID
#              D. Mito % (or Gene Count for Plants)
# ==============================================================================
DrawAmbientRNAContamination <- function(data, savedir, reduction){
  
  if(!require(patchwork, quietly = TRUE)) library(patchwork)
  if(!require(ggplot2, quietly = TRUE)) library(ggplot2)
  if(!require(dplyr, quietly = TRUE)) library(dplyr)
  
  contamination_threshold <- 0.2
  total_cells <- ncol(data)
  contam_cells <- sum(data$Contamination > contamination_threshold)
  rate <- round((contam_cells / total_cells) * 100, 2)
  
  info(logger, paste0("  Plotting setup: ", total_cells, " cells, ", contam_cells, " high-contamination cells (>0.2)"))
  info(logger, paste0("  Using reduction: ", reduction))
  
  info(logger, paste0("  Plotting DecontX results. High contamination cells (>0.2): ", rate, "%"))
  
  p1 <- FeaturePlot(data, features = 'Contamination', 
                    reduction = reduction,
                    raster = TRUE,
                    pt.size = 2) + 
    scale_color_viridis_c(option = "magma", direction = -1) +
    labs(title = "Ambient RNA Score",
         color = "Score",
         subtitle = paste0("Contaminated Cells (>0.2): ", contam_cells, " (", rate, "%)"),
         x = paste0(toupper(reduction), "-1"), y = paste0(toupper(reduction), "-2")) +
    theme_pubclean() +
    theme(plot.title = element_text(hjust = 0.5, face = "bold"),
          plot.subtitle = element_text(hjust = 0.5, color = "red", size = 9),
          legend.position = 'bottom')
  
  p2 <- DimPlot(data, group.by = "seurat_clusters",
                reduction = reduction,
                label = TRUE, label.size = 4) +
    labs(title = "Seurat Clusters", x = paste0(toupper(reduction), "-1"), y = paste0(toupper(reduction), "-2")) + 
    theme_pubclean() +
    theme(plot.title = element_text(hjust = 0.5, face = "bold"),
          legend.position = 'none')
  
  p3 <- DimPlot(data, group.by = "orig.ident",
                reduction = reduction) + 
    labs(title = "Sample ID", x = paste0(toupper(reduction), "-1"), y = paste0(toupper(reduction), "-2")) + 
    theme_pubclean() +
    theme(plot.title = element_text(hjust = 0.5, face = "bold"),
          legend.position = "bottom")
  

  has_mt <- any(data$percent.mt > 0)
  
  if (has_mt) {
    info(logger, "  Detected mitochondrial data (Animal/Human mode)")
    p4 <- FeaturePlot(data, features = 'percent.mt', reduction = reduction) +
      scale_color_gradient2(low = "grey90", mid = "white", high = "red", midpoint = 10, limits = c(0, 100)) +
      labs(title = "Mitochondrial %",
           color = "MT %",
           x = paste0(toupper(reduction), "-1"), y = paste0(toupper(reduction), "-2")) +
      theme_pubclean() +
      theme(plot.title = element_text(hjust = 0.5, face = "bold"),
            legend.position = 'bottom')
  } else {
    
    info(logger, "  No mitochondrial expression detected (Plant/Other mode)")
    p4 <- FeaturePlot(data, features = 'nFeature_RNA', reduction = reduction) +
      scale_color_viridis_c(option = "viridis") +
      labs(title = "Gene Count (nFeature)",
           color = "Count",
           subtitle = "MT% is 0, showing Gene Count",
           x = paste0(toupper(reduction), "-1"), y = paste0(toupper(reduction), "-2")) +
      theme_pubclean() +
      theme(plot.title = element_text(hjust = 0.5, face = "bold"),
            legend.position = 'bottom',
            legend.text = element_text(angle = 45,hjust = 0.99,vjust = 0.99))
  }

  combined_plot <- p1 + p2 + p3 + p4 + 
    patchwork::plot_layout(ncol = 2,nrow = 2) +
    patchwork::plot_annotation(
      title = "Ambient RNA Decontamination Overview",
      tag_levels = "A",
      theme = theme(plot.title = element_text(size = 16, face = "bold", hjust = 0.5))
    )
  
  pdf_path <- file.path(savedir, "AmbientRNAContamination.pdf")
  png_path <- file.path(savedir, "AmbientRNAContamination.png")
  
  ggsave(pdf_path, width = 12, height = 10, plot = combined_plot, device = "pdf")
  ggsave(png_path, width = 12, height = 10, plot = combined_plot, device = "png", dpi = 300)
  
  info(logger, paste0("  Saved plots to: ", pdf_path, " and ", png_path))
  
  return(combined_plot)
}
# ==============================================================================
# END 
# ==============================================================================
