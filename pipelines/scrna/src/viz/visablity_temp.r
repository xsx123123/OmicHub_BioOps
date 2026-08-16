# function12-1:draw UMAP plot split
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
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-UMAP-spilt-plot.pdf")),plot=p1,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-UMAP-spilt-plot.png")),plot=p1,width = width,height = 10,units = "cm",device = "png",dpi=1000)
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
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-tSNE-spilt-plot.pdf")),plot=p2,width = width,height = 10,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-tSNE-spilt-plot.png")),plot=p2,width = width,height = 10,units = "cm",device = "png",dpi=1000)
}
#####
# function12-2:draw UMAP plot not split
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
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-UMAP-plot.pdf")),plot=p1,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-UMAP-plot.png")),plot=p1,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
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
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-tSNE-plot.pdf")),plot=p2,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-tSNE-plot.png")),plot=p2,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
}
# draw UMAP plot not split UPDATE
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
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-UMAP-plot.pdf")),plot=p1,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-UMAP-plot.png")),plot=p1,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
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
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-tSNE-plot.pdf")),plot=p2,width = 12,height = 14,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0(figure_prefix,"-",name,"-scRNA-seq-tSNE-plot.png")),plot=p2,width = 12,height = 14,units = "cm",device = "png",dpi=1000)
}

# function19:draw UMAP  plot
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
#####
# function20:draw tsne plot
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
#####
# function21:manual annotation cell cluster
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
#####
# function22: annotation_cell_cluster_name tsne
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
#####
# function23: annotation_cell_cluster_name doplot
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

#####
# function24: states cell cluster rate
states_cell_cluster_rate <- function(data,name_plot,title_name){
  print_color_note_NOTE("This function will states orig.ident cell type rate & visablity")
  # auto get width by orig.ident
  width_1 <- length(levels(as.factor(data$orig.ident))) * 1.3
  #data <-rename_maritx
  if (length(levels(data@active.ident)) <= 10){
    ncol = 1
    width = width_1 +2
  }else{
    if (length(levels(data@active.ident)) <= 20){
      ncol = 2
      width = width_1 + 4
    }else{
      if (length(levels(data@active.ident)) <= 30){
        ncol = 3
        width = width_1 + 6
      }
    }
  }
  # extert cell cluster number
  rate_data <- as.data.frame(table(Idents(data),data$orig.ident))
  # convert rate
  rate_data_1 <- data.frame()
  for(i in levels(rate_data$Var2)){
    temp_data <- subset(rate_data,rate_data$Var2==i)
    temp_sum <- sum(temp_data$Freq)
    temp_data$rate <- temp_data$Freq/temp_sum
    rate_data_1 <- rbind(rate_data_1,temp_data)
  }
  # convert %
  rate_data_1$rate <- rate_data_1$rate*100
  # change col name
  colnames(rate_data_1)[1] <- "Cell_cluster_name"
  colnames(rate_data_1)[2] <- "group"
  colnames(rate_data_1)[3] <- "frequently"
  colnames(rate_data_1)[4] <- "rate"
  # draw plot
  colour1 <- colour
  p <- ggplot(rate_data_1,aes(x=group,y=rate,fill=Cell_cluster_name))+
    geom_bar(position = 'stack',stat="identity",width=0.5)+
    labs(x="",y = "Cell cluster frequently (%)",title = title_name)+
    scale_fill_manual(values=colour1)+
    scale_y_continuous(expand = c(0,0),n.breaks = 10) +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5,size =10,family="sans",face = "bold"),
          legend.key.size = unit(0.15, "inch"),
          legend.title=element_text(size =6,face = "bold",family="sans"),
          legend.text =element_text(size =4),
          text = element_text(size = 4,face = "bold"),title = element_text(size = 4),
          axis.title.x = element_text(size = 8,family="sans",face = "bold"),axis.title.y = element_text(size = 8,family="sans",face = "bold"),
          axis.text.x = element_text(size = 6,family="sans",angle=45,hjust = 0.9,vjust = 0.9),axis.text.y = element_text(size = 6,family="sans"),
          panel.border = element_rect(color = "#606c70", fill = NA, size = 0.3),
          axis.line.x=element_line(linetype=1,color="#606c70",size=0.12),
          axis.line.y=element_line(linetype=1,color="#606c70",size=0.12),
          axis.ticks.x=element_line(color="#606c70",size=0.12,lineend = 0.05),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.12,lineend = 0.05))+
    guides(fill=guide_legend(ncol=ncol,title="Cell cluster Type",override.aes = list(size=0.02,alpha=1)))
  print(p)
  # save
  write.csv(rate_data_1,file.path(output_dir,paste0("2.proportion_annotation",name_plot,"-plot.csv")),row.names = F)
  ggsave(file.path(proportions_dir,paste0("11.proportion_annotation",name_plot,"-plot.pdf")),plot=p,width = width,height = 8,units = "cm",device = "pdf")
  ggsave(file.path(proportions_dir,paste0("11.proportion_annotation",name_plot,"-plot.png")),plot=p,width = width,height = 8,units = "cm",device = "png",dpi=1000)
  # print run condition
  return(p)
}
# function25: states cell cluster rate scCustomize color 
states_cell_cluster_rate_scCustomize <- function(data,name_plot,title_name,group.by){
  # auto get width by orig.ident
  width_1 <- length(levels(as.factor(data$orig.ident))) * 1.3
  #data <-rename_maritx
  if (length(levels(data@active.ident)) <= 10){
    ncol = 1
    width = width_1 +2
  }else{
    if (length(levels(data@active.ident)) <= 20){
      ncol = 2
      width = width_1 + 4
    }else{
      if (length(levels(data@active.ident)) <= 30){
        ncol = 3
        width = width_1 + 6
      }
    }
  }
  # extert cell cluster number
  colnames(data@meta.data)[which(colnames(data@meta.data) == `group.by`)] <- "Group"
  rate_data <- as.data.frame(table(Idents(data),data$Group))
  # convert rate
  rate_data_1 <- data.frame()
  for(i in levels(rate_data$Var2)){
    temp_data <- subset(rate_data,rate_data$Var2==i)
    temp_sum <- sum(temp_data$Freq)
    temp_data$rate <- temp_data$Freq/temp_sum
    rate_data_1 <- rbind(rate_data_1,temp_data)
  }
  # convert %
  rate_data_1$rate <- rate_data_1$rate*100
  # change col name
  colnames(rate_data_1)[1] <- "Cell_cluster_name"
  colnames(rate_data_1)[2] <- "group"
  colnames(rate_data_1)[3] <- "frequently"
  colnames(rate_data_1)[4] <- "rate"
  # draw plot
  colour1 <- scCustomize_Palette(num_groups = 36, ggplot_default_colors = FALSE)
  p <- ggplot(rate_data_1,aes(x=group,y=rate,fill=Cell_cluster_name))+
    geom_bar(position = 'stack',stat="identity",width=0.5)+
    labs(x="",y = "Cell cluster frequently (%)",title = title_name)+
    scale_fill_manual(values=colour1)+
    scale_y_continuous(expand = c(0,0),n.breaks = 10) +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5,size =10,family="sans",face = "bold"),
          legend.key.size = unit(0.15, "inch"),
          legend.title=element_text(size =6,face = "bold",family="sans"),
          legend.text =element_text(size =4),
          text = element_text(size = 4,face = "bold"),title = element_text(size = 4),
          axis.title.x = element_text(size = 8,family="sans",face = "bold"),axis.title.y = element_text(size = 8,family="sans",face = "bold"),
          axis.text.x = element_text(size = 6,family="sans",angle=45,hjust = 0.9,vjust = 0.9),axis.text.y = element_text(size = 6,family="sans"),
          panel.border = element_rect(color = "#606c70", fill = NA, size = 0.3),
          axis.line.x=element_line(linetype=1,color="#606c70",size=0.12),
          axis.line.y=element_line(linetype=1,color="#606c70",size=0.12),
          axis.ticks.x=element_line(color="#606c70",size=0.12,lineend = 0.05),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.12,lineend = 0.05))+
    guides(fill=guide_legend(ncol=ncol,title="Cell cluster Type",override.aes = list(size=0.02,alpha=1)))
  print(p)
  # save
  write.csv(rate_data_1,file.path(output_dir,paste0("2.proportion_annotation",name_plot,"-plot.csv")),row.names = F)
  ggsave(file.path(proportions_dir,paste0("11.proportion_annotation",name_plot,"-plot.pdf")),plot=p,width = width,height = 8,units = "cm",device = "pdf")
  ggsave(file.path(proportions_dir,paste0("11.proportion_annotation",name_plot,"-plot.png")),plot=p,width = width,height = 8,units = "cm",device = "png",dpi=1000)
  # print run condition
  return(p)
}
combine_scCustomuamp_rate_plot <- function(data,Celltype,Group,umap_plot,color_list,title_name,dir){
  library(patchwork)
  rate_data <- as.data.frame(table(data$`Celltype`,data$`Group`))
  # convert rate
  rate_data_1 <- data.frame()
  for(i in levels(rate_data$Var2)){
    temp_data <- subset(rate_data,rate_data$Var2==i)
    temp_sum <- sum(temp_data$Freq)
    temp_data$rate <- temp_data$Freq/temp_sum
    rate_data_1 <- rbind(rate_data_1,temp_data)
  }
  # convert %
  rate_data_1$rate <- rate_data_1$rate*100
  # change col name
  colnames(rate_data_1)[1] <- "Cell_cluster_name"
  colnames(rate_data_1)[2] <- "group"
  colnames(rate_data_1)[3] <- "frequently"
  colnames(rate_data_1)[4] <- "rate"
  write_csv(rate_data_1,file.path(dir,paste0(title_name,'-Celltype-rate.csv')))
  p_no_legend <- ggplot(rate_data_1, aes(x = group, y = rate, fill = Cell_cluster_name)) +
    geom_bar(position = 'stack', stat = "identity", width = 0.5) +
    scale_shape_manual(values = rep(21, length(colour1))) + # 设置形状
    labs(x = "", y = "Cell cluster frequently (%)", title = title_name) +
    scale_y_continuous(expand = c(0, 0), n.breaks = 10) +
    scale_fill_manual(values = color_list) +
    theme_minimal() +
    theme(plot.title = element_text(hjust = 0.5),
          legend.position = 'none')
  finish  <- p + p_no_legend + patchwork::plot_layout(guides = 'collect')
  return(finish)
}
# SingleSampleProp
SingleSampleProp <- function(data,title_name,group_by,ncol){
  p <- as.data.frame(table(data@meta.data[which(colnames(data@meta.data) == `group_by`)])) |> 
    mutate(group = `title_name`) |> mutate(prop = (Freq/(sum(Freq)))*100) |>
    ggplot(aes(x=group,y=prop,fill=Var1))+
    geom_bar(position = 'stack',stat="identity",width=0.5)+
    labs(x="",y = "Cell cluster frequently (%)",title = title_name)+
    scale_fill_manual(values=colour1)+
    scale_y_continuous(expand = c(0,0),n.breaks = 10) +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5))+
    guides(fill=guide_legend(ncol=ncol,title="Cell cluster Type",override.aes = list(size=0.5,alpha=1)))
  return(p)
}
#####
# merge umap & prop
merge_umap_prop <- function(umap,rate,figure_dir){
  merge_p <- ggarrange(umap,rate,labels=c("A","B"),common.legend = T,legend="right")
  ggsave(file.path(figure_dir,paste0("UMAP-prop-plot.pdf")),plot=merge_p,width = 14,height = 6,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0("UMAP-prop-plot.png")),plot=merge_p,width = 14,height = 6,units = "cm",device = "png",dpi=1000)
}
# function29 : get geneexpression by celltype
get_gene_expression_by_celltype <- function(data){
  # data <- rename_maritx
  # get celltype infor
  data$celltype <- Idents(data)
  # calculation gene expreession
  gene_expression <- as.data.frame(AverageExpression(data,group.by="celltype"))
  # change row name
  colnames(gene_expression) <- levels(data$celltype)
  # save gene expression
  write.csv(gene_expression,file.path(output_dir,"everyone-celltype-average-gene-expression.csv"))
  # return geneexpreesion
  return(gene_expression)
}
#####
# function30: get geneexpression by cluster
get_gene_expression_by_cluster <- function(data){
  # data <- rename_maritx
  # get celltype infor
  data$celltype <- Idents(data)
  # calculation gene expreession
  gene_expression <- as.data.frame(AverageExpression(data,group.by="seurat_clusters"))
  # change row name
  colnames(gene_expression) <- levels(data$seurat_clusters)
  # save gene expression
  write.csv(gene_expression,file.path(output_dir,"everyone-cluster-average-gene-expression.csv"))
  # return geneexpreesion
  return(gene_expression)
}
#####
# function31: get geneexpression by DIY
get_gene_expression_by_DIY <- function(data,DIY){
  print_color_note_warring("DIY PARAMETER MUST STR & IN meta.data FACTOR ")
  # data <- rename_maritx
  # get celltype infor
  data$celltype <- Idents(data)
  # calculation gene expreession
  gene_expression <- as.data.frame(AverageExpression(data,group.by=DIY))
  # change row name
  colnames(gene_expression) <- levels(data@meta.data[,grep(DIY,colnames(data@meta.data))])
  # save gene expression
  write.csv(gene_expression,file.path(output_dir,paste0("everyone-",DIY,"-average-gene-expression.csv")))
  # return geneexpreesion
  return(gene_expression)
}
#####
# function32: merge gene expression & DEG result
gene_expression_deg_merge <- function(diy_gene_expression,deg){
  colnames(diy_gene_expression) <- paste0("Average-gene-expression-",colnames(diy_gene_expression))
  
  diy_gene_expression$gene <- rownames(diy_gene_expression)
  merge_data <- left_join(deg,diy_gene_expression,by="gene")
  # return deg data
  return(merge_data)
}
#####
# function33: annotation deg gene
annotation_deg_result <- function(deg,db){
  annotation_data <- select(db, keys=deg$gene, columns=c("SYMBOL", "GENENAME"), keytype="SYMBOL")
  # change colname
  colnames(annotation_data) <- c("gene","GENE NAME")
  merge_data <- left_join(deg,annotation_data,by="gene")
  return(merge_data)
}
#####
# function35: draw signle gene annotation plot & calcualtion prop
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
#####
# function36:draw dotplot
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
#####
# function37: annotation_cell_cluster single gene
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
#####
# function38: annotation_cell_cluster gene list
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
#####
# function39: DRAW ALL KONW CELL TYPE MARKER GENE LIST
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
#####
# function40: DRAW ALL KONW CELL TYPE MARKER DotPlot
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
#####
# function41: QC VlnPlot FOR cell cluster
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

# draw stack violin plot type 1
StackVlnPlot <- function(data,features){
  spring <- c("#f6bcfd","#8dd3c6","#ffc512","#ffa300","#ff7d00","#ff6581",
              "#f8d90d","#a5da6b","#e578d6","#ffd2d8","#90e4cd","#84dce0",
              "#fe65b3","#D3F8E2","#E4C1F9","#F5B7B1","#A0E8AF","#FFF0F5",
              "#FFC48C","#A8E6CE")
  p <- VlnPlot(data, features = features, stack = T, sort = F, flip = T) +
    ggtitle("Stack violin-plot") +
    ylab("Expression Level")+
    xlab("Cell cluster") +
    theme_classic()+
    scale_fill_manual(values = spring) +
    scale_color_manual(values = spring)+
    theme(legend.position = "none",
          plot.title = element_text(hjust = 0.5,size = 14),
          panel.spacing = unit(0, "lines"),
          panel.background = element_rect(fill = NA, color = "black"),
          strip.background = element_blank(),
          strip.text.y = element_text(angle = 0,hjust = 0,size=10),
          axis.title.y = element_text(size = 12),
          axis.title.x = element_text(size = 12),
          axis.text.x = element_text(angle = 0,hjust = 0.5,size=10))
  return(p)
}
#####
# draw stack violin plot type 2
StackViolinType2 <- function(Stackdata,annotation,name){
  # Stackdata <- kindney_T
  # extert gene express
  vln.dat=FetchData(Stackdata,c(annotation$features,"celltype","seurat_clusters"))
  vln.dat$Cell <- rownames(vln.dat)
  vln.dat.melt <-  vln.dat |> pivot_longer(cols = !matches(c("Cell","seurat_clusters")),
                                           names_to="gene",
                                           values_to = "Expr",
                                           values_drop_na = TRUE) |> 
    group_by(seurat_clusters,gene) |>
    mutate(fillcolor=mean(Expr)) |> 
    mutate(CellCluster=paste0("CellCluster-",seurat_clusters))
  # annotation data deal 
  fileted <- annotation |> dplyr::filter(features %in% levels(as.factor(vln.dat.melt$gene)))
  fileted$features <- fct_reorder(fileted$features, fileted$group)
  fileted$group <- factor(fileted$group)
  vln.dat.melt$gene <- factor(vln.dat.melt$gene,levels = levels(fileted$features))
  vln.dat.melt$CellCluster <- fct_reorder(vln.dat.melt$CellCluster, as.numeric(vln.dat.melt$seurat_clusters))
  # draw stack violin PLOT
  p1 <- vln.dat.melt |>  
    ggplot(aes(gene, Expr, fill = gene)) +
    geom_violin(scale = "width", adjust = 1, trim = TRUE,color="#ffffff") +
    scale_y_continuous(expand = c(0, 0), position="right", labels = function(x)
      c(rep(x = "", times = length(x)-2), x[length(x) - 1], "")) +
    facet_grid(rows = vars(seurat_clusters), scales = "free", switch = "y") +
    scale_fill_manual(values = my55colors) + 
    ggtitle(paste0(name," Stack Violin Plot")) + 
    ylab("Expression Level") +
    theme_classic() +
    theme(legend.position = "none", 
          panel.spacing = unit(0, "lines"),
          plot.title = element_text(hjust = 0.5,face = "bold"),
          panel.background = element_rect(fill = NA, color = "black"),
          plot.margin = margin(7, 7, 0, 7, "pt"),
          strip.background = element_blank(),
          strip.text = element_text(),
          strip.text.y.left = element_text(angle = 0),
          axis.text.y = element_text(),
          axis.title.y = element_text(),
          axis.title.x = element_blank(),
          axis.text.x = element_blank(),
          axis.line.y = element_line(size = 0.3),
          axis.line.y.right = element_line(size = 0.3),
          axis.ticks.x = element_blank())
  # draw stack plot type2
  p1_1 <- vln.dat.melt |>  
    ggplot(aes(gene, Expr, fill = gene)) +
    geom_violin(scale = "width", adjust = 1, trim = TRUE,color="#ffffff") +
    scale_y_continuous(expand = c(0, 0), position="right", labels = function(x)
      c(rep(x = "", times = length(x)-2), x[length(x) - 1], "")) +
    facet_grid(rows = vars(CellCluster), scales = "free", switch = "y") +
    scale_fill_manual(values = my55colors) + 
    ggtitle(paste0(name," Stack Violin Plot")) + 
    ylab("Expression Level") +
    theme_classic() +
    theme(legend.position = "none", 
          panel.spacing = unit(0, "lines"),
          plot.title = element_text(hjust = 0.5,face = "bold"),
          panel.background = element_rect(fill = NA, color = "black"),
          plot.margin = margin(7, 7, 0, 7, "pt"),
          strip.background = element_blank(),
          strip.text = element_text(),
          strip.text.y.left = element_text(angle = 0),
          axis.text.y = element_text(),
          axis.title.y = element_text(),
          axis.title.x = element_blank(),
          axis.text.x = element_blank(),
          axis.line.y = element_line(size = 0.3),
          axis.line.y.right = element_line(size = 0.3),
          axis.ticks.x = element_blank())
  # draw bar
  p2 <- ggplot(fileted, aes(x = features, y = 1, fill = group)) + 
    geom_tile() + 
    xlab("Feature")+
    theme_bw(base_size = 12) +
    scale_fill_manual(values = sping) + 
    scale_y_continuous(expand = c(0, 0)) +
    guides(fill = guide_legend(direction = "horizontal", label.position = "right",
                               title.theme = element_blank(), keyheight = 1, nrow = 2,
                               label.vjust=0.5)) +
    theme(legend.position = "bottom",
          legend.justification = "top",
          legend.text = element_text(face = "bold", color = "black",size = 10),
          legend.margin = margin(0,0,0,0),
          legend.box.margin = margin(-10,5,0,0),
          panel.spacing = unit(0, "lines"),
          panel.background = element_blank(),
          panel.border = element_blank(),
          plot.background = element_blank(),
          plot.margin = margin(0, 7, 7, 7, "pt"),
          axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5, color = "black"),
          axis.title.y = element_blank(),
          axis.title.x = element_text(face = "bold", color = "black",size = 10),
          axis.ticks.y = element_blank(),
          axis.text.y = element_blank(),
          axis.line.y = element_blank(),
          axis.line.y.right = element_blank())
  # merge plot
  all_1 <- p1/p2 + patchwork::plot_layout(heights  = c(25, 1))
  all_2 <- p1_1/p2 + patchwork::plot_layout(heights  = c(25, 1))
  print(all_1|all_2)
  plot <- list(all_1,all_2)
  return(plot)
}
#####
DrawGeneSetViolin <- function(AnnotationData,genelist,group_by,plot_name){
  # AnnotationData1 <- data
  # genelist <- gene
  # group_by <- "annotation"
  # plot_name <- "test"
  list <- list(genelist)
  AnnotationDataobj <- addModuleScore(object = AnnotationData, features = list, name = "list")
  library(tidyverse)
  temp_data <- AnnotationDataobj@meta.data |> dplyr::select(c(group_by,"list1")) |> 
    mutate(group_by=factor(group_by))
    x = temp_data[,which(colnames(temp_data) == group_by)]
    p <- ggplot(data = temp_data,aes(x=  x,y= list1,fill=x)) +
    geom_violin(alpha = 0.5,color="black",position=position_dodge(width=0.8),size=0.75)+
    scale_fill_manual(values=colour1)+
    labs(x="Clusters",y="",title = plot_name) +
    theme_classic()+
    scale_y_continuous( n.breaks = 8,expand = c(0,0))+
    theme(panel.background =element_blank(),
          text = element_text(size = 6,family="sans"),
          legend.position="none",
          axis.text.x = element_text(hjust=0.9, vjust=.9,size = 6,face = "bold",angle=45),
          axis.text.y = element_text(hjust=0.5, vjust=.5,size = 6),
          axis.title.y = element_text(hjust=0.5, vjust=.5,size = 8,face = "bold"),
          axis.title.x = element_text(hjust=0.5, vjust=.5,size = 8,face = "bold"),
          plot.title = element_text(hjust = 0.5,size = 10, face = "bold"),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),       
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))
  print(p)
  return(p)
}
# 
drawheatmap <- function(data,gene_list,plot_name,figureDir){
  gene_list <- intersect(gene_list, rownames(GetAssayData(data, slot = 'data')))
  mat <- AverageExpression(data, features = gene_list, slot = 'data')
  mat1 <- t(scale(t(mat$RNA)))
  #change colname
  colnames(mat1) <- sub("g","",colnames(mat1))
  # setting color 
  paletteLength <- 50
  myColor <- viridis::viridis(paletteLength)
  myColor1 <- colorRampPalette(c('#1F3A93', '#FF4500'))(paletteLength)
  myColor2 <- colorRampPalette(c('lightgray', 'red'))(paletteLength)
  myBreaks <- c(seq(min(mat1), 0, length.out=ceiling(paletteLength/2) + 1), 
                seq(max(mat1)/paletteLength, max(mat1), length.out=floor(paletteLength/2)))
  anno_col <- as.data.frame(paste0("Cluster-",levels(data@meta.data$seurat_clusters)))
  colnames(anno_col) <- "Cluster ID"
  anno_col$`Cluster ID` <- factor(anno_col$`Cluster ID`)
  rownames(anno_col) <- colnames(mat1)
  pheatmap::pheatmap(
    mat1,
    border_color = NA,
    color = myColor,
    breaks = myBreaks,
    annotation_col = anno_col,
    angle_col = 0,
    cellwidth = 20,
    cellheight = 20,
    treeheight_row =6,
    treeheight_col=6,
    width=10,
    height=10,
    filename=file.path(figureDir,paste(plot_name,"-style-1.pdf")))
  pheatmap::pheatmap(mat1,
                     border_color = NA,
                     color = myColor1,
                     breaks = myBreaks,
                     annotation_col = anno_col,
                     angle_col = 0,
                     cellwidth = 20,
                     cellheight = 20,
                     treeheight_row =6,
                     treeheight_col=6,
                     width=10,
                     height=10,
                     filename=file.path(figureDir,paste(plot_name,"-style-2.pdf")))
  pheatmap::pheatmap(mat1,
                     border_color = NA,
                     color = myColor2,
                     breaks = myBreaks,
                     annotation_col = anno_col,
                     angle_col = 0,
                     cellwidth = 20,
                     cellheight = 20,
                     treeheight_row =6,
                     treeheight_col=6,
                     width=10,
                     height=10,
                     filename=file.path(figureDir,paste(plot_name,"-style-3.pdf")))
}
##########
# draw Multi Orig.ident FeaturePlot
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
        ggsave(file.path(figureDir,paste0("all_",gene,".pdf")),height = 10,width = 12,plot=all)
        ggsave(file.path(figureDir,paste0("all_",gene,".png")),height = 10,width = 12,dpi=400,plot=all)
      }else{
        if (length(plot_list) ==5){
          all =  plot_list[[1]] + plot_list[[2]] + plot_list[[3]] + plot_list[[4]] + plot_list[[5]] +patchwork::plot_layout(ncol = 2)
          ggsave(file.path(figureDir,paste0("all_",gene,".pdf")),height = 15,width = 12,plot=all)
          ggsave(file.path(figureDir,paste0("all_",gene,".png")),height = 15,width = 12,dpi=400,plot=all)
        }
      }
    }
  }
}
#-----------------------------------####---------------------------------------#
# draw two seurat object special gene vlnplot (add Ttest Pvalue)
DrawGeneVlnplotfortwodata <- function(Seuratlist,Seuratlistname,gene,y_text,y_max){
  # merge two data
  merge_seurat <-  merge(Seuratlist[[1]], y = Seuratlist[[2]], add.cell.ids = Seuratlistname)
  merge_seurat@meta.data$orig.ident <- factor(merge_seurat@meta.data$orig.ident,levels = Seuratlistname)
  # Extert data
  p <- VlnPlot(merge_seurat,gene,group.by = "orig.ident") + NoLegend()+
    stat_compare_means(label.x=1.3,method = "t.test",label.y = y_max*0.8)+
    scale_y_continuous(expand = c(0,0),n.breaks = 8,limits = c(0,y_max))+
    theme_classic()+
    xlab("")+
    theme(plot.title = element_text(hjust = 0.5,size=15),
          legend.position = "none",
          axis.text.x = element_text(angle = 45,vjust = 0.9,hjust = 0.9,size=10),
          axis.text.y = element_text(size=10),
          axis.title.y = element_text(size=12))
  # print plot
  print(p)
  # return
  return(p)
}
# draw two seurat object special gene Mean bar 
DrawGeneMeanBarplotfortwodata <- function(Seuratlist,Seuratlistname,gene){
  # barplot of gene Mean Expression
  data_1_AverageExpression <-  AverageExpression(Seuratlist[[1]],features = gene)
  data_1_AverageExpression_mean <- mean(data_1_AverageExpression$RNA)
  data_2_AverageExpression <- AverageExpression(Seuratlist[[2]],features = gene)
  data_2_AverageExpression_mean <- mean(data_2_AverageExpression$RNA)
  bar <- t(data.frame("data_1"=data_1_AverageExpression_mean,
                      "data_2"=data_2_AverageExpression_mean))
  data <- bar |> as.data.frame() |>  mutate(id = rownames(bar)) |> mutate(value = round(V1,4))
  data$id <- ifelse(data$id == "data_1",Seuratlistname[1],Seuratlistname[2])
  data$id <- factor(data$id,levels =Seuratlistname)
  y_cei <- ceiling(max(data$value))
  p <-   ggplot(data=data,aes(x=id,y=V1,fill=id))+
    ylab(paste0("Mean ",gene," Expression"))+
    xlab("")+
    ggtitle(gene)+
    geom_bar(stat = "identity",linewidth = 0.8,width=0.7) +
    geom_text(aes(x=id,y=(V1-0.5),label = value))+
    scale_y_continuous(expand = c(0,0),limits = c(0,y_cei),n.breaks = 8)+
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5,size=15),
          legend.position = "none",
          axis.text.x = element_text(angle = 45,vjust = 0.9,hjust = 0.9,size=10),
          axis.text.y = element_text(size=10),
          axis.title.y = element_text(size=12))
  # print
  print(p)
  # return
  return(p)
}
#-----------------------------------####---------------------------------------#
# Spatial RNA-seq analysis scripts
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
AddModuleScorePlot <- function(data,group_by,gene_set,plot_name){
  data@meta.data <- data@meta.data |> dplyr::select(c(`group_by`,`gene_set`)) 
  colnames(data@meta.data)[which(colnames(data@meta.data) == `group_by`)] <- "Type"
  p <- data@meta.data |> 
    mutate(Type=factor(Type)) |>
    ggplot(aes(x=Type,y=list1,fill=Type)) +
    geom_violin(alpha = 0.5,color="black",position=position_dodge(width=0.8),size=0.75)+
    scale_fill_manual(values=colour1) +
    labs(x=" ",y="",title = plot_name) +
    theme_classic()+
    theme(panel.background =element_blank(),
          text = element_text(size = 6,family="sans"),
          legend.position="none",
          axis.text.x = element_text(angle = 45,hjust=0.9, vjust=.9,size = 8),
          axis.text.y = element_text(hjust=0.5, vjust=.5),
          plot.title = element_text(hjust = 0.5,size = 10, face = "bold"),
          axis.line.x=element_line(linetype=1,color="black",size=0.2),       
          axis.line.y=element_line(linetype=1,color="black",size=0.2),
          axis.ticks.x=element_line(color="black",size=0.2,lineend = 1),
          axis.ticks.y=element_line(color="black",size=0.2,lineend = 1))
  return(p)
}
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
# ==============================================================================
# END 
# ==============================================================================