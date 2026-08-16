# ==============================================================================
# 09.03.vis_proportions.r
# 功能：负责细胞比例统计与可视化
# 包括：堆叠柱状图展示各样本/分组中细胞类型的占比
# ==============================================================================

#' 统计并绘制细胞 Cluster 比例 (orig.ident)
#'
#' @description 
#' 统计 `orig.ident` 中各细胞 Cluster 的比例，绘制堆叠柱状图。
#' 自动根据 Cluster 数量调整图例和宽度。
#' 结果保存为 CSV 和 PDF/PNG。
#'
#' @param data Seurat 对象
#' @param name_plot 文件名标识
#' @param title_name 图表标题
#' @return ggplot 对象
#' @export
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

#' 统计并绘制细胞 Cluster 比例 (scCustomize 配色)
#'
#' @description 
#' 类似于 `states_cell_cluster_rate`，但使用 `scCustomize_Palette` 配色，
#' 并允许指定分组列 `group.by`。
#'
#' @param data Seurat 对象
#' @param name_plot 文件名标识
#' @param title_name 图表标题
#' @param group.by 分组依据的列名（在 meta.data 中）
#' @return ggplot 对象
#' @export
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
  colnames(data@meta.data)[which(colnames(data@meta.data) == group.by)] <- "Group"
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

#' 组合 UMAP 与比例图
#'
#' @description 
#' 计算指定 Group 和 Celltype 的比例，绘制堆叠图，并与给定的 UMAP 图（`umap_plot`）组合。
#' 需要 `patchwork` 包。
#'
#' @param data 数据框（含 Celltype 和 Group 列）
#' @param Celltype 细胞类型列名（注意：函数内部似乎直接引用 data$`Celltype`，参数可能仅作为标记或未使用）
#' @param Group 分组列名
#' @param umap_plot 已生成的 UMAP ggplot 对象
#' @param color_list 颜色列表
#' @param title_name 图表标题
#' @param dir CSV 保存目录
#' @return 组合后的 plot 对象
#' @export
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

#' 单样本细胞比例绘制
#'
#' @description 
#' 绘制单个样本中各 Cluster 的比例。
#'
#' @param data Seurat 对象
#' @param title_name 图表标题
#' @param group_by 分组列名
#' @param ncol 图例列数
#' @return ggplot 对象
#' @export
SingleSampleProp <- function(data,title_name,group_by,ncol){
  p <- as.data.frame(table(data@meta.data[which(colnames(data@meta.data) == group_by)])) |> 
    mutate(group = title_name) |> mutate(prop = (Freq/(sum(Freq)))*100) |>
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

#' 合并 UMAP 和比例图
#'
#' @description 
#' 将 UMAP 图和比例图左右排列合并（使用 ggarrange），并保存为文件。
#'
#' @param umap UMAP ggplot 对象
#' @param rate 比例 ggplot 对象
#' @param figure_dir 图片保存目录
#' @export
merge_umap_prop <- function(umap,rate,figure_dir){
  merge_p <- ggarrange(umap,rate,labels=c("A","B"),common.legend = T,legend="right")
  ggsave(file.path(figure_dir,paste0("UMAP-prop-plot.pdf")),plot=merge_p,width = 14,height = 6,units = "cm",device = "pdf")
  ggsave(file.path(figure_dir,paste0("UMAP-prop-plot.png")),plot=merge_p,width = 14,height = 6,units = "cm",device = "png",dpi=1000)
}
# ==============================================================================
# END 
# ==============================================================================
