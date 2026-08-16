# Author : zhang jian
# Date : 2024-12-13
# Version : 1.0.1v
#########################################################################
# Description : this scRNA-seq multithreds DEG scripts
# This script can take different information in the metadata of a Seurat object as grouping information, 
# perform differential analysis between one group and all other groups, and annotate the results of the differential analysis.
# DEG power 20 Threads
# SeuratObject : Seurat object
# groupby : meta.data group.by infor
# threads : DEG analysis Threads
# test_use : DEG stats test use methods
# only_pos : only keep positive DGE result
# logfc_threshold : DEG logfc_threshold cutoff dafult : 0.25
# pct_1 : DEG pct_1 cutoff dafult : 0.25
# p_val_adjCutoff : DEG p_val_adjCutoff cutoff dafult : 0.05
# LFCCutoff : DEG  LFCCutoff cutoff dafult : 0.5
# SaveDir : DEG result save dir
# taxid : Species taxid for DEG annotation
# multithreadingFindMarkerCluster(SeuratObject = data,groupby = 'seurat_clusters',
#                                 threads = 20,test_use = "wilcox",
#                                 only_pos = FALSE,logfc_threshold = 0.25,pct_1 = 0.25,
#                                 p_val_adjCutoff = 0.05,LFCCutoff = 0.5,
#                                 y_aes_value = 60,SaveDir = cluster_marker_gene_dir,taxid = 10090)
# DEG power Single Threads
# multithreadingFindMarkerCluster(SeuratObject = data,groupby = 'seurat_clusters',
#                                 threads = 1,test_use = "wilcox",
#                                 only_pos = FALSE,logfc_threshold = 0.25,pct_1 = 0.25,
#                                 p_val_adjCutoff = 0.05,LFCCutoff = 0.5,
#                                 y_aes_value = 60,SaveDir = cluster_marker_gene_dir,taxid = 10090)
# findmarker by special Treat_cells & Control_cells list
# FindMarkerClusterPair(data = ANN,
#                       Treat_cells = Treat_cd8_cells,
#                       Control_cells = Control_CD5_CD7_cells,
#                       Treat_name = 'TDD21&TDD28&TMD7&CD8+',Control_name = 'TDD14CD5+CD7+',
#                       test_use = "wilcox",only_pos = FALSE,logfc_threshold = 0.25,
#                       pct_1 = 0.25,p_val_adjCutoff = 0.05,LFCCutoff = 0.5,
#                       y_aes_value = 400,save_dir = SaveDir,taxid = 9606)
#
#########################################################################
# DEG Annotation Database
mus_gene_infor_dir = "/titan3/local_zhang_jian/database/genome/mm10/Mus_musculus.gene_info"
human_gene_infor_dir = '/titan3/local_zhang_jian/database/genome/hg19/Homo_sapiens.gene_info'
# log4r init functions
log4r_init <- function(){
  require(log4r)
  logger <- log4r::logger()
  my_layout <- function(level, ...) {
    require(crayon)
    if (level == 'INFO'){
      paste0(bold(cyan(format(Sys.time()), " [", level, " ] ➡️ ")),...,'\n',collapse = "\n")
    }else{
      if (level == 'WARN'){
        paste0(bold(yellow(format(Sys.time()), " [", level, " ] ❓ ")),...,'\n',collapse = "\n")
      }else{
        if (level == 'ERROR'){
          paste0(bold(red(format(Sys.time()), " [", level, "] 🧨 ")),...,'\n', collapse = "\n")
        }else{
          if (level == 'FATAL'){
            paste0(bold(bgRed(format(Sys.time()), " [", level, "] 💣 ")),...,'\n', collapse = "")
          }else{
            if (level == 'DEBUG'){
              paste0(bold(blue(format(Sys.time()), " [", level, "] 🔧 ")),...,'\n', collapse = "\n")
            }
          }
        }
      }
    }
  }
  logger <- log4r::logger(threshold = "INFO",appenders = list(console_appender(my_layout)))
  return(logger)
}
# DEG annotation functions
DEG_annotation <- function(filter_deg,taxid,
                           mus_gene_infor = mus_gene_infor_dir,
                           human_gene_infor = human_gene_infor_dir){
  require(tidyverse)
  mus_gene_infor <- mus_gene_infor
  human_gene_infor <- human_gene_infor
  # check taxid
  if (taxid %in% c(10090,9606)){
    if (taxid == 10090){
      info(logger,'Findmarker mouse DEG  result annotation')
      filter_deg <- filter_deg |> as.data.frame() |> tibble::rownames_to_column(var = 'Symbol')
      annotation = read.csv(mus_gene_infor,sep = '\t')
      annotation_deg <-  dplyr::left_join(filter_deg,annotation,by = "Symbol")
    }else{
      if (taxid == 9606){
        info(logger,'Findmarker human DEG  result annotation')
        filter_deg <- filter_deg |> as.data.frame() |> tibble::rownames_to_column(var = 'Symbol')
        annotation = read.csv(human_gene_infor,sep = '\t')
        annotation_deg <-  dplyr::left_join(filter_deg,annotation,by = "Symbol")
      }
    }
  }else{
    warn(logger,'Place check taxid')
  }
  return(annotation_deg)
}
# Draw VolcanoSCRNAFC_p_val_adj plot functions
DrawVolcanoSCRNAFC_p_val_adj <- function(deg_result,
                                         p_val_adjCutoff = 0.05,
                                         LFCCutoff = 0.5,
                                         name,deg_figure_dir,y_aes_value = 300){
  library(ggplot2)
  library(ggrepel)
  # deg_result <- filter_deg
  deg_result <- deg_result %>% mutate(log10 = -log10(p_val_adj)) |> mutate(log2FC = avg_log2FC) |> mutate(Symbol = rownames(deg_result))
  # add UP&DOWN&NO Symbol TAG
  deg_result$label = NA
  deg_result$Group <- "Non-significan"
  deg_result$Group[which((deg_result$p_val_adj < p_val_adjCutoff) & (deg_result$log2FC > LFCCutoff))] = "Up-regulated"
  deg_result$Group[which((deg_result$p_val_adj  < p_val_adjCutoff) & (deg_result$log2FC < -LFCCutoff))] = "Down-regulated"
  # extert Up & Down Gene
  deg_result_extert <- deg_result 
  deg_result_UP <- deg_result_extert |> filter(Group=="Up-regulated")
  deg_result_Down <- deg_result_extert |> filter(Group=="Down-regulated")
  deg_infor <-  data.frame("UP"=nrow(deg_result_UP),"DOWN"=nrow(deg_result_Down));rownames(deg_infor) <- paste0(name,"-DEG")
  write.csv(deg_result,file.path(deg_figure_dir,paste0(name,"-DEG.csv")),row.names =F)
  write.csv(deg_result_UP,file.path(deg_figure_dir,paste0(name,"-DEG-up.csv")),row.names =F)
  write.csv(deg_result_Down,file.path(deg_figure_dir,paste0(name,"-DEG-down.csv")),row.names =F)
  write.csv(deg_infor,file.path(deg_figure_dir,paste0(name,"-DEG-infor.csv")),row.names =F)
  # GET NOT&UP&DOWN DATA
  non_deg_result <- subset(deg_result,deg_result$Group =="Non-significan")
  up_deg_result <- subset(deg_result,deg_result$Group =="Up-regulated")
  down_deg_result <- subset(deg_result,deg_result$Group =="Down-regulated")
  # GET TOP 15 p_val Symbol UP&DOWN
  deg_result_up <- up_deg_result |> arrange(-avg_log2FC) |> head(15)
  deg_result_down <- down_deg_result |> arrange(avg_log2FC) |> head(15)
  # get y_aes
  y_aes <- deg_result$log10
  # get y_aes
  y_aes <- deg_result$log10
  # remove inf
  y_aes <- y_aes[is.finite(y_aes)]
  y_1 <- sort(y_aes, decreasing = TRUE)[1]
  y_2 <- sort(y_aes, decreasing = TRUE)[2]
  x_aes = 4
  y_aes_value = y_aes_value
  # draw volcano plot
  p <- ggplot(deg_result, aes(x = log2FC, y = log10)) +
    geom_point(data=non_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#C7C7C7",alpha=0.8) +
    geom_point(data=deg_result_up,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill="#e41749",alpha=0.5) +
    geom_point(data=up_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#e41749",alpha=0.4) +
    geom_point(data=deg_result_down,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill="#41b6e6",alpha=0.5) +
    geom_point(data=down_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#41b6e6",alpha=0.4) +
    geom_vline(xintercept=LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_vline(xintercept=-LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_hline(yintercept = 1.3,lty=2,col="black",lwd=0.1) +
    labs(x= bquote("scRNA-seq " * log[2] * " fold change " * .(name) * ""),y= expression(paste(-log[10], "p_val_adj")),title =paste0(name," Volcano Plot")) +
    geom_text_repel(data = deg_result_up,aes(log2FC, log10, label= Symbol),size=0.7,colour="black",fontface="bold.italic",
                    segment.alpha = 0.5,segment.size = 0.15,segment.color = "black",min.segment.length=0,
                    box.padding=unit(0.2, "lines"),point.padding=unit(0, "lines"),force = 20,max.iter = 3e3,
                    max.overlaps = 25,arrow=arrow(length = unit(0.02, "inches"))) +
    geom_text_repel(data = deg_result_down,aes(log2FC, log10, label= Symbol),size=0.7,colour="black",fontface="bold.italic",
                    segment.alpha =0.5,segment.size = 0.15,segment.color = "black",min.segment.length=0,
                    box.padding=unit(0.2, "lines"),point.padding=unit(0, "lines"),force = 20,max.iter = 3e3,
                    max.overlaps = 25,arrow=arrow(length = unit(0.02, "inches"))) +
    guides(color=guide_legend(override.aes = list(size=10)),) +
    scale_x_continuous(limits=c(-(x_aes*1.2),(x_aes*1.2)),n.breaks = 8) +
    scale_y_continuous(limits=c(0,y_aes_value),n.breaks = 10) +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5,size =3,family="sans"),legend.position="none",
          legend.title=element_text(size =4,face = "bold",family="sans"),
          text = element_text(size = 4,family="sans"),title = element_text(size = 4),
          axis.title.x = element_text(size = 3,family="sans",face = "bold"),
          axis.title.y = element_text(size = 3,family="sans",face = "bold"),
          axis.text.x = element_text(size = 2.5,family="sans"),
          axis.text.y = element_text(size = 2.5,family="sans"),
          axis.line.x=element_line(linetype=1,color="#606c70",size=0.2),
          axis.line.y=element_line(linetype=1,color="#606c70",size=0.2),
          axis.ticks.x=element_line(color="#606c70",size=0.15,lineend = 0.05),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.15,lineend = 0.05))
  # save plot
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type2.pdf")),plot = p,width = 4,height = 4,units = "cm")
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type2.png")),device = "png",plot = p,width = 4,height = 4,units = "cm",dpi = 1000)
  #
  p1 <- ggplot(deg_result, aes(x = log2FC, y = log10)) +
    geom_point(data=non_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#C7C7C7",alpha=0.8) +
    geom_point(data=deg_result_up,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill="#e41749",alpha=0.5) +
    geom_point(data=up_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#e41749",alpha=0.4) +
    geom_point(data=deg_result_down,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill="#41b6e6",alpha=0.5) +
    geom_point(data=down_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#41b6e6",alpha=0.4) +
    geom_vline(xintercept=LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_vline(xintercept=-LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_hline(yintercept = 1.3,lty=2,col="black",lwd=0.1) +
    labs(x= bquote("RNA-seq " * log[2] * " fold change " * .(name) * ""),y= expression(paste(-log[10], "p_val_adj")),title =paste0(name," Volcano Plot")) +
    guides(color=guide_legend(override.aes = list(size=10)),) +
    scale_x_continuous(limits=c(-(x_aes*1.2),(x_aes*1.2)),n.breaks = 8) +
    scale_y_continuous(limits=c(0,y_aes_value),n.breaks = 10) +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5,size =3,family="sans"),legend.position="none",
          legend.title=element_text(size =4,face = "bold",family="sans"),
          text = element_text(size = 4,family="sans"),title = element_text(size = 4),
          axis.title.x = element_text(size = 3,family="sans",face = "bold"),
          axis.title.y = element_text(size = 3,family="sans",face = "bold"),
          axis.text.x = element_text(size = 2.5,family="sans"),
          axis.text.y = element_text(size = 2.5,family="sans"),
          axis.line.x=element_line(linetype=1,color="#606c70",size=0.2),
          axis.line.y=element_line(linetype=1,color="#606c70",size=0.2),
          axis.ticks.x=element_line(color="#606c70",size=0.15,lineend = 0.05),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.15,lineend = 0.05))
  # save plot
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type1.pdf")),plot = p1,width = 4,height = 4,units = "cm")
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type1.png")),device = "png",plot = p1,width = 4,height = 4,units = "cm",dpi = 1000)
  #
  p2 <- ggplot(deg_result, aes(x = log2FC, y = log10)) +
    geom_point(data=non_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#C7C7C7",alpha=0.8) +
    geom_point(data=up_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#e41749",alpha=0.4) +
    geom_point(data=down_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#41b6e6",alpha=0.4) +
    geom_vline(xintercept=LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_vline(xintercept=-LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_hline(yintercept = 1.3,lty=2,col="black",lwd=0.1) +
    labs(x= bquote("RNA-seq " * log[2] * " fold change " * .(name) * ""),y= expression(paste(-log[10], "p_val_adj")),title =paste0(name," Volcano Plot")) +
    guides(color=guide_legend(override.aes = list(size=10)),) +
    scale_x_continuous(limits=c(-(x_aes*1.2),(x_aes*1.2)),n.breaks = 8) +
    scale_y_continuous(limits=c(0,y_aes_value),n.breaks = 10) +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5,size =3,family="sans"),legend.position="none",
          legend.title=element_text(size =4,face = "bold",family="sans"),
          text = element_text(size = 4,family="sans"),title = element_text(size = 4),
          axis.title.x = element_text(size = 3,family="sans",face = "bold"),
          axis.title.y = element_text(size = 3,family="sans",face = "bold"),
          axis.text.x = element_text(size = 2.5,family="sans"),
          axis.text.y = element_text(size = 2.5,family="sans"),
          axis.line.x=element_line(linetype=1,color="#606c70",size=0.2),
          axis.line.y=element_line(linetype=1,color="#606c70",size=0.2),
          axis.ticks.x=element_line(color="#606c70",size=0.15,lineend = 0.05),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.15,lineend = 0.05))
  # save plot
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type3.pdf")),plot = p2,width = 4,height = 4,units = "cm")
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type3.png")),device = "png",plot = p2,width = 4,height = 4,units = "cm",dpi = 1000)
}
# FindMarkerCluster functions
FindMarkerCluster <- function(data = SeuratObject,Cluster = 0,test_use = "wilcox",only_pos = FALSE,logfc_threshold = 0.25,
                              groupby = 'seurat_clusters',pct_1 = 0.25,p_val_adjCutoff = 0.05,LFCCutoff = 0.5,
                              y_aes_value = 60,save_dir = SaveDir,taxid = 9606){
  require(tidyverse)
  require(Seurat)
  require(log4r)             
  data@meta.data <- data@meta.data |> dplyr::rename("Group" = `groupby`)
  # extert cell cluster for group1
  cells1 <- subset(data@meta.data, Group %in% Cluster ) %>% rownames()
  # extert cell cluster for group2
  cells2 <- subset(data@meta.data, !Group %in% Cluster) %>% rownames()
  # use MAST DEG
  deg <- FindMarkers(data, ident.1 = cells1, ident.2 = cells2,
                     only.pos = only_pos,
                     test.use = test_use,
                     logfc.threshold = logfc_threshold)
  deg_dir <- file.path(save_dir,paste0("Cluster_",Cluster,'_vs_',"Other_Cluster"))
  info(logger,paste0(`groupby`,"-",Cluster,' : FindMarkers Result Save at : ',deg_dir))
  dir.create(deg_dir)
  info(logger, paste0(`groupby`,"-",Cluster,' : FindMarkers pct.1 threshold :',pct_1))
  filter_deg <-  deg |> dplyr::filter(pct.1 > pct_1)
  filter_deg <- DEG_annotation(filter_deg,taxid)
  rownames(filter_deg) <- filter_deg$Symbol
  name = paste0("Cluster_",Cluster,'_vs_',"Other_Cluster")
  info(logger,paste0(`groupby`,"-",Cluster," : Draw Volcano Plot : ","Cluster_",Cluster,'_vs_',"Other_Cluster"))
  DrawVolcanoSCRNAFC_p_val_adj(filter_deg,p_val_adjCutoff,
                               LFCCutoff,name,deg_dir,y_aes_value = y_aes_value)
  info(logger, crayon::bgCyan(paste0(`groupby`,"-",Cluster,' : FindMarkers DONE ')))
}
# FindMarkerClusterPair
FindMarkerClusterPair <- function(data = SeuratObject,Treat_cells = Treat_cells,Control_cells = Control_cells,
                                  Treat_name = 'Treat',Control_name = 'Control',
                                  test_use = "wilcox",only_pos = FALSE,logfc_threshold = 0.25,
                                  pct_1 = 0.25,p_val_adjCutoff = 0.05,LFCCutoff = 0.5,
                                  y_aes_value = 60,save_dir = SaveDir,taxid = 9606){
  require(tidyverse)
  require(Seurat)
  require(log4r)             
  # extert cell cluster for group1
  cells1 <- Treat_cells
  # extert cell cluster for group2
  cells2 <- Control_cells
  # use MAST DEG
  deg <- FindMarkers(data, ident.1 = cells1, ident.2 = cells2,
                     only.pos = only_pos,
                     test.use = test_use,
                     logfc.threshold = logfc_threshold)
  deg_dir <- file.path(save_dir,paste0(Treat_name ,' vs ',Control_name))
  info(logger,paste0(Treat_name ,' vs ',Control_name,' : FindMarkers Result Save at : ',save_dir))
  dir.create(deg_dir)
  info(logger, paste0(Treat_name ,' vs ',Control_name,' : FindMarkers pct.1 threshold :',pct_1))
  filter_deg <-  deg |> dplyr::filter(pct.1 > pct_1)
  filter_deg <- DEG_annotation(filter_deg,taxid)
  rownames(filter_deg) <- filter_deg$Symbol
  name = paste0(Treat_name ,' vs ',Control_name)
  info(logger,paste0(Treat_name ,' vs ',Control_name," : Draw Volcano Plot : ",Treat_name,' vs ',Control_name))
  DrawVolcanoSCRNAFC_p_val_adj(filter_deg,p_val_adjCutoff,
                               LFCCutoff,name,deg_dir,y_aes_value = y_aes_value)
  info(logger, crayon::bgCyan(paste0(Treat_name ,' vs ',Control_name,' : FindMarkers DONE ')))
}
# FindMarkerCluster functions
FindMarkerCluster_parallel <- function(params){
  # data = param_list[[1]]$data
  # Cluster = param_list[[1]]$Cluster
  # test.use = param_list[[1]]$test.use
  # only.pos = param_list[[1]]$only.pos
  # logfc.threshold = param_list[[1]]$logfc.threshold
  # pct_1 = param_list[[1]]$pct_1
  # group_by = param_list[[1]]$group_by
  # p_val_adjCutoff = param_list[[1]]$p_val_adjCutoff
  # LFCCutoff = param_list[[1]]$LFCCutoff
  # y_aes_value = param_list[[1]]$y_aes_value
  # save_dir = param_list[[1]]$save_dir
  # taxid = param_list[[1]]$taxid     
  data = params$data
  Cluster = params$Cluster
  test.use = params$test.use
  only.pos = params$only.pos
  logfc.threshold = params$logfc.threshold
  pct_1 = params$pct_1
  group_by = params$group_by
  p_val_adjCutoff = params$p_val_adjCutoff
  LFCCutoff = params$LFCCutoff
  y_aes_value = params$y_aes_value
  save_dir = params$save_dir
  taxid = params$taxid                      
  require(tidyverse)
  require(Seurat)
  require(log4r)
  data@meta.data <- data@meta.data |> dplyr::rename("Group" = `group_by`)
  # extert cell cluster for group1
  cells1 <- subset(data@meta.data, Group %in% Cluster ) %>% rownames()
  # extert cell cluster for group2
  cells2 <- subset(data@meta.data, ! Group %in% Cluster) %>% rownames()
  # use MAST DEG
  deg <- FindMarkers(data, ident.1 = cells1, ident.2 = cells2,
                     only.pos = only.pos,
                     test.use = test.use,
                     logfc.threshold = logfc.threshold)
  deg_dir <- file.path(save_dir,paste0("Cluster_",Cluster,'_vs_',"Other_Cluster"))
  info(logger,paste0(`group_by`,"-",Cluster,' : FindMarkers Result Save at : ',deg_dir))
  dir.create(deg_dir)
  info(logger, paste0(`group_by`,"-",Cluster,' : FindMarkers pct.1 threshold :',pct_1))
  filter_deg <-  deg |> dplyr::filter(pct.1 > pct_1)
  filter_deg <- DEG_annotation(filter_deg,taxid)
  rownames(filter_deg) <- filter_deg$Symbol
  name = paste0("Cluster_",Cluster,'_vs_',"Other_Cluster")
  info(logger,paste0(`group_by`,"-",Cluster," : Draw Volcano Plot : ","Cluster_",Cluster,'_vs_',"Other_Cluster"))
  DrawVolcanoSCRNAFC_p_val_adj(filter_deg,p_val_adjCutoff,
                               LFCCutoff,name,deg_dir,y_aes_value = y_aes_value)
  info(logger, crayon::bgCyan(paste0(`group_by`,"-",Cluster,' : FindMarkers DONE ')))
}
# multithreadingFindMarkerCluster
multithreadingFindMarkerCluster <- function(SeuratObject = Seurat,groupby = 'seurat_clusters',threads = 20,test_use = "wilcox",
                                            only_pos = FALSE,logfc_threshold = 0.25,pct_1 = 0.25,p_val_adjCutoff = 0.05,
                                            LFCCutoff = 0.5,y_aes_value = 60,SaveDir = cluster_marker_gene_dir,taxid = 9606){
  # SeuratObject <- data
  require(parallel)
  # SeuratObject <- JoinLayers(SeuratObject)
  if (all((table(gsub("^.*[s|a].",'',Layers(SeuratObject))))  > 1) %in% FALSE ){
    SeuratObject <- JoinLayers(SeuratObject)
  }
  logger <- log4r_init()
  if (threads > 1){
    info(logger, paste0('FindMarkers Power by Multithreads '))
    cell_cluster_list <- as.list(names(table(SeuratObject[[`groupby`]])))
    info(logger, paste0('FindMarkers Use ',threads,' Threads '))
    param_list <- lapply(cell_cluster_list, function(x) list(
      Cluster = x, 
      data = SeuratObject, 
      test.use = test_use,
      only.pos = only_pos,
      logfc.threshold = logfc_threshold,
      pct_1 = pct_1,
      group_by = groupby,
      p_val_adjCutoff = p_val_adjCutoff,
      LFCCutoff = LFCCutoff,
      y_aes_value = y_aes_value,
      save_dir = SaveDir,
      taxid = taxid
    ))
    # debug
    # print( param_list )
    mclapply(param_list, FindMarkerCluster_parallel, mc.cores = threads,
             mc.preschedule = F)
    info(logger, paste0('FindMarkers Multithreads Done'))
  }else{
    info(logger, paste0('FindMarkers Power by FindMarkerCluster'))
    cell_cluster_list <- levels(SeuratObject$seurat_clusters)
    for ( i  in cell_cluster_list){
      info(logger, paste0('FindMarkers ',i,' Cluster Marker'))
      FindMarkerCluster(data = SeuratObject,
                        groupby = groupby,
                        Cluster = i,
                        test_use = test_use,
                        only_pos = only_pos,
                        logfc_threshold = logfc_threshold,
                        pct_1 = pct_1,
                        p_val_adjCutoff = p_val_adjCutoff,
                        LFCCutoff = LFCCutoff,
                        y_aes_value = y_aes_value,
                        save_dir = SaveDir,
                        taxid = taxid)
    }
    info(logger, paste0('FindMarkers Done'))
  }
}
###########################