# author : zhang jian
# date : 2024-12-25
# version : 1.0v
# FindClusterMarkersDotplot : 使用 seurat 包的FindMarkers对seurat object 的meta.data的特定列进行差异分析,
#                             并且使用 pct.1 > 0.25进行过滤，更具过滤后的 marker list 绘制marker dotplot
#                             差异分析配对规则 group1 vs (all other group)
#                             差异分析可以使用的 test 方法 (默认使用wilcox)："wilcox","wilcox_limma","bimod"  
#                             "LR","MAST","DESeq2","roc","t","negbinom","poisson"
# cluster差异分析并绘制Dotplot FindClusterMarkersDotplot
FindClusterMarkersDotplot <-function(Seurat,group_by = 'Celltype',
                                     save_dir='./',
                                     test = "wilcox",
                                     topgene = 5,
                                     color = viridis_plasma_dark_high){
  require(scCustomize)
  require(ggplot2)
  require(Seurat)
  # Seurat <- annotation_Seurat
  markrt_list <- data.frame(group = character(),
                            gene = character())
  Seurat@meta.data$celltype <- Seurat@meta.data[[group_by]]
  for (i in levels(factor(Seurat@meta.data$celltype))){
    # i <- '14'
    info(logger, paste0('scRNA-seq Analysis FindMarkers ',i))
    cells1 <- subset(Seurat@meta.data,celltype == i )  |> rownames()
    cells2 <- subset(Seurat@meta.data,celltype != i )  |> rownames()
    temp_marker <-  FindMarkers(Seurat,
                                ident.1 = cells1, 
                                ident.2 = cells2,
                                only.pos = FALSE,
                                logfc.threshold = log(2),
                                test.use = test)
    temp_marker <- temp_marker |> arrange(-avg_log2FC) |> filter(pct.1 > 0.25) |>  dplyr::slice_head(n=topgene)
    temp <- data.frame(group = i,
                       gene = rownames(temp_marker))
    markrt_list <-  rbind(markrt_list,temp)
  }
  write.csv(markrt_list,file.path(save_dir,'markrt_list.csv'))
  # viridis_plasma_dark_high ,viridis_plasma_light_high,viridis_magma_dark_high,viridis_magma_light_high
  # viridis_inferno_dark_high,viridis_inferno_light_high,viridis_dark_high,viridis_light_high
  p <- DotPlot_scCustom(seurat_object = Seurat,
                        features = unique(markrt_list$gene),
                        group.by = `group_by`,
                        colors_use = viridis_plasma_dark_high) +
    theme(axis.text.x = element_text(angle = 45,vjust=0.9,hjust=0.9))
  return(p)
}