# ==============================================================================
# 09.04.vis_expression.r
# 功能：负责基因表达量的高级可视化
# 包括：堆叠小提琴图、热图、基因集打分（ModuleScore）小提琴图、多数据对比图
# ==============================================================================

#' 绘制堆叠小提琴图 (Type 1)
#'
#' @description 
#' 绘制多个基因在各 Cluster 中的表达量，以堆叠小提琴图（水平翻转）形式展示。
#' 类似于 Scanpy 的 `sc.pl.stacked_violin`。
#'
#' @param data Seurat 对象
#' @param features 基因列表
#' @return ggplot 对象
#' @export
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

#' 绘制堆叠小提琴图 (Type 2, 含注释条)
#'
#' @description 
#' 复杂的堆叠小提琴图，上方是表达量分布，下方是分组注释色块。
#' 需要 `Stackdata` 对象和额外的 `annotation` 信息。
#'
#' @param Stackdata Seurat 对象
#' @param annotation 包含 features 和 group 的注释数据框
#' @param name 图表标题前缀
#' @return 包含两个组合图的列表 (list(all_1, all_2))
#' @export
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

#' 绘制基因集打分的小提琴图
#'
#' @description 
#' 使用 `addModuleScore` 对基因集打分，并绘制各 Cluster 得分分布的小提琴图。
#'
#' @param AnnotationData Seurat 对象
#' @param genelist 基因列表
#' @param group_by 分组列名
#' @param plot_name 图表标题
#' @return ggplot 对象
#' @export
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

#' 绘制热图 (pheatmap)
#'
#' @description 
#' 计算平均表达量并绘制热图，生成三种配色方案的 PDF 文件：
#' 1. viridis
#' 2. 蓝红 (Blue-Red)
#' 3. 灰红 (Gray-Red)
#'
#' @param data Seurat 对象
#' @param gene_list 基因列表
#' @param plot_name 文件名前缀
#' @param figureDir 图片保存目录
#' @export
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

#' 绘制 ModuleScore 小提琴图
#'
#' @description 
#' 假设数据中已经计算了 ModuleScore（列名为 list1），绘制小提琴图。
#' 注意：函数假设 `gene_set` 列作为额外的分组或标记信息。
#'
#' @param data Seurat 对象
#' @param group_by 主分组列
#' @param gene_set 基因集标识列（未使用于绘图，仅作为 select）
#' @param plot_name 图表标题
#' @return ggplot 对象
#' @export
AddModuleScorePlot <- function(data,group_by,gene_set,plot_name){
  data@meta.data <- data@meta.data |> dplyr::select(c(group_by,gene_set)) 
  colnames(data@meta.data)[which(colnames(data@meta.data) == group_by)] <- "Type"
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

#' 绘制两个数据集的基因表达对比（小提琴图 + T检验）
#'
#' @description 
#' 合并两个 Seurat 对象，绘制指定基因在两组数据中的表达小提琴图，并进行 T 检验。
#'
#' @param Seuratlist Seurat 对象列表 (list(obj1, obj2))
#' @param Seuratlistname 数据集名称向量 (c("Name1", "Name2"))
#' @param gene 基因名称
#' @param y_text 未使用
#' @param y_max Y轴最大值限制
#' @return ggplot 对象
#' @export
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

#' 绘制两个数据集的基因平均表达量柱状图
#'
#' @description 
#' 计算并对比两个 Seurat 对象中指定基因的平均表达量。
#'
#' @param Seuratlist Seurat 对象列表
#' @param Seuratlistname 数据集名称向量
#' @param gene 基因名称
#' @return ggplot 对象
#' @export
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
# ==============================================================================
# END 
# ==============================================================================