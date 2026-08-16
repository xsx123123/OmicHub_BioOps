# author  : zhang jian
# date    : 2025-1-21
# version : 1.0v
#-----------------------------#
# description : 这是注释后scRNA-seq数据细胞比例统计 & 绘图function，
#               同时可以方便的添加特定细胞比例到柱状图中。
#-----------------------------#
Proplot <- function(data,
                    Celltype,
                    group.by,
                    dir,
                    name,
                    bar_width = 0.7,
                    add_prop_text = F,
                    top_celltype = 3,
                    text_color = '#F7F2E7',
                    text_size = 5,
                    color_list = NULL){
  # Proplot 2.0v
  require(ggplot2)
  require(tidyverse)
  # data <- cs91a108v001_data
  # Celltype <- 'Celltype'
  # group.by <- 'orig.ident'
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
    # i <- 'SC1'
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
  write.csv(rate_data_1,file.path(dir,paste0(name,'-celltyoe.prop.csv')))
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
  top3_data <- rate_data_1 %>%
    group_by(group) %>%
    arrange(desc(rate)) %>%
    slice_head(n = top_celltype)  
  p <- rate_data_1 |>
    ggplot(aes(x=group,y=rate,fill=Cell_cluster_name))+
    geom_bar(position = 'stack',stat="identity",width = bar_width)+
    labs(x="",y = "Cell cluster frequently (%)",title = )+
    scale_fill_manual(values=colour1) +
    # scale_y_continuous(expand = c(0,0),limits = c(0,100)) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45,vjust = 0.99,hjust=0.99))+
    guides(fill=guide_legend(ncol=1,title="Cell cluster Type",
                             keywidth = 1, keyheight = 1,
                             override.aes = list(size=0.02,alpha=1)))
  # add celltype prop text
  if (add_prop_text == T){
    p <- p + geom_text(data = top3_data, 
              aes(label = paste0(round(rate, 1), "%")), 
              position = position_stack(vjust = 0.5), 
              size = text_size, 
              color = text_color)
  }
  return(p)
}