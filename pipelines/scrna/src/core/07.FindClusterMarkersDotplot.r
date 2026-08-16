# ==============================================================================
# Cluster Markers Analysis and Dotplot Visualization
# Author: zhang jian
# Date: 2024-12-25
# Version: 1.1v (Optimized)
# Description: Uses Seurat FindMarkers for differential expression analysis,
#              filters by pct.1 > 0.25, and generates marker dotplots
#              Supports multiple resolutions with integrated plotting
# ==============================================================================

# ==============================================================================
# Function: FindClusterMarkers
# Description: Performs FindAllMarkers analysis and filters for top marker genes
# Parameters:
#   Seurat_obj: Seurat object
#   group_by: metadata column for grouping (default: 'Celltype')
#   save_dir: directory to save results (default: './')
#   test: statistical test method (default: "wilcox")
#   topgene: number of top genes to select per cluster (default: 30)
# Returns:
#   A data frame containing the filtered top markers
# ==============================================================================
FindClusterMarkers <- function(Seurat_obj, 
                               intergetmethods = "Harmony", # Harmony,CCA
                               save_dir = './',
                               test = "wilcox",
                               topgene = 30) {
  
  # 1. 验证必需包
  required_packages <- c("Seurat", "dplyr")
  for (pkg in required_packages) {
    if (!requireNamespace(pkg, quietly = TRUE)) {
      stop(paste("Required package not found:", pkg))
    }
  }

  if (intergetmethods %in% c('CCA', 'ALL')) {
    group_by <- 'cca_clusters'
    debug(logger, "Using CCA integration method")
  } else if (intergetmethods == 'Harmony') {
    group_by <- 'harmony_clusters'
    debug(logger, "Using Harmony integration method")
  } else {
    stop(paste("Unsupported integration method:", intergetmethods))
  }
  
  debug(logger, paste0("Starting FindClusterMarkers analysis for group_by: ", group_by))
  debug(logger, paste0("Test method: ", test, ", Target top genes per cluster: ", topgene))
  
  # 参数验证
  if (!group_by %in% colnames(Seurat_obj@meta.data)) {
    stop(paste("Group column not found in metadata:", group_by))
  }
  
  # 创建保存目录
  if (!dir.exists(save_dir)) {
    dir.create(save_dir, recursive = TRUE, showWarnings = FALSE)
    debug(logger, paste0("Created directory: ", save_dir))
  }
  
  # 2. 设置聚类标签
  Idents(Seurat_obj) <- group_by
  
  # 3. 寻找所有 Marker 基因
  debug(logger, "Running FindAllMarkers... This might take a while depending on data size.")
  
  all_markers <- tryCatch({
    FindAllMarkers(Seurat_obj,
                   only.pos = TRUE,           
                   min.pct = 0.25,            
                   logfc.threshold = 0.5,     
                   test.use = test)
  }, error = function(e) {
    error(logger, paste0("FindAllMarkers failed: ", e$message))
    return(NULL)
  })
  
  if (is.null(all_markers) || nrow(all_markers) == 0) {
    warn(logger, "No markers found across all clusters.")
    return(NULL)
  }
  
  # 4. 筛选 Top 基因
  # 策略：先过滤显著性，再取 FC 前 200 确保特异性，最后取 pct.1 前 topgene 确保稳定性
  debug(logger, "Filtering and selecting top genes...")
  top_markers <- all_markers |>
    dplyr::group_by(cluster) |>
    dplyr::filter(p_val_adj < 0.05 & avg_log2FC > 0.5 & pct.1 > 0.25) |>
    dplyr::slice_max(n = 200, order_by = avg_log2FC, with_ties = FALSE) |>
    dplyr::slice_max(n = topgene, order_by = pct.1, with_ties = FALSE) |>
    dplyr::ungroup()
  
  # 5. 保存结果到 CSV
  # 使用 group_by 变量名命名文件，避免同目录运行不同分组时发生覆盖
  marker_file <- file.path(save_dir, paste0(group_by, '_marker_list.csv'))
  write.csv(top_markers, marker_file, row.names = FALSE)
  
  debug(logger, paste0("Saved ", nrow(top_markers), " top markers to: ", marker_file))
  debug(logger, "Marker identification and filtering completed!")

  return(top_markers)
}


# ==============================================================================
# Function: FindClusterMarkersDotplot
# Description: Performs differential expression analysis and creates dotplot visualization
# Parameters:
#   Seurat: Seurat object
#   group_by: metadata column for grouping (default: 'Celltype')
#   NAME: name prefix for output files
#   save_dir: directory to save results
#   test: statistical test method (default: "wilcox")
#   topgene: number of top genes per cluster (default: 5)
#   color: color palette for visualization
# ==============================================================================
FindClusterMarkersDotplot <- function(Seurat, group_by = 'Celltype',
                                     NAME = 'MARKER',
                                     save_dir = './',
                                     test = "wilcox",
                                     topgene = 5,
                                     color = viridis_plasma_dark_high) {
  
  # 验证必需包是否加载
  required_packages <- c("scCustomize", "ggplot2", "Seurat", "dplyr")
  for (pkg in required_packages) {
    if (!requireNamespace(pkg, quietly = TRUE)) {
      stop(paste("Required package not found:", pkg))
    }
  }
  
  debug(logger, paste0("Starting FindClusterMarkersDotplot for group_by: ", group_by))
  debug(logger, paste0("Test method: ", test, ", Top genes per cluster: ", topgene))
  
  # 参数验证
  if (!group_by %in% colnames(Seurat@meta.data)) {
    stop(paste("Group column not found in metadata:", group_by))
  }
  
  # 创建保存目录（如果不存在）
  if (!dir.exists(save_dir)) {
    dir.create(save_dir, recursive = TRUE, showWarnings = FALSE)
    debug(logger, paste0("Created directory: ", save_dir))
  }
  
  # 初始化结果数据框
  marker_list <- data.frame(group = character(),
                            gene = character(),
                            avg_log2FC = numeric(),
                            pct.1 = numeric(),
                            pct.2 = numeric(),
                            p_val = numeric(),
                            stringsAsFactors = FALSE)
  
  # 获取细胞类型水平
  cell_types <- levels(factor(Seurat@meta.data[[group_by]]))
  debug(logger, paste0("Found ", length(cell_types), " cell types to analyze"))
  
  # 为每个细胞类型进行差异表达分析
  for (i in seq_along(cell_types)) {
    current_type <- cell_types[i]
    
    debug(logger, paste0("Processing cell type ", i, "/", length(cell_types), ": ", current_type))
    
    tryCatch({
      # 定义比较组：当前类型 vs 所有其他类型
      cells1 <- rownames(subset(Seurat@meta.data, get(group_by) == current_type))
      cells2 <- rownames(subset(Seurat@meta.data, get(group_by) != current_type))
      
      debug(logger, paste0("  Cell group 1: ", length(cells1), " cells"))
      debug(logger, paste0("  Cell group 2: ", length(cells2), " cells"))
      
      # 检查是否有足够的细胞进行分析
      if (length(cells1) < 3 || length(cells2) < 3) {
        warn(logger, paste0("Insufficient cells for analysis in group: ", current_type))
        next
      }
      
      # 执行差异表达分析
      temp_marker <- FindMarkers(Seurat,
                                ident.1 = cells1, 
                                ident.2 = cells2,
                                only.pos = TRUE,            # 优化1：只计算上调基因
                                min.pct = 0.25,             # 优化2：增加表达比例过滤
                                max.cells.per.ident = 1000, # 优化3：终极杀招，开启降采样
                                logfc.threshold = log(2),
                                test.use = test)
      
      debug(logger, paste0("  Found ", nrow(temp_marker), " total markers"))
      
      # 应用过滤条件：pct.1 > 0.25 并按avg_log2FC排序
      # temp_marker_filtered <- temp_marker %>% 
      #   arrange(-avg_log2FC) %>% 
      #   filter(pct.1 > 0.25) %>% 
      #   dplyr::slice_head(n = topgene)

      # new marker gene filter
      temp_marker_filtered <- temp_marker |>
        dplyr::filter(p_val_adj < 0.05 & avg_log2FC > 0.5 & pct.1 > 0.25) |>
        dplyr::slice_max(n = 200, order_by = avg_log2FC) |>
        dplyr::slice_max(n = topgene, order_by = pct.1) 

      debug(logger, paste0("  After filtering (pct.1 > 0.25): ", nrow(temp_marker_filtered), " markers"))
      
      # 添加到总结果
      if (nrow(temp_marker_filtered) > 0) {
        temp_result <- data.frame(
          group = current_type,
          gene = rownames(temp_marker_filtered),
          avg_log2FC = temp_marker_filtered$avg_log2FC,
          pct.1 = temp_marker_filtered$pct.1,
          pct.2 = temp_marker_filtered$pct.2,
          p_val = temp_marker_filtered$p_val,
          stringsAsFactors = FALSE
        )
        marker_list <- rbind(marker_list, temp_result)
      }
      
    }, error = function(e) {
      error(logger, paste0("Failed to process cell type ", current_type, ": ", e$message))
      next
    })
  }
  
  # 保存标记基因列表
  if (nrow(marker_list) > 0) {
    marker_file <- file.path(save_dir, paste0(NAME, '_marker_list.csv'))
    write.csv(marker_list, marker_file, row.names = FALSE)
    debug(logger, paste0("Saved ", nrow(marker_list), " markers to: ", marker_file))
  } else {
    warn(logger, "No markers found after filtering")
  }
  
  # 生成dotplot
  unique_genes <- unique(marker_list$gene)
  debug(logger, paste0("Creating dotplot with ", length(unique_genes), " unique genes"))
  
  if (length(unique_genes) == 0) {
    warn(logger, "No genes available for dotplot generation")
    return(NULL)
  }
  
  p <- DotPlot_scCustom(seurat_object = Seurat,
                        features = unique_genes,
                        group.by = group_by,
                        colors_use = color) +
    theme(axis.text.x = element_text(angle = 45, vjust = 0.9, hjust = 0.9))
  
  debug(logger, paste0("Dotplot generation completed for: ", NAME))
  return(p)
}

# ==============================================================================
# Function: draw_res_DimPlot
# Description: Creates comprehensive visualization of multiple resolutions
# Parameters:
#   integrated_obj: Seurat object with multiple resolutions
#   reduceType: dimensionality reduction type
#   intergetmethods: integration method (CCA, Harmony, or ALL)
#   figure_dir: directory to save figures
#   cluster_marker_gene_dir: directory to save marker gene results
# ==============================================================================
draw_res_DimPlot <- function(integrated_obj, 
                             intergetmethods = ctx$intergetmethods, 
                             figure_dir,
                             cluster_marker_gene_dir) {
  
  debug(logger, paste0("Starting draw_res_DimPlot with integration method: ", intergetmethods))
  
  # 验证输入参数
  if (!inherits(integrated_obj, "Seurat")) {
    stop("Input must be a Seurat object")
  }
  
  # 根据整合方法设置降维参数
  if (intergetmethods %in% c('CCA', 'ALL')) {
    reduction_umap <- 'umap.cca'
    resolutions <- list(
      list(res = 0.6, name = "cca_clusters_res_0.6"),
      list(res = 0.8, name = "cca_clusters_res_0.8"),
      list(res = 1.2, name = "cca_clusters_res_1.2"),
      list(res = 2.0, name = "cca_clusters_res_2")
    )
    debug(logger, "Using CCA integration method")
  } else if (intergetmethods == 'Harmony') {
    reduction_umap <- 'umap.harmony'
    resolutions <- list(
      list(res = 0.6, name = "harmony_clusters_res_0.6"),
      list(res = 0.8, name = "harmony_clusters_res_0.8"),
      list(res = 1.2, name = "harmony_clusters_res_1.2"),
      list(res = 2.0, name = "harmony_clusters_res_2")
    )
    debug(logger, "Using Harmony integration method")
  } else {
    stop(paste("Unsupported integration method:", intergetmethods))
  }
  
  # 验证降维是否存在
  if (!reduction_umap %in% names(integrated_obj@reductions)) {
    stop(paste("Reduction not found:", reduction_umap))
  }
  
  debug(logger, paste0("Using reduction: ", reduction_umap))
  
  # 创建保存目录
  if (!dir.exists(figure_dir)) {
    dir.create(figure_dir, recursive = TRUE, showWarnings = FALSE)
  }
  if (!dir.exists(cluster_marker_gene_dir)) {
    dir.create(cluster_marker_gene_dir, recursive = TRUE, showWarnings = FALSE)
  }
  
  # 生成UMAP DimPlot (4个resolution的对比)
  debug(logger, "Generating UMAP DimPlots for all resolutions...")
  
  plots_list <- list()
  for (i in seq_along(resolutions)) {
    res_info <- resolutions[[i]]
    res_name <- res_info$name
    
    debug(logger, paste0("Processing resolution ", res_info$res, ": ", res_name))
    
    # 检查该resolution的聚类结果是否存在
    if (!res_name %in% colnames(integrated_obj@meta.data)) {
      warn(logger, paste0("Resolution not found in metadata: ", res_name))
      next
    }
    
    # 获取聚类数量
    n_clusters <- length(unique(integrated_obj@meta.data[[res_name]]))
    debug(logger, paste0("Found ", n_clusters, " clusters in ", res_name))
    
    # 创建DimPlot
    plots_list[[i]] <- DimPlot_scCustom(integrated_obj,
                                       reduction = reduction_umap,
                                       group.by = res_name,
                                       label = TRUE) + NoLegend() +
      labs(title = paste0("Resolution ", res_info$res)) +
      theme(plot.title = element_text(hjust = 0.5, face = "bold"))
  }
  
  # 组合DimPlot
  if (length(plots_list) == 4) {
    combined_dimplot <- plots_list[[1]] + plots_list[[2]] + plots_list[[3]] + plots_list[[4]] +
      plot_layout(nrow = 2, ncol = 2)
    
    # 保存DimPlot
    dimplot_file_png <- file.path(figure_dir, "DimPlotUMAP_res_0.6_0.8_1.2_2.png")
    dimplot_file_pdf <- file.path(figure_dir, "DimPlotUMAP_res_0.6_0.8_1.2_2.pdf")
    
    ggsave(dimplot_file_png, plot = combined_dimplot, width = 10, height = 10, dpi = 1000)
    ggsave(dimplot_file_pdf, plot = combined_dimplot, width = 10, height = 10, dpi = 1000)
    
    debug(logger, paste0("Saved combined DimPlot to: ", dimplot_file_png))
  } else {
    warn(logger, paste0("Only ", length(plots_list), "/4 resolutions found. Skipping combined DimPlot."))
  }
  
  # 为每个resolution生成标记基因dotplot
  debug(logger, "Generating marker gene dotplots for each resolution...")
  
  for (res_info in resolutions) {
    res_name <- res_info$name
    
    if (!res_name %in% colnames(integrated_obj@meta.data)) {
      warn(logger, paste0("Skipping ", res_name, ": not found in metadata"))
      next
    }
    
    debug(logger, paste0("Creating marker dotplot for resolution: ", res_name))
    
    tryCatch({
      # 获取聚类数量用于调整图形尺寸
      n_clusters <- length(unique(integrated_obj@meta.data[[res_name]]))
      plot_width <- n_clusters * 1.1
      plot_height <- n_clusters * 0.8
      
      debug(logger, paste0("Plot dimensions: ", plot_width, " x ", plot_height))
      
      # 生成dotplot
      p_dot <- FindClusterMarkersDotplot(
        integrated_obj, 
        group_by = res_name,
        NAME = res_name,
        save_dir = cluster_marker_gene_dir,
        test = "wilcox",
        topgene = 7,
        color = viridis_plasma_dark_high
      )
      
      if (!is.null(p_dot)) {
        # 保存dotplot
        dotplot_file_png <- file.path(cluster_marker_gene_dir, paste0(res_name, "cluster_marker_gene_dotplot.png"))
        dotplot_file_pdf <- file.path(cluster_marker_gene_dir, paste0(res_name, "cluster_marker_gene_dotplot.pdf"))

        qs::qsave(p_dot,file.path(cluster_marker_gene_dir, paste0(res_name, "cluster_marker_gene_dotplot.qs")))
        # ggsave(dotplot_file_png, plot = p_dot, width = plot_width, height = plot_height, dpi = 1000)
        # ggsave(dotplot_file_pdf, plot = p_dot, width = plot_width, height = plot_height, dpi = 1000)
        
        # debug(logger, paste0("Saved dotplot for ", res_name, " to: ", dotplot_file_png))
      } else {
        warn(logger, paste0("Failed to generate dotplot for resolution: ", res_name))
      }
      
    }, error = function(e) {
      error(logger, paste0("Error processing resolution ", res_name, ": ", e$message))
      next
    })
  }
  
  debug(logger, "Completed draw_res_DimPlot execution")
}
# ==============================================================================
# END
# ==============================================================================
