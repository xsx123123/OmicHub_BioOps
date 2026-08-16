# ==============================================================================
# 09.01.vis_dim_reduction.r
# 功能：负责降维分析（UMAP, tSNE）的可视化展示
# 包括：分割/不分割样本的 DimPlot，以及多样本的 FeaturePlot
# ==============================================================================

#' 绘制 UMAP 和 tSNE 图（按 orig.ident 分割）
#'
#' @description 
#' 同时绘制 UMAP 和 tSNE 的 DimPlot，并按照 `orig.ident` 进行 split.by 分割展示。
#' 结果保存为 PDF 和 PNG。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称（通常是样本或分析名称）
#' @param figure_prefix 图片文件名前缀
#' @export
dimplot_UMAPtSNE_split_plot <- function(data,name,figure_prefix){
  # data <- scrna_seq_integr
  width = length(levels(factor(data$orig.ident)))*8
  # DRAW UMAP
  p1 <- DimPlot(data, reduction = "umap", split.by = "orig.ident",label = TRUE,pt.size=0.4,label.size=3.2)+
    geom_vline(xintercept=0,lty=4,col="black",lwd=0.3) + 
    geom_hline(yintercept = 0,lty=4,col="black",lwd=0.3) + 
    theme_classic()+
    ggtitle(paste0(name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 20) + 
    scale_x_continuous(n.breaks = 20) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="bottom",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))  + 
    guides(color=guide_legend(nrow=2,title="Cluster-ID",title.position = "left",override.aes = list(size=3,alpha=1)))
  # save
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-UMAP-spilt-plot.pdf")),plot=p1,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-UMAP-spilt-plot.png")),plot=p1,width = width,height = 10,units = "cm",device = "png",dpi=1000)
  # DRAW TSNE
  p2 <- DimPlot(data, reduction = "tsne", split.by = "orig.ident",label = TRUE,pt.size=0.4,label.size=3.2)+
    geom_vline(xintercept=0,lty=4,col="black",lwd=0.3) + 
    geom_hline(yintercept = 0,lty=4,col="black",lwd=0.3) + 
    theme_classic()+
    ggtitle(paste0(name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 20) + 
    scale_x_continuous(n.breaks = 20) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="bottom",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))  + 
    guides(color=guide_legend(nrow=2,title="Cluster-ID",title.position = "left",override.aes = list(size=3,alpha=1)))
  # save
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-tSNE-spilt-plot.pdf")),plot=p2,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-tSNE-spilt-plot.png")),plot=p2,width = width,height = 10,units = "cm",device = "png",dpi=1000)
}

#' 绘制 UMAP 和 tSNE 图（不分割）
#'
#' @description 
#' 标准的 DimPlot 绘制，展示 UMAP 和 tSNE，不进行分割。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称
#' @param figure_prefix 图片文件名前缀
#' @export
dimplot_UMAPtSNE_plot <- function(data,name,figure_prefix){
  # data <- scrna_seq_integr
  # DRAW UMAP
  p1 <- DimPlot(data, reduction = "umap",label = TRUE,pt.size=0.4,label.size=3.2)+
    geom_vline(xintercept=0,lty=4,col="black",lwd=0.3) + 
    geom_hline(yintercept = 0,lty=4,col="black",lwd=0.3) + 
    theme_classic()+
    ggtitle(paste0(name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 20) + 
    scale_x_continuous(n.breaks = 20) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="bottom",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))  + 
    guides(color=guide_legend(nrow=2,title="Cluster-ID",title.position = "left",override.aes = list(size=3,alpha=1)))
  # save
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-UMAP-plot.pdf")),plot=p1,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-UMAP-plot.png")),plot=p1,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
  # DRAW TSNE
  p2 <- DimPlot(data, reduction = "tsne", label = TRUE,pt.size=0.4,label.size=3.2)+
    geom_vline(xintercept=0,lty=4,col="black",lwd=0.3) + 
    geom_hline(yintercept = 0,lty=4,col="black",lwd=0.3) + 
    theme_classic()+
    ggtitle(paste0(name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 20) + 
    scale_x_continuous(n.breaks = 20) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="bottom",
          legend.title=element_text(size = 10),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))  + 
    guides(color=guide_legend(nrow=2,title="Cluster-ID",title.position = "left",override.aes = list(size=3,alpha=1)))
  # save
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-tSNE-plot.pdf")),plot=p2,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-tSNE-plot.png")),plot=p2,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
}

#' 绘制 UMAP 和 tSNE 图（更新版）
#'
#' @description 
#' `dimplot_UMAPtSNE_plot` 的更新版本，支持传入 `figure_dir`。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称
#' @param figure_prefix 图片文件名前缀
#' @param figure_dir 图片保存目录
#' @export
DimPlotUMAPtSNE <- function(data,name,figure_prefix,figure_dir){
  # data <- scrna_seq_integr
  # DRAW UMAP
  p1 <- DimPlot(data, reduction = "umap",label = TRUE,pt.size=0.4,label.size=3.2)+
    theme_classic()+
    ggtitle(paste0(name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 20) + 
    scale_x_continuous(n.breaks = 20) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="bottom",
          legend.title=element_text(size = 8),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))  + 
    guides(color=guide_legend(nrow=2,title="ClusterID",title.position = "left",override.aes = list(size=3,alpha=1)))
  # save
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-UMAP-plot.pdf")),plot=p1,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-UMAP-plot.png")),plot=p1,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
  # DRAW TSNE
  p2 <- DimPlot(data, reduction = "tsne", label = TRUE,pt.size=0.4,label.size=3.2)+
    theme_classic()+
    ggtitle(paste0(name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 20) + 
    scale_x_continuous(n.breaks = 20) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 15),
          legend.position="bottom",
          legend.title=element_text(size = 8),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 10),
          axis.title.y = element_text(size = 10),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))  + 
    guides(color=guide_legend(nrow=2,title="ClusterID",title.position = "left",override.aes = list(size=3,alpha=1)))
  # save
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-tSNE-plot.pdf")),plot=p2,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-","scRNA-seq-tSNE-plot.png")),plot=p2,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
}

#' 绘制定制化 UMAP 图
#'
#' @description 
#' 绘制 UMAP 图，自动根据 Cluster 数量调整图例列数和宽度，保存到 UMAP_dir。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称/文件名前缀
#' @return ggplot 对象
#' @export
draw_umap_plot <- function(data,name){
  # data <- blood_vessels
  if (length(levels(Idents(data))) > 12 ) {
    legend_col <- 2
    width <- 15
  }else{
    legend_col <- 1
    width <- 13
  }
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (UMAP) DO!!!!!"))
  cat("\n")
  p <- DimPlot(data,
               reduction = "umap",
               label=F,
               label.size=1.3,
               cols=colour )
  p1 <- p + 
    theme_classic()+
    ggtitle(paste0(project_name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 10) + 
    scale_x_continuous(n.breaks = 10) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 10,family="sans",face = "bold"),
          legend.position="right",
          legend.title=element_text(size = 8),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 8),
          axis.title.y = element_text(size = 8),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.2),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))+
    guides(color=guide_legend(ncol=legend_col,title="Cluster-ID",title.position = "top",override.aes = list(size=1.5,alpha=0.8)))
  # ggsave
  ggsave(file.path(UMAP_dir,paste0(name," UMAP-plot.pdf")),plot=p1,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(UMAP_dir,paste0(name," UMAP-plot.png")),plot=p1,width = width,height = 10,units = "cm",device = "png",dpi=1000)
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (UMAP) DONE!!!!!"))
  cat("\n")
  return(p1)
}

#' 绘制定制化 UMAP 图（按 orig.ident 分割）
#'
#' @description 
#' 绘制按 `orig.ident` 分割的 UMAP 图，自动调整宽度。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称/文件名前缀
#' @return ggplot 对象
#' @export
draw_umap_plot_orig.ident <- function(data,name){
  # data <- blood_vessels
  if (length(levels(Idents(data))) > 12 ) {
    legend_col <- 2
  }else{
    legend_col <- 1
  }
  width <- (length(levels(as.factor(data$orig.ident)))*10)+3
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (UMAP) DO!!!!!"))
  cat("\n")
  p <- DimPlot(data,
               reduction = "umap",
               label=F,
               label.size=1.3,
               cols=colour,
               split.by="orig.ident")
  p1 <- p + 
    theme_classic()+
    ggtitle(paste0(project_name," UMAP plot")) + 
    labs(x="UMAP-1",y="UMAP-2")+
    scale_y_continuous(n.breaks = 10) + 
    scale_x_continuous(n.breaks = 10) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 10,family="sans",face = "bold"),
          legend.position="right",
          legend.title=element_text(size = 8),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 8),
          axis.title.y = element_text(size = 8),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.2),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))+
    guides(color=guide_legend(ncol=legend_col,title="Cluster-ID",title.position = "top",override.aes = list(size=1.5,alpha=0.8)))
  # ggsave
  ggsave(file.path(UMAP_dir,paste0(name,"-orig.ident-UMAP-plot.pdf")),plot=p1,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(UMAP_dir,paste0(name,"-orig.ident-UMAP-plot.png")),plot=p1,width = width,height = 10,units = "cm",device = "png",dpi=1000)
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (UMAP) DONE!!!!!"))
  cat("\n")
  return(p1)
}

#' 绘制定制化 tSNE 图
#'
#' @description 
#' 绘制 tSNE 图，自动根据 Cluster 数量调整图例列数和宽度，保存到 tsne_dir。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称/文件名前缀
#' @return ggplot 对象
#' @export
draw_tsne_plot <- function(data,name){
  if (length(levels(Idents(data))) > 12 ) {
    legend_col <- 2
    width <- 15
  }else{
    legend_col <- 1
    width <- 13
  }
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (tSNE) DO!!!!!"))
  cat("\n")
  p <- DimPlot(data,
               reduction = "tsne",
               label=F,
               label.size=1.3,
               cols=colour)
  p1 <- p + 
    theme_classic()+
    ggtitle(paste0(project_name," tSNE plot")) + 
    labs(x="tSNE-1",y="tSNE-2")+
    scale_y_continuous(n.breaks = 10) + 
    scale_x_continuous(n.breaks = 10) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 10,family="sans",face = "bold"),
          legend.position="right",
          legend.title=element_text(size = 8),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 8),
          axis.title.y = element_text(size = 8),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.2),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.2),
          axis.ticks.x=element_line(color="black",linewidth=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.2,lineend = 1))+
    guides(color=guide_legend(ncol=legend_col,title="Cluster-ID",title.position = "top",override.aes = list(size=1.5,alpha=0.8)))
  # ggsave
  ggsave(file.path(tsne_dir,paste0(name," tSNE-plot.pdf")),plot=p1,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(tsne_dir,paste0(name," tSNE-plot.png")),plot=p1,width = width,height = 10,units = "cm",device = "png",dpi=1000)
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (tSNE) DONE!!!!!"))
  cat("\n")
  return(p1)
}

#' 绘制定制化 tSNE 图（按 orig.ident 分割）
#'
#' @description 
#' 绘制按 `orig.ident` 分割的 tSNE 图，自动调整宽度。
#'
#' @param data Seurat 对象
#' @param name 图表标题名称/文件名前缀
#' @return ggplot 对象
#' @export
draw_tsne_plot_orig.ident <- function(data,name){
  if (length(levels(Idents(data))) > 12 ) {
    legend_col <- 2
  }else{
    legend_col <- 1
  }
  # data <- blood_vessels
  width <- (length(levels(as.factor(data$orig.ident)))*10)+3
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (tSNE) DO!!!!!"))
  cat("\n")
  p <- DimPlot(data,
               reduction = "tsne",
               label=F,
               label.size=1.3,
               cols=colour,
               split.by="orig.ident")
  p1 <- p + 
    theme_classic()+
    ggtitle(paste0(project_name," tSNE plot")) + 
    labs(x="tSNE-1",y="tSNE-2")+
    scale_y_continuous(n.breaks = 10) + 
    scale_x_continuous(n.breaks = 10) + 
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0.6),
          plot.title = element_text(hjust = 0.5,size = 10,family="sans",face = "bold"),
          legend.position="right",
          legend.title=element_text(size = 8),
          text = element_text(size = 8,family="sans"),
          axis.title.x = element_text(size = 8),
          axis.title.y = element_text(size = 8),
          axis.text.x = element_text(size = 6),
          axis.text.y = element_text(size = 6),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.2),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.2),
          axis.ticks.x=element_line(color="black",linewidth=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.2,lineend = 1))+
    guides(color=guide_legend(ncol=legend_col,title="Cluster-ID",title.position = "top",override.aes = list(size=1.5,alpha=0.8)))
  # ggsave
  ggsave(file.path(tsne_dir,paste0(name," -orig.ident-tSNE-plot.pdf")),plot=p1,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(tsne_dir,paste0(name," -orig.ident-tSNE-plot.png")),plot=p1,width = width,height = 10,units = "cm",device = "png",dpi=1000)
  # print run condition
  cat("\n")
  cat(cyan("PCA dim PLOT (tSNE) DONE!!!!!"))
  cat("\n")
  return(p1)
}

#' 根据整合方法绘制 UMAP 或 tSNE
#'
#' @description 
#' 根据 `intergetmethods` 参数（CCA, Harmony, NULL 等）选择对应的 reduction 进行绘图。
#' 使用 scCustomize 的 DimPlot_scCustom 进行绘制。
#'
#' @param ann_data Seurat 对象
#' @param reduceType 是否绘制降维图（默认 TRUE）
#' @param intergetmethods 整合方法 ('CCA', 'ALL', 'Harmony', 'NULL')
#' @param name 图片文件名前缀
#' @param figure_dir 图片保存目录
#' @export
draw_umap_tsne_plot <- function(ann_data,
                                reduceType = 'TRUE',
                                intergetmethods = 'CCA',
                                name = 'scRNA-seq',
                                figure_dir = figure_dir
                                ){
    # umap.harmony tsne.harmony
    # umap.cca tsne.cca
    if (intergetmethods %in% c('CCA','ALL')){
      reduction_tsne = 'tsne.cca'
      reduction_umap = 'umap.cca'
    }
    if (intergetmethods == 'Harmony'){
      reduction_tsne = 'tsne.harmony'
      reduction_umap = 'umap.harmony'
    }
    if (intergetmethods == 'NULL'){
      reduction_tsne = 'tsne'
      reduction_umap = 'umap'
    }
    if (reduceType == 'TRUE'){
      info(logger, 'Draw tSNE & UMAP Dimplot')
      p <- DimPlot_scCustom(ann_data,reduction = reduction_tsne) + labs(x= 'tSNE-1',y = 'tSNE-2')
      p2 <- DimPlot_scCustom(ann_data,reduction = reduction_umap) + labs(x= 'UMAP-1',y = 'UMAP-2')
      ggsave(file.path(figure_dir,paste0(name,'-tsne.png')),width = 8,height = 4,dpi = 1000,plot = p)
      ggsave(file.path(figure_dir,paste0(name,'-tsne.pdf')),width = 8,height = 4,dpi = 1000,plot = p)
      ggsave(file.path(figure_dir,paste0(name,'-umap.png')),width = 8,height = 4,dpi = 1000,plot = p2)
      ggsave(file.path(figure_dir,paste0(name,'-umap.pdf')),width = 8,height = 4,dpi = 1000,plot = p2)

      all <- (p|p2)
      ggsave(file.path(figure_dir,paste0(name,'-tsne_umap.png')),width = 10,height = 4,dpi = 1000,plot = all)
      ggsave(file.path(figure_dir,paste0(name,'-tsne_umap.pdf')),width = 10,height = 4,dpi = 1000,plot = all)
    }else{
      info(logger, 'Draw UMAP Dimplot')
      p2 <- DimPlot_scCustom(ann_data,reduction = reduction_umap) + labs(x= 'UMAP-1',y = 'UMAP-2')
      ggsave(file.path(figure_dir,paste0(name,'_umap.png')),width = 6,height = 4,dpi = 1000,plot = p2)
      ggsave(file.path(figure_dir,paste0(name,'_umap.pdf')),width = 6,height = 4,dpi = 1000,plot = p2)
  }
}

#' 绘制多样本 FeaturePlot (Split by orig.ident)
#'
#' @description 
#' 对特定基因绘制 FeaturePlot，并按 `orig.ident` 拆分为多个子图，最后合并展示。
#' 自动根据样本数量调整合并后的布局。
#'
#' @param data Seurat 对象
#' @param gene 目标基因名称
#' @param figureDir 图片保存目录
#' @export
DrawaMultiOrig.identFeaturePlot <- function(data,gene,figureDir){
  DefaultAssay(data) <- "RNA"
  data_list <- SplitObject(data, split.by = "orig.ident")
  Gname_list <- names(data_list)
  plot_list <- list()
  for(i in Gname_list){
    # i <- Gname_list[1]
    p1 <- FeaturePlot(data_list[i][[1]],gene,combine=F)[[1]] + labs(title=paste0(i,"-",gene))
    ggsave(file.path(figureDir,paste0(i,"-",gene,".pdf")),height = 5,width = 6,plot=p1)
    ggsave(file.path(figureDir,paste0(i,"-",gene,".png")),height = 5,width = 6,dpi=400,plot=p1)
    plot_list[[i]] <- p1
  }
  # megre plot
  if (length(plot_list) ==2){
    all = plot_list[[1]] + plot_list[[2]] + patchwork::plot_layout(ncol = 2)
    ggsave(file.path(figureDir,paste0("all_",gene,".pdf")),height = 5,width = 12,plot=all)
    ggsave(file.path(figureDir,paste0("all_",gene,".png")),height = 5,width = 12,dpi=400,plot=all)
  }else{
    if (length(plot_list) ==3){
      all = plot_list[[1]] + plot_list[[2]] + plot_list[[3]] +patchwork::plot_layout(ncol = 2)
      ggsave(file.path(figureDir,paste0("all_",gene,".pdf")),height = 10,width = 12,plot=all)
      ggsave(file.path(figureDir,paste0("all_",gene,".png")),height = 10,width = 12,dpi=400,plot=all)
    }else{
      if (length(plot_list) ==4){
        all = plot_list[[1]] + plot_list[[2]] + plot_list[[3]] + plot_list[[4]] +patchwork::plot_layout(ncol = 2)
        ggsave(file.path(figure_dir,paste0("all_",gene,".pdf")),height = 10,width = 12,plot=all)
        ggsave(file.path(figure_dir,paste0("all_",gene,".png")),height = 10,width = 12,dpi=400,plot=all)
      }else{
        if (length(plot_list) ==5){
          all =  plot_list[[1]] + plot_list[[2]] + plot_list[[3]] + plot_list[[4]] + plot_list[[5]] +patchwork::plot_layout(ncol = 2)
          ggsave(file.path(figure_dir,paste0("all_",gene,".pdf")),height = 15,width = 12,plot=all)
          ggsave(file.path(figure_dir,paste0("all_",gene,".png")),height = 15,width = 12,dpi=400,plot=all)
        }
      }
    }
  }
}
# ==============================================================================
# END 
# ==============================================================================
