# author : zhang jian
# date : 2025-2-7
# version :  1.2.1v
# description : this is patch celltype levels deg scripts
#--------------------------#
# [skill 改造记录] skills/scrna-deg-analysis (OmicHub OSDP v1.0), 2026-08-03:
#   1. 移除 mus_gene_infor / human_gene_infor 默认参数中的 /titan3/ 硬编码路径,
#      改为从环境变量 SCRNA_DEG_REF_DIR 拼接 (默认相对目录 DEG_Annotation_reference);
#   2. DEG_annotation 读注释文件前新增文件存在性检查, 缺失时给出设置
#      SCRNA_DEG_REF_DIR 的可读报错 (原为 read.csv 直接报错);
#   3. 修复 logger 作用域 bug: check_parameter / DEG_annotation 为全局函数,
#      其自由变量 logger 按词法作用域解析到 log4r::logger 构造函数 (closure),
#      导致 info(logger, ...) 报 "object of type 'closure' is not subsettable";
#      现改为两个函数新增 logger 形参, 由主函数显式传入;
#   4. 兼容 ggplot2 4.x: element_line(lineend = 0.05) 在 4.x 下报
#      "@lineend must be <character> or <NULL>", 统一改为 lineend = "butt" (共 6 处)。
#   其余逻辑与原 tools/DEG/FindMarkers_Celltype_group/FindMarkers_Celltype_group.r 一致。
#--------------------------#
##### FindMarkers_Celltype_group parameter
#@ Seurat     : Seurat object 
#@ Celltype   : patch DEG analysis levels
#@ Pair       : patch DEG analysis pair infor in mete.data
#@ Treat      : patch DEG analysis Treat group name
#@ Control    : patch DEG analysis Treat Control name
#@ test       : Denotes which test to use
#@ pvalCutoff : DEG gene filter standard 
#@ LFCCutoff  : DEG gene filter standard
#@ logfc.threshold : DEG gene filter standard
#@ pct_1           : DEG gene filter standard
#@ taxid           : DEG result annotation
#@ mus_gene_infor  : mouse DEG annotation refernece
#@ human_gene_infor: human DEG annotation refernece
#@ save_dir        : DEG & DrawVolcano Save PATH
#@ y_aes_value     : DrawVolcano plot y aes limt
#@ top_gene        : tag up & down top gene number (dafult:15)
#@ fix_deg_result  : fix deg_result  pvalue = 0
#@ Volcano_text_size   : Volcano tag text size  (dafult : 0.5)
#@ Volcano_fontface    : Volcano tag text fontface (dafult : "plain") Font face : "plain", "bold", "italic", "bold.italic"
#@ Volcano_plot_width  : Save Volcano plot width (dafult : 6)
#@ Volcano_plot_height : Save Volcano plot height (dafult : 4)
#@ up_color   : Volcano plot up gene color (dafult : '#e41749')
#@ down_color : Volcano plot down gene color (dafult : '#41b6e6')
#--------------------------#
# help & visablity module
# log4r init module
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
# check_parameter function (logger 由调用方显式传入, 避免词法作用域解析到 log4r::logger)
check_parameter <- function(Seurat,Celltype,Pair,
                            Treat,Control,mus_gene_infor,human_gene_infor,
                            logger){
  # check Celltype & Pair setting
  if (Celltype %in% colnames(Seurat@meta.data) & Pair %in% colnames(Seurat@meta.data)){
    info(logger,'Check Celltype & Pair setting PASS')
  }else{
    warn(logger,'Place check Celltype & Pair setting')
  }
  # check & Pair setting
  if (Treat %in% levels(factor(Seurat@meta.data[[Pair]])) & Control %in% levels(factor(Seurat@meta.data[[Pair]]))){
    info(logger,'Check Pair group inforPASS')
    }else{
    warn(logger,'Place check Pair group infor')
  }
  # check deg annotation reference
  if (file.exists(mus_gene_infor) & file.exists(human_gene_infor)){
    info(logger,'Check mus & human annotation reference file PASS')
  }else{
    warn(logger,'Place check mus & human annotation reference file')
  }
}
# check DEG annotation reference file, readable error instead of raw read.csv failure
.check_deg_ref_file <- function(ref_file, taxid) {
  if (!file.exists(ref_file)) {
    stop(paste0(
      'DEG 注释参考文件缺失 (taxid=', taxid, '): ', ref_file, '\n',
      '请设置环境变量 SCRNA_DEG_REF_DIR 指向 gene_info 目录 ',
      '(目录内需含 mm10_Mus_musculus.gene_info / hg19_Homo_sapiens.gene_info), ',
      '例如仓库内参考: tools/DEG/DEG_Annotation_reference/'))
  }
}
# findmarker deg rseult annotation module (logger 由调用方显式传入)
DEG_annotation <- function(filter_deg,taxid=9606,
                          mus_gene_infor,
                          human_gene_infor,
                          logger){
  # loading packages
  require(tidyverse)
  mus_gene_infor <- mus_gene_infor
  human_gene_infor <- human_gene_infor
  # check taxid
  if (taxid %in% c(10090, 9606)) {
  if (taxid == 10090) {
    info(logger, 'Findmarker mouse DEG result annotation')
    .check_deg_ref_file(mus_gene_infor, taxid)

    rownames(filter_deg) <- make.unique(rownames(filter_deg))
    
    filter_deg <- filter_deg |> as.data.frame() |> tibble::rownames_to_column(var = 'Symbol')
    filter_deg <- filter_deg[!duplicated(filter_deg$Symbol), ]  # 移除重复的行
    annotation <- read.csv(mus_gene_infor, sep = '\t')
    annotation_deg <- dplyr::left_join(filter_deg, annotation, by = "Symbol")
  } else if (taxid == 9606) {
    info(logger, 'Findmarker human DEG result annotation')
    .check_deg_ref_file(human_gene_infor, taxid)

    rownames(filter_deg) <- make.unique(rownames(filter_deg))
    
    filter_deg <- filter_deg |> as.data.frame() |> tibble::rownames_to_column(var = 'Symbol')
    filter_deg <- filter_deg[!duplicated(filter_deg$Symbol), ]  # 移除重复的行
    annotation <- read.csv(human_gene_infor, sep = '\t')
    annotation_deg <- dplyr::left_join(filter_deg, annotation, by = "Symbol")
  }
  }else{
    warn(logger,'Place check taxid')
  }
  return(annotation_deg)
}
# visablity volcano_plot_type1
TaggeneVolcanoPlot <- function(deg_result = deg_result,
                               non_deg_result = non_deg_result,
                               deg_result_up = deg_result_up,
                               up_deg_result = up_deg_result,
                               deg_result_down = deg_result_down,
                               down_deg_result = down_deg_result,
                               LFCCutoff = 1,
                               up_color = '#e41749',
                               down_color = '#41b6e6',
                               text_size = 0.5,
                               fontface = "plain",
                               name = 'volcano type1',
                               top_gene = 20,
                               subtitle = T,
                               y_aes_value = 320,
                               x_aes = 10,
                               deg_figure_dir =deg_figure_dir,
                               plot_width = 6,
                               plot_height = 4){
  # loading packages
  require(ggplot2)
  library(ggrepel)
  # draw plot
  p <- ggplot(deg_result, aes(x = log2FC, y = log10)) +
  geom_point(data=non_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#C7C7C7",alpha=0.8) +
  geom_point(data=deg_result_up,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill=up_color,alpha=0.5) +
  geom_point(data=up_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color=up_color,alpha=0.4) +
  geom_point(data=deg_result_down,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill=down_color,alpha=0.5) +
  geom_point(data=down_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color=down_color,alpha=0.4) +
  geom_vline(xintercept=LFCCutoff,lty=2,col="black",lwd=0.1) +
  geom_vline(xintercept=-LFCCutoff,lty=2,col="black",lwd=0.1) +
  geom_hline(yintercept = 1.3,lty=2,col="black",lwd=0.1) +
  labs(x= bquote(log[2] * " fold change " * .(name) * ""),y= expression(paste(-log[10], " adjusted P-value")),title =paste0(name)) +
  geom_text_repel(data = deg_result_up,aes(log2FC, log10, label= Symbol),size=text_size,colour="black",fontface=fontface,
                  segment.alpha = 0.5,segment.size = 0.15,segment.color = "black",min.segment.length=0,
                  box.padding=unit(0.2, "lines"),point.padding=unit(0, "lines"),force = 20,max.iter = 3e3,
                  max.overlaps = 25,arrow=arrow(length = unit(0.02, "inches"))) +
  geom_text_repel(data = deg_result_down,aes(log2FC, log10, label= Symbol),size=text_size,colour="black",fontface=fontface,
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
        axis.ticks.x=element_line(color="#606c70",size=0.15,lineend = "butt"),
        axis.ticks.length=unit(.08,"lines"),
        axis.ticks.y=element_line(color="#606c70",size=0.15,lineend = "butt"))
    if (subtitle == T){
    p <- p + labs(subtitle =  paste0('gene symbol labeled for top ',top_gene,' log2FC up/down regulated'))+
    theme(plot.title = element_text(hjust = 0,size =5,family="sans",face = "bold",margin = margin(b = 2)),
          plot.subtitle = element_text(hjust = 0,size =3,family="sans",margin = margin(t = -1)))
    }
  # save plot
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type2.pdf")),plot = p,width = plot_width,height = plot_height,units = "cm")
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type2.png")),device = "png",plot = p,width = plot_width,height = plot_height,units = "cm",dpi = 1000)
}
# VolcanoPlot plot type1
VolcanoPlot1 <- function(deg_result = deg_result,non_deg_result = non_deg_result,
                        deg_result_up = deg_result_up,up_deg_result = up_deg_result,
                        deg_result_down = deg_result_down,down_deg_result = down_deg_result,
                        LFCCutoff = 1,up_color = '#e41749',down_color = '#41b6e6',
                        name = 'volcano type1',y_aes_value = 320,x_aes = 10,
                        deg_figure_dir =deg_figure_dir,plot_width = 6,plot_height = 4){
  # loading packages
  require(ggplot2)
  library(ggrepel)
  # draw plot
  p1 <- ggplot(deg_result, aes(x = log2FC, y = log10)) +
    geom_point(data=non_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#C7C7C7",alpha=0.8) +
    geom_point(data=deg_result_up,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill=up_color,alpha=0.5) +
    geom_point(data=up_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color=up_color,alpha=0.4) +
    geom_point(data=deg_result_down,aes(x = log2FC, y = log10),size=0.02,shape = 21,fill=down_color,alpha=0.5) +
    geom_point(data=down_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color=down_color,alpha=0.4) +
    geom_vline(xintercept=LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_vline(xintercept=-LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_hline(yintercept = 1.3,lty=2,col="black",lwd=0.1) +
    labs(x= bquote(log[2] * " fold change " * .(name) * ""),y= expression(paste(-log[10], " adjusted P-value")),title =paste0(name)) +
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
          axis.ticks.x=element_line(color="#606c70",size=0.15,lineend = "butt"),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.15,lineend = "butt"))
  # save plot
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type1.pdf")),plot = p1,width = plot_width,height = plot_height,units = "cm")
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type1.png")),device = "png",plot = p1,width = plot_width,height = plot_height,units = "cm",dpi = 1000)
}
# # VolcanoPlot plot type2
VolcanoPlot2 <- function(deg_result = deg_result,non_deg_result = non_deg_result,
                        deg_result_up = deg_result_up,up_deg_result = up_deg_result,
                        deg_result_down = deg_result_down,down_deg_result = down_deg_result,
                        up_color = '#e41749',down_color = '#41b6e6',LFCCutoff = 1,
                        name = 'volcano type1',y_aes_value = 320,x_aes = 10,
                        deg_figure_dir =deg_figure_dir,plot_width = 6,plot_height = 4){
  # loading packages
  require(ggplot2)
  library(ggrepel) 
  p2 <- ggplot(deg_result, aes(x = log2FC, y = log10)) +
    geom_point(data=non_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#C7C7C7",alpha=0.8) +
    geom_point(data=up_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#e41749",alpha=0.4) +
    geom_point(data=down_deg_result,aes(x = log2FC, y = log10),size=0.02,shape = 21,color="#41b6e6",alpha=0.4) +
    geom_vline(xintercept=LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_vline(xintercept=-LFCCutoff,lty=2,col="black",lwd=0.1) +
    geom_hline(yintercept = 1.3,lty=2,col="black",lwd=0.1) +
    labs(x= bquote(log[2] * " fold change " * .(name) * ""),y= expression(paste(-log[10], " adjusted P-value")),title =paste0(name)) +
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
          axis.ticks.x=element_line(color="#606c70",size=0.15,lineend = "butt"),
          axis.ticks.length=unit(.08,"lines"),
          axis.ticks.y=element_line(color="#606c70",size=0.15,lineend = "butt"))
  # save plot
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type3.pdf")),plot = p2,width = plot_width,height = plot_height,units = "cm")
  ggsave(file.path(deg_figure_dir,paste0(name," Volcano Plot-FC-type3.png")),device = "png",plot = p2,width = plot_width,height = plot_height,units = "cm",dpi = 1000)
}
DrawVolcanoSCRNAFC_p_val_adj <- function(deg_result,p_val_adjCutoff = 0.05,LFCCutoff =1,name = 'Volcano',deg_figure_dir = deg_figure_dir,y_aes_value = 300,top_gene = 15,
                                          text_size =0.5,fontface = "bold.italic",plot_width = 6,plot_height =4,up_color = '#e41749',down_color = '#41b6e6'){
  # loading packages
  require(ggplot2)
  require(ggrepel)
  require(tidyverse)
  # deg_result <- filter_deg
  deg_result <- deg_result |> mutate(log10 = -log10(p_val_adj)) |> mutate(log2FC = avg_log2FC) |> mutate(Symbol = rownames(deg_result))
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
  deg_result_up <- up_deg_result |> arrange(-avg_log2FC) |> head(top_gene)
  deg_result_down <- down_deg_result |> arrange(avg_log2FC) |> head(top_gene)
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
  # draw add gene tag volcano plot 
  TaggeneVolcanoPlot(deg_result = deg_result,non_deg_result = non_deg_result,
                     deg_result_up = deg_result_up,up_deg_result = up_deg_result,
                     deg_result_down = deg_result_down,down_deg_result = down_deg_result,
                     LFCCutoff = LFCCutoff,up_color = up_color,down_color = down_color,
                     name = name,y_aes_value = y_aes_value,x_aes = x_aes,deg_figure_dir =deg_figure_dir,
                     plot_width = plot_width,plot_height = plot_height,top_gene = top_gene ,
                     subtitle = T)
  # draw volcano plot type1
  VolcanoPlot1(deg_result = deg_result,non_deg_result = non_deg_result,
              deg_result_up = deg_result_up,up_deg_result = up_deg_result,
              deg_result_down = deg_result_down,down_deg_result = down_deg_result,
              up_color = up_color,down_color = down_color,LFCCutoff = LFCCutoff,
              name = name,y_aes_value =  y_aes_value,x_aes = x_aes,
              deg_figure_dir =deg_figure_dir,plot_width = plot_width,plot_height = plot_height)
  # draw volcano plot type2
  VolcanoPlot2(deg_result = deg_result,non_deg_result = non_deg_result,
              deg_result_up = deg_result_up,up_deg_result = up_deg_result,
              deg_result_down = deg_result_down,down_deg_result = down_deg_result,
              up_color = up_color,down_color = down_color,LFCCutoff = LFCCutoff,
              name = name,y_aes_value =  y_aes_value,x_aes = x_aes,
              deg_figure_dir =deg_figure_dir,plot_width = plot_width,plot_height = plot_height)
}
# main function
FindMarkers_Celltype_group <- function(Seurat,Celltype = 'celltype',Pair = 'group',
                                       Treat = 'Treat',Control = 'Control',test = 'wilcox',
                                       pvalCutoff = 0.05,LFCCutoff=1,logfc.threshold = log(2),pct_1 = 0.25,
                                       taxid = 9606 ,save_dir = './',y_aes_value = 300,top_gene = 15,
                                       fix_deg_result = F,Volcano_text_size = 0.5 ,Volcano_fontface = "plain",
                                       Volcano_plot_width = 6,Volcano_plot_height =4,up_color = '#e41749',down_color = '#41b6e6',
                                       mus_gene_infor = file.path(Sys.getenv('SCRNA_DEG_REF_DIR', unset = 'DEG_Annotation_reference'), 'mm10_Mus_musculus.gene_info'),
                                       human_gene_infor = file.path(Sys.getenv('SCRNA_DEG_REF_DIR', unset = 'DEG_Annotation_reference'), 'hg19_Homo_sapiens.gene_info')){
  # LOADING PACAKGES
  require(tidyverse)
  require(Seurat)
  require(crayon)
  require(ggplot2)
  require(log4r)
  # loading log module
  logger <- log4r_init()
  list <- levels(factor(Seurat@meta.data[[`Celltype`]]))
  info(logger, paste0('FindMarkers levels : ',Celltype))
  check_parameter(Seurat,Celltype,Pair,
                  Treat,Control,mus_gene_infor,human_gene_infor,logger)
  Seurat@meta.data$Celltype_Rename <-  Seurat@meta.data[[Celltype]]
  Seurat@meta.data <- Seurat@meta.data |> dplyr::rename(Pair = `Pair` )
  for (i in list){
    info(logger, crayon::bgCyan('FindMarkers ################################# DO '))
    info(logger, paste0('FindMarkers Treat group :',Treat))
    cells1 <- subset(Seurat@meta.data,Pair == Treat & Celltype_Rename == i )  |> rownames()
    info(logger, paste0('FindMarkers Control group :',Control))
    cells2 <- subset(Seurat@meta.data,Pair == Control & Celltype_Rename == i )  |> rownames()
    info(logger, paste0('FindMarkers ',i,' Celltype ',Treat,' vs ',Control,' Marker'))
    info(logger, paste0('FindMarkers logfc.threshold :',logfc.threshold))

  DEG <- tryCatch({
    FindMarkers(Seurat,
                ident.1 = cells1,
                ident.2 = cells2,
                only.pos = FALSE,
                logfc.threshold = logfc.threshold,
                test.use = test)
  }, error = function(e) {
    info(logger, paste0("FindMarkers failed: ", e$message))
    return(NULL)
  })

  if (!is.null(DEG)) {
    if (fix_deg_result == TRUE) {
      min_value <- .Machine$double.xmin
      info(logger, paste0("Fix p_val_adj = 0"))
      DEG <- DEG |> dplyr::mutate(p_val_adj = ifelse(p_val_adj == 0, min_value, p_val_adj))
    }

    if (grepl("/", i)) {
      i <- gsub('/', "-", i)
    }

    deg_dir <- file.path(save_dir, paste0(Treat, '_vs_', Control, '-', i))
    info(logger, paste0('FindMarkers Result Save at : ', deg_dir))
    dir.create(deg_dir, showWarnings = FALSE)

    info(logger, paste0('FindMarkers pct.1 threshold :', pct_1))

    filter_deg <- tryCatch({
      DEG |> dplyr::filter(pct.1 > pct_1)
    }, error = function(e) {
      info(logger, paste0("Filtering DEG failed: ", e$message))
      return(NULL)
    })

    if (!is.null(filter_deg)) {
      filter_deg <- tryCatch({
        DEG_annotation(filter_deg, taxid, mus_gene_infor, human_gene_infor, logger)
      }, error = function(e) {
        info(logger, paste0("DEG annotation failed: ", e$message))
        return(NULL)
      })

      if (!is.null(filter_deg)) {
        
        filter_deg <- filter_deg[!duplicated(filter_deg$Symbol), ] 
        rownames(filter_deg) <- filter_deg$Symbol

        name <- paste0(Treat, ' vs ', Control, i)

        info(logger, paste0('Draw Volcano Plot : ', Treat, ' vs ', Control, i))
        tryCatch({
          DrawVolcanoSCRNAFC_p_val_adj(
            filter_deg,
            p_val_adjCutoff = pvalCutoff,
            LFCCutoff = LFCCutoff,
            name = name,
            deg_figure_dir = deg_dir,
            y_aes_value = y_aes_value,
            top_gene = top_gene,
            text_size = Volcano_text_size,
            fontface = Volcano_fontface,
            plot_width = Volcano_plot_width,
            plot_height = Volcano_plot_height
          )
        }, error = function(e) {
          info(logger, paste0("Drawing Volcano Plot failed: ", e$message))
        })
      }
    }
  }

  # 记录完成信息
  info(logger, crayon::bgCyan('FindMarkers ################################# DONE '))
  }
}
# End