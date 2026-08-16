# ==============================================================================
# 09.02.vis_annotation.r
# 功能：负责细胞类型注释和 Marker 基因的可视化
# 包括：手动注释用的多图组合、DotPlot 批量绘制、单个基因注释检查等
# ==============================================================================

#' 手动注释辅助绘图（组合图）
#'
#' @description 
#' 针对特定基因（genes_to_check），绘制组合图包括：
#' 1. DotPlot
#' 2. VlnPlot (两种样式)
#' 3. FeaturePlot (两种配色样式)
#' 生成的图片保存到 `annotation_figure_dir`。
#'
#' @param data Seurat 对象
#' @param plot_Prefix 图片文件名前缀
#' @param genes_to_check 要检查的基因名称
#' @export
manual_annotation_figure <- function(data,plot_Prefix,genes_to_check){
  # print run condition
  cat("\n")
  cat(cyan(paste0("manual annotation ",genes_to_check," PLOT  DO!!!!!")))
  cat("\n")
  # draw  DotPlot
  # data <-  subset_maritx
  # genes_to_check <- "NCAM1"
  p1 <- DotPlot(data, features = genes_to_check,assay='RNA')+ 
    theme_classic()+
    ggtitle(paste0(genes_to_check)) + 
    labs(x="Feature",y="cell cluster ID")+
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 12),
          legend.position="right",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10,face="bold"),
          axis.title.y = element_text(size = 10,face="bold"),
          axis.text.x = element_text(size = 8,face="bold"),
          axis.text.y = element_text(size = 8,face="bold"),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))
  # draw VlnPlot
  # data <-  subset_maritx
  # genes_to_check <- "NCAM1"
  boxplot_data <- data.frame(
    Gene = rep(genes_to_check, each = NROW(data@meta.data)),
    Expression_Level = as.vector(data@assays$RNA$data[genes_to_check,]),
    seurat_clusters = data@meta.data$seurat_clusters
  )
  colors_with_alpha <- adjustcolor(colour1, alpha = 0.5)
  p2 <- VlnPlot(data, features = genes_to_check,cols=colors_with_alpha,pt.size=0.00001)+ 
    theme_classic()+
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="none",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10,face="bold"),
          axis.title.y = element_text(size = 10,face="bold"),
          axis.text.x = element_text(size = 8,face="bold"),
          axis.text.y = element_text(size = 8,face="bold"),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))
  # DRAW VIOLIN GGPLOT CODE
  p2_1 <- ggplot()+
    geom_violin(data = boxplot_data,
                aes(x =seurat_clusters,y = Expression_Level,fill=seurat_clusters),
                colour=NA)+ 
    geom_boxplot(data = boxplot_data,aes(x =seurat_clusters,y = Expression_Level,fill = seurat_clusters,) 
                 ,size=0.2, colour = "#000000",alpha=0.5)+ 
    scale_fill_manual(values=colors_with_alpha)+
    ggtitle(paste0(genes_to_check)) + 
    labs(x="cell cluster ID",y="Expression level")+ 
    scale_y_continuous(expand = c(0,0),n.breaks = 8) + 
    theme_classic()+
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="none",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10,face="bold"),
          axis.title.y = element_text(size = 10,face="bold"),
          axis.text.x = element_text(size = 8,face="bold"),
          axis.text.y = element_text(size = 8,face="bold"),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))
  # draw FeaturePlot
  # data <-  subset_maritx
  # genes_to_check <- "NCAM1"
  p3 <- FeaturePlot(data, features = genes_to_check,pt.size=1, 
                    cols = c("low" = "#FFFFFF","high" = "#b20a2c"))+ 
    labs(color = "Expression") + 
    theme_classic()+
    ggtitle(paste0(genes_to_check)) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 10) + 
    scale_x_continuous(n.breaks = 10) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position= c(0.9,0.16),
          legend.title=element_text(size = 8,face="bold"),
          legend.text =element_text(size = 6),
          legend.key.size = unit(0.15, "inch"),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,size=0.2,color="#a6acaf"),
          axis.line.y=element_line(linetype=1,size=0.2,color="#a6acaf"),
          axis.ticks.x=element_line(size=0.2,lineend = 1,color="#a6acaf"),
          axis.ticks.y=element_line(size=0.2,lineend = 1,color="#a6acaf"))
  # add FeaturePlot TYPE
  # data <-  subset_maritx
  # genes_to_check <- "GZMH"
  p4 <- FeaturePlot(data, features = genes_to_check,pt.size=0.5, 
                    cols = c("low" = "#fdbb2d","mid"="#b21f1f","high" = "#1a2a6c"))+ 
    labs(color = "Expression") + 
    theme_classic()+
    ggtitle(paste0(genes_to_check)) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 10) + 
    scale_x_continuous(n.breaks = 10) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position= c(0.9,0.16),
          legend.title=element_text(size = 8,face="bold"),
          legend.text =element_text(size = 6),
          legend.key.size = unit(0.15, "inch"),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,size=0.2,color="#1b2631"),
          axis.line.y=element_line(linetype=1,size=0.2,color="#1b2631"),
          axis.ticks.x=element_line(size=0.2,lineend = 1,color="#1b2631"),
          axis.ticks.y=element_line(size=0.2,lineend = 1,color="#1b2631"))
  # merge plot
  all_p <- ggarrange(umap_plot,p3,p1,p2,ncol=2,nrow=2,labels=c("A","B","C","D"))
  # print plot
  print(all_p)
  # save plot
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," merge_plot.pdf")),device = "pdf",width = 10,height = 12,plot=all_p)
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," merge_plot.png")),device = "png",width = 10,height = 12,plot=all_p,dpi=600)
  # save p1 plot
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," DotPlot.pdf")),device = "pdf",width = 4,height = 6,plot=p1)
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," DotPlot.png")),device = "png",width = 4,height = 6,plot=p1,dpi=600)
  # save p2 plot
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," VlnPlot-TYPE1.pdf")),device = "pdf",width = 8,height = 5,plot=p2)
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," VlnPlot-TYPE1.png")),device = "png",width = 8,height = 5,plot=p2,dpi=600)
  # save p2_1 plot
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," VlnPlot-TYPE2.pdf")),device = "pdf",width = 8,height = 5,plot=p2_1)
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," VlnPlot-TYPE2.png")),device = "png",width = 8,height = 5,plot=p2_1,dpi=600)
  # save p3 plot
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," FeaturePlot_plot-TYPE1.pdf")),device = "pdf",width = 5,height = 5,plot=p3)
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," FeaturePlot_plot-TYPE1.png")),device = "png",width = 5,height = 5,plot=p3,dpi=600)
  # save p4 plot
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," FeaturePlot_plot-TYPE2.pdf")),device = "pdf",width = 5,height = 5,plot=p4)
  ggsave(file.path(annotation_figure_dir,paste0(plot_Prefix,"-",genes_to_check," FeaturePlot_plot-TYPE2.png")),device = "png",width = 5,height = 5,plot=p4,dpi=600)
  # print run condition
  cat("\n")
  cat(cyan(paste0("manual annotation ",genes_to_check," PLOT  DONE!!!!!")))
  cat("\n")
}

#' 重命名细胞 Cluster ID 并绘图
#'
#' @description 
#' 使用新的 Cluster ID 列表重命名 Seurat 对象的 Idents。
#' 注：函数内部的绘图代码已被注释。
#'
#' @param data Seurat 对象
#' @param new.cluster.ids 新的 Cluster ID 向量
#' @param plot_name 图表标题名称（未使用，因绘图代码被注释）
#' @return 重命名后的 Seurat 对象
#' @export
AnnotationCellClusterName <- function(data,new.cluster.ids,plot_name){
  #data <- scrna_seq_integr
  names(new.cluster.ids) <- levels(data)
  rename_data <- RenameIdents(data, new.cluster.ids)
  # set plot width
  width <- (length(levels(as.factor(data$orig.ident))) * 8)+5
  # draw plot
  #draw_umap_plot(rename_data,plot_name)
  #draw_umap_plot_orig.ident(rename_data,plot_name)
  #draw_tsne_plot(rename_data,plot_name)
  #draw_tsne_plot_orig.ident(rename_data,plot_name)
  # print run condition
  return(rename_data)
}

#' 绘制注释用的 DotPlot
#'
#' @description 
#' 绘制基因列表的 DotPlot，横纵坐标翻转，保存为 PDF 和 PNG。
#'
#' @param data Seurat 对象
#' @param genes_to_check 基因列表
#' @export
draw_annotation_cell_cluster_doplot <- function(data,genes_to_check){
  #data <- rename_maritx
  p<- DotPlot(data, features = genes_to_check,assay='RNA',dot.scale=2.5) + 
    coord_flip()+
    theme_classic()+
    ggtitle(paste0(project_name," Dimplot")) + 
    labs(x="",y="")+ 
    theme(plot.title = element_text(hjust = 0.5,size = 8),
          legend.position="right",
          legend.title=element_text(size = 5),
          text = element_text(size = 9),title = element_text(size = 7),
          axis.title.x = element_text(size = 8),axis.title.y = element_text(size = 7),
          axis.text.x = element_text(size = 5,angle=45,hjust=0.9,vjust=0.9),axis.text.y = element_text(size = 5),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))
  print(p)
  # save plot
  # save
  ggsave(file.path(figure_dir,paste0("10.annotation-DotPlot.pdf")),plot=p,width = 8,height = 11,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0("10.annotation-DotPlot.png")),plot=p,width = 8,height = 11,units = "cm",device = "png",dpi=1000)
  # print run condition
}

#' 单基因注释分析（绘图 + 计算比例）
#'
#' @description 
#' 针对单个基因：
#' 1. 调用 `manual_annotation_figure` 绘图
#' 2. 计算该基因在所有细胞以及各 Cluster 中的表达比例
#' 3. 结果保存为 CSV
#'
#' @param data Seurat 对象
#' @param plot_Prefix 图片文件名前缀
#' @param genes_to_check 基因名称
#' @export
sign_gene_annotation_calculation_prop <- function(data,plot_Prefix,genes_to_check){
  # data <- GENOMIC10XDATA_maritx_filted_normal_scale
  # plot_Prefix <- "s1858r09003_1"
  # genes_to_check <- "Cd3d"
  # draw umap plot
  # draw manual annotation plot
  manual_annotation_figure(data,plot_Prefix,genes_to_check)
  # calculation marker gene rate by scCustomize R pcakage for All cells
  percent_stats <- Percent_Expressing(seurat_object = data, features = genes_to_check, threshold = 0,
                                      entire_object=T)
  percent_stats$number <-  percent_stats*dim(data)[2]/100
  print_color_note(paste0(genes_to_check," all Cells rate ", percent_stats))
  # calculation marker gene rateby scCustomize R pcakage for cells cluster
  percent_stats_cell_cluster <- Percent_Expressing(seurat_object = data, features = genes_to_check, threshold = 0,
                                                   entire_object=F,split_by="seurat_clusters")
  colnames(percent_stats_cell_cluster) <- paste0("cluster-",c(0:(length(levels(data$seurat_clusters))-1)))
  # print run condition
  print(percent_stats_cell_cluster)
  merge_data <- cbind(percent_stats,percent_stats_cell_cluster)
  # save marker gene rate for all Cells
  write.csv(merge_data,file.path(manual_annotation_figure_dir,paste0(genes_to_check,"-merker-gene-for-all-cells.csv")))
}

#' 绘制 DotPlot (多种样式)
#'
#' @description 
#' 绘制两套不同样式的 DotPlot，用于展示 Marker 基因在各 Cluster 的表达情况。
#' Type 1: 红蓝配色
#' Type 2: 另一套红蓝配色
#'
#' @param data Seurat 对象
#' @param marker Marker 列表（需包含 gene 列）
#' @param plot_name 图片文件名前缀
#' @param title_name 图表标题
#' @export
DotPlot_plot <- function(data,marker,plot_name,title_name){
  # data <- scrna_seq_integr
  # plot_name <- "test"
  # title_name <- "test"
  # marker <- marker_list
  # get plot height
  if (length(marker$gene) < 5){
    plot_height = 3
  }else{
    plot_height <- round(length(marker$gene)*0.25)
  }
  # draw plot
  p1 <- DotPlot(data, features = unique(marker$gene), dot.scale = 3.5) + 
    coord_flip()+
    scale_colour_gradient2(low = "#0468FD", mid = "#FEFEB7", high = "#EF290B")+ 
    ggtitle(paste0(title_name," DotPlot")) + 
    labs(x="Feature Genes",y="Cells cluster")+ 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6), 
          plot.title = element_text(hjust = 0.5,size = 9),
          legend.justification = c(0.0, 1.0),
          legend.title=element_text(size = 7),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 9),
          axis.title.y = element_text(size = 9),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.2),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.2),
          axis.ticks.x=element_line(color="black",linewidth=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.2,lineend = 1))
  # save plot
  ggsave(file.path(DotPlot_dir,paste0(plot_name,"_DotPlot_type1.pdf")),plot=p1,width = 5,height = plot_height,device = "pdf")
  ggsave(file.path(DotPlot_dir,paste0(plot_name,"_DotPlot_type1.png")),plot=p1,width = 5,height = plot_height,device = "png",dpi=1000)
  # print plot
  print(p1)
  # dotplot type2
  # get plot height
  if (length(marker$gene) < 5){
    plot_width = 3
  }else{
    plot_width <- round(length(marker$gene)*0.25)
  }
  # draw plot
  p2 <- DotPlot(data, features = unique(marker$gene), dot.scale = 3.5) + 
    scale_colour_gradient2(low = "#0468FD", mid = "#FEFEB7", high = "#EF290B")+ 
    ggtitle(paste0(project_name," DotPlot")) + 
    labs(x="Feature Genes",y="Cells cluster")+ 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 9),
          legend.justification = c(0.0, 1.0),
          legend.title=element_text(size = 7),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 9),
          axis.title.y = element_text(size = 9),
          axis.text.x = element_text(size = 6,angle=90), 
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.2),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.2),
          axis.ticks.x=element_line(color="black",linewidth=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.2,lineend = 1))
  # save plot
  ggsave(file.path(DotPlot_dir,paste0(plot_name,"_DotPlot_type2.pdf")),plot=p2,width = plot_width,height = 5,device = "pdf")
  ggsave(file.path(DotPlot_dir,paste0(plot_name,"_DotPlot_type2.png")),plot=p2,width = plot_width,height = 5,device = "png",dpi=1000)
  # print plot
  print(p2)
}

#' 手动注释单基因（包装函数）
#'
#' @description 
#' `manual_annotation_figure` 的包装函数，并计算表达比例。
#'
#' @param count_maritx Seurat 对象
#' @param plot_Prefix 图片文件名前缀
#' @param genes_to_check 基因名称
#' @export
manual_annotation_cell_cluster_single_gene <- function(count_maritx,plot_Prefix,genes_to_check){
  # genes_to_check <- "CTLA4"
  # draw manual annotation plot
  manual_annotation_figure(count_maritx,plot_Prefix,genes_to_check)
  # calculation marker gene rate by scCustomize R pcakage for All cells
  percent_stats <- Percent_Expressing(seurat_object = count_maritx,
                                      features = genes_to_check,
                                      threshold = 0,
                                      entire_object=T)
  print_color_note(paste0(genes_to_check," all Cells rate ", percent_stats))
  # calculation marker gene rate by scCustomize R pcakage for cells cluster
  percent_stats_cell_cluster <- Percent_Expressing(seurat_object = count_maritx,
                                                   features = genes_to_check,
                                                   threshold = 0,
                                                   entire_object=F,
                                                   split_by="seurat_clusters")
  colnames(percent_stats_cell_cluster) <- paste0("cluster-",c(0:(length(levels(count_maritx$seurat_clusters))-1)))
  # print run condition
  #print(percent_stats_cell_cluster)
  merge_data <- cbind(percent_stats,percent_stats_cell_cluster)
  # save marker gene rate for all Cells
  write.csv(merge_data,file.path(manual_annotation_figure_dir,paste0(genes_to_check,"-merker-gene-for-all-cells.csv")))
}

#' 手动注释基因列表
#'
#' @description 
#' 批量处理基因列表：
#' 1. 绘制整体的 DotPlot
#' 2. 循环对列表中每个基因调用 `manual_annotation_cell_cluster_single_gene`
#' 包含错误处理（tryCatch）。
#'
#' @param count_maritx Seurat 对象
#' @param plot_name 图片文件名前缀
#' @param title_name 图表标题
#' @param list 基因列表
#' @export
manual_annotation_cell_cluster_gene_list <- function(count_maritx,plot_name,title_name,list){
  # check marker special
  # list <- cell_marker_list[i]
  # list <- Fib.cell.marker
  # count_maritx <- scrna_seq_integr
  # title_name <- plot_name
  marker_list <- as.data.frame(list)
  colnames(marker_list) <- "gene"
  # draw all gene dotplot
  tryCatch({
    DotPlot_plot(count_maritx,marker_list,plot_name,title_name)
  }, warning = function(w){
    print_color_note_warring(paste0("Draw dotplot WARRING !!!"))
    DotPlot_plot(count_maritx,marker_list,plot_name,title_name)
  }, error = function(e){
    print_color_note_warring(paste0("Draw dotplot ERROR !!!"))
    DotPlot_plot(count_maritx,marker_list,plot_name,title_name)
  })
  # draw everyone gene list
  for (i in list[[1]]){
    tryCatch({
      manual_annotation_cell_cluster_single_gene(count_maritx,i)
    }, warning = function(w){
      print_color_note_warring(paste0("Draw ",i," gene expression WARRING !!!"))
    }, error = function(e){
      print_color_note_warring(paste0("Draw ",i," gene expression ERROR !!!"))
    })
  }
}

#' 绘制所有已知细胞类型的 Marker 列表
#'
#' @description 
#' 遍历 `cell_marker_list` 中的所有细胞类型，调用 `manual_annotation_cell_cluster_gene_list` 进行批量绘图。
#'
#' @param draw_all_marker 逻辑值，是否执行
#' @param cell_marker_list 包含各细胞类型 Marker 的列表
#' @param scrna_seq_integr Seurat 对象
#' @export
draw_all_marker_list <- function(draw_all_marker,cell_marker_list,scrna_seq_integr){
  if (draw_all_marker == T ){
    for (i in c(1:length(cell_marker_list))){
      # i <- 1
      marker_name <- names(cell_marker_list[i])
      print_color_note_UP(paste0("ANALYSIS ",marker_name," GENE LIST DONE!!"))
      # draw NK.cell.marker GENE list
      plot_name <- marker_name
      manual_annotation_cell_cluster_gene_list(scrna_seq_integr,plot_name,marker_name,cell_marker_list[i])
      print_color_note_DOWN(paste0("ANALYSIS ",marker_name," GENE LIST DO!!"))
    }
  }else{
    print_color_note_NOTE("DON'T DRAW ALL KONW CELL TYPR MARKER LIST")
  }
}

#' 绘制基因列表 DotPlot (Wrapper)
#'
#' @description 
#' `DotPlot_plot` 的简单包装，增加了 tryCatch 错误处理。
#'
#' @param count_maritx Seurat 对象
#' @param plot_name 图片文件名前缀
#' @param title_name 图表标题
#' @param list 基因列表
#' @export
draw_gene_list_DotPlot_plot <- function(count_maritx,plot_name,title_name,list){
  # check marker special
  # list <- cell_marker_list[i]
  # count_maritx <- scrna_seq_integr
  marker_list <- as.data.frame(list)
  colnames(marker_list) <- "gene"
  # draw all gene dotplot
  tryCatch({
    DotPlot_plot(count_maritx,marker_list,plot_name,title_name)
  }, warning = function(w){
    print_color_note_warring(paste0("Draw dotplot WARRING !!!"))
    DotPlot_plot(count_maritx,marker_list,plot_name,title_name)
  }, error = function(e){
    print_color_note_warring(paste0("Draw dotplot ERROR !!!"))
    DotPlot_plot(count_maritx,marker_list,plot_name,title_name)
  })
}
# ==============================================================================
# END 
# ==============================================================================
