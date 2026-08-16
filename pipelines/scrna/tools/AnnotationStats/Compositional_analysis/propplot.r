# Author : zhang jian
# date : 2024-12-26
# Proplot 2.0v
# description : Proplot 函数是对单细胞注释后的seurat object 细胞类型分组柱状图可视化函数 & 并统计不同组的细胞数量与比例
# @ data : seurat object
# @ Celltype : cell annotation col in meta.data
# @ group.by : seurat group by infor (dafult : orig.ident)
# @ dir : cell prop result save dir
# @ name : cell prop result save name
# @ angle : prop plot axis x text angle
# @ color_list : prop plot use color list (dafult : NULL)
#--------------# 
# Proplot
Proplot <- function(data = Seurat,
                    Celltype = 'celltype',
                    group.by = 'orig.ident',
                    dir = save_dir,
                    name = 'scRNA-seq Compositional ',
                    angle = 45,
                    color_list = NULL){
  # loading depend packages
  require(Seurat)
  require(tidyverse)
  require(ggplot2)
  # data clean & convert 
  temp <- data@meta.data |> dplyr::select(c(`Celltype`,`group.by`))
  colnames(temp)[1] <- 'Celltype'
  list <- levels(temp$Celltype)
  temp$Celltype <- as.character(temp$Celltype)
  colnames(temp)[2] <- 'Group'
  rate_data <- as.data.frame(table(temp$Celltype,temp$Group))
  rate_data$Var1 <- factor(rate_data$Var1,levels = list)
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
  # save cell frequently & rate
  write.csv(rate_data_1,file.path(dir,paste0(name,'-celltyoe.prop.csv')),
            row.names = F)
  if (is.null(color_list)) {
    colour1 <- c('#E5D2DD', '#53A85F', '#F1BB72', '#F3B1A0', '#D6E7A3', '#57C3F3', '#476D87',
                 '#E95C59', '#E59CC4', '#AB3282', '#23452F', '#BD956A', '#8C549C', '#585658',
                 '#9FA3A8', '#E0D4CA', '#5F3D69', '#C5DEBA', '#58A4C3', '#E4C755', '#F7F398',
                 '#AA9A59', '#E63863', '#E39A35', '#C1E6F3', '#6778AE', '#91D0BE', '#B53E2B',
                 '#712820', '#DCC1DD', '#CCE0F5',  '#CCC9E6', '#625D9E', '#68A180', '#3A6963',
                 '#968175')
  } else {
    colour1 <- color_list
  }
  p <- rate_data_1 |>
    ggplot(aes(x=group,y=rate,fill=Cell_cluster_name))+
    geom_bar(position = 'stack',stat="identity",width=0.5)+
    labs(x="",y = "Cell cluster frequently (%)",title = )+
    scale_fill_manual(values=colour1) +
    scale_y_continuous(expand = c(0,0),limits = c(0,100)) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = angle,vjust = 0.99,hjust=0.99))+
    guides(fill=guide_legend(ncol=1,title="Cell cluster Type",
                             keywidth = 1, keyheight = 1,
                             override.aes = list(size=0.02,alpha=1)))
  return(p)
}