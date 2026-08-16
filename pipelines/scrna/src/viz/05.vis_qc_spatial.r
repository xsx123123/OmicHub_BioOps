# ==============================================================================
# 09.05.vis_qc_spatial.r
# 功能：负责质控（QC）和空间转录组数据的可视化
# 包括：nFeature, nCount, percent.mt 的小提琴图，以及空间特征图
# ==============================================================================

#' 绘制细胞质控指标小提琴图
#'
#' @description 
#' 绘制三个核心 QC 指标（nFeature_RNA, nCount_RNA, percent.mt）的小提琴图。
#' 自动组合三个图并保存为 PDF 和 PNG。
#'
#' @param qc_dir 图片保存目录
#' @param data Seurat 对象
#' @param group.by 分组变量（x轴）
#' @param xtiite x轴标签
#' @param plot_Prefix 图片文件名前缀
#' @export
QCVlnPlot <- function(qc_dir,data,group.by,xtiite,plot_Prefix){
  # data <- subset_maritx
  colors_with_alpha <- adjustcolor(colour1, alpha = 0.3)
  P <- VlnPlot(data,group.by = group.by,
               features = c("nFeature_RNA", "nCount_RNA", "percent.mt"),
               ncol = 3,
               assay = "RNA",
               pt.size=0.0000000,
               combine = F,
               cols = colors_with_alpha)
  # extert nFeature_RNA_plot
  nFeature_RNA_plot <- P[[1]]
  P1 <- nFeature_RNA_plot +
    ggtitle("Feature Gene Count") +
    labs(x=xtiite,y="Feature Gene Count")+
    scale_y_continuous(expand = c(0,0),n.breaks = 8) +
    theme_classic()+
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 12,face="bold"),
          legend.position="none",
          legend.title=element_text(size = 10),
          text = element_text(size = 7,family="sans"),
          axis.title.x = element_text(size = 10,face="bold"),
          axis.title.y = element_text(size = 10,face="bold"),
          axis.text.x = element_text(size = 7,angle = 45,vjust = 0.9,hjust = 0.9),
          axis.text.y = element_text(size = 7),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.4),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.4),
          axis.ticks.x=element_line(color="black",linewidth=0.4,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.4,lineend = 1))
  # extert nCount_RNA_plot
  nCount_RNA_plot <- P[[2]]
  P2 <- nCount_RNA_plot +
    ggtitle("UMI Count") +
    labs(x=xtiite,y="UMI Count")+
    scale_y_continuous(expand = c(0,0),n.breaks = 8) +
    theme_classic()+
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 12,face="bold"),
          legend.position="none",
          legend.title=element_text(size = 10),
          text = element_text(size = 7,family="sans"),
          axis.title.x = element_text(size = 10,face="bold"),
          axis.title.y = element_text(size = 10,face="bold"),
          axis.text.x = element_text(size = 7,angle = 45,vjust = 0.9,hjust = 0.9),
          axis.text.y = element_text(size = 7),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.4),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.4),
          axis.ticks.x=element_line(color="black",linewidth=0.4,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.4,lineend = 1))
  
  # percent.mt_plot
  percent.mt_plot <- P[[3]]
  P3 <- percent.mt_plot +
    ggtitle("MT Gene Proportion") +
    labs(x=xtiite,y="MT Gene Proportion (%)")+
    scale_y_continuous(expand = c(0,0),n.breaks = 8) +
    theme_classic()+
    theme(panel.border = element_rect(linetype = 1, fill = NA,size=0),
          plot.title = element_text(hjust = 0.5,size = 12,face="bold"),
          legend.position="none",
          legend.title=element_text(size = 10),
          text = element_text(size = 7,family="sans"),
          axis.title.x = element_text(size = 10,face="bold"),
          axis.title.y = element_text(size = 10,face="bold"),
          axis.text.x = element_text(size = 7,angle = 45,vjust = 0.9,hjust = 0.9),
          axis.text.y = element_text(size = 7),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.4),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.4),
          axis.ticks.x=element_line(color="black",linewidth=0.4,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.4,lineend = 1))
  # merge plot
  all <- (P1 | P2 | P3)
  # save plot
  ggsave(file.path(qc_dir,paste0(plot_Prefix,"-","QC_cell_",xtiite,"_plot.pdf")),device = "pdf",width = 10,height = 4,plot=all)
  ggsave(file.path(qc_dir,paste0(plot_Prefix,"-","QC_cell_",xtiite,"_plot.png")),device = "png",width = 10,height = 4,plot=all,dpi=600)
}

#' 空间转录组质控绘图
#'
#' @description 
#' 针对空间数据（Spatial），绘制 nCount, nFeature, percent.mt 的小提琴图和空间分布图（SpatialFeaturePlot）。
#' 返回包含 3 个组合图列表的 List。
#'
#' @param SpatialData Seurat 空间对象
#' @param project_name 项目名称
#' @return list(p1, p2, p3)
#' @export
SpatialQC <- function(SpatialData,project_name){
  plot_list <- list()
  mean_nCount <-  mean(c(max(SpatialData@meta.data$nCount_Spatial),min(SpatialData@meta.data$nCount_Spatial)))
  plot1 <- VlnPlot(SpatialData, features = "nCount_Spatial", pt.size = 0) + 
    labs(title = "Spatial nCount" ) +
    scale_y_continuous(n.breaks = 7) +
    theme(legend.position = "none",
          plot.title = element_text(hjust = 0.5,face = "plain",size = 8),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size = 6),
          axis.title.x = element_text(angle = 0,hjust = 0.5,size = 8),
          axis.text.y = element_text(size = 8))
  plot2 <- SpatialFeaturePlot(SpatialData, features = "nCount_Spatial") +
    labs(fill = "Spatial nCount",title = project_name ) +
    scale_fill_gradient2(low = "blue",mid ="#ffffff" ,high="red",midpoint =mean_nCount)+
    theme(legend.position = "right",
          plot.title = element_text(hjust = 0.5,face = "plain",size = 8),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size = 6),
          axis.title.x = element_text(angle = 0,hjust = 0.5,size = 8),
          axis.text.y = element_text(size = 8))
  p1 <- plot1+plot2+patchwork::plot_layout(widths = c(1:3),nrow = 1,ncol=2)
  plot_list[[1]] <- p1
  mean_nfeatures <-  mean(c(max(SpatialData@meta.data$nFeature_Spatial),min(SpatialData@meta.data$nFeature_Spatial)))
  plot1 <- VlnPlot(SpatialData, features = "nFeature_Spatial", pt.size = 0) +
    labs(title = "Spatial nFeature" ) +
    scale_y_continuous(n.breaks = 7) +
    theme(legend.position = "none",
          plot.title = element_text(hjust = 0.5,face = "plain",size = 8),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size = 6),
          axis.title.x = element_text(angle = 0,hjust = 0.5,size = 8),
          axis.text.y = element_text(size = 8))
  plot2 <- SpatialFeaturePlot(SpatialData, features = "nFeature_Spatial") +
    labs(fill = "Spatial nFeature",title = project_name ) +
    scale_fill_gradient2(low = "blue",mid ="#ffffff" ,high="red",midpoint = mean_nfeatures)+
    theme(legend.position = "right",
          plot.title = element_text(hjust = 0.5,face = "plain",size = 8),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size = 6),
          axis.title.x = element_text(angle = 0,hjust = 0.5,size = 8),
          axis.text.y = element_text(size = 8))
  p2 <- plot1+plot2+patchwork::plot_layout(widths = c(1:3),nrow = 1,ncol=2)
  plot_list[[2]] <- p2
  mean_percent.mt <-  mean(c(max(SpatialData@meta.data$percent.mt),min(SpatialData@meta.data$percent.mt)))
  plot1 <- VlnPlot(SpatialData, features = "percent.mt", pt.size = 0) +
    scale_y_continuous(n.breaks = 8) +
    scale_y_continuous(n.breaks = 7) +
    theme(legend.position = "none",
          plot.title = element_text(hjust = 0.5,face = "plain",size = 8),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size = 6),
          axis.title.x = element_text(angle = 0,hjust = 0.5,size = 8),
          axis.text.y = element_text(size = 8))
  plot2 <- SpatialFeaturePlot(SpatialData, features = "percent.mt")+
    labs(fill = "Spatial MT Prop",title = project_name ) +
    scale_fill_gradient2(low = "blue",mid ="#ffffff" ,high="red",midpoint = mean_percent.mt)+
    theme(legend.position = "right",
          plot.title = element_text(hjust = 0.5,face = "plain",size = 8),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size = 6),
          axis.title.x = element_text(angle = 0,hjust = 0.5,size = 8),
          axis.text.y = element_text(size = 8))  
  p3 <- plot1+plot2+patchwork::plot_layout(widths = c(1:3),nrow = 1,ncol=2)
  plot_list[[3]] <- p3
  # return list
  return(plot_list)
}
# ==============================================================================
# END 
# ==============================================================================
