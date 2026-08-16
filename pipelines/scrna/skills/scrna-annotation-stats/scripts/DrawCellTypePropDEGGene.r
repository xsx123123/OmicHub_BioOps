# author : zhang jian
# date : 2025-1-13
# version : 1.0v
#--------------------#
# logging help function
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
# Findmarker & stats deg gene functions
stats_deg_gene <- function(main_annotation = main_annotation,
                           tread = "LC",
                           control = "N"){
  gene_stats <- data.frame(group = NULL,NUMBER = NULL)
  for ( i in levels(factor(main_annotation$Celltype))){
    # i <- "B cells"
    tread_cell_id <- subset(main_annotation@meta.data,orig.ident == tread & Celltype == i )
    control_cell_id <- subset(main_annotation@meta.data,orig.ident == control & Celltype == i )
    deg <- FindMarkers(main_annotation, ident.1 = rownames(tread_cell_id) , ident.2 = rownames(control_cell_id), logfc.threshold = 0.25)
    deg <- sum(deg$p_val_adj < 0.05 & deg$avg_log2FC > 0.25)
    temp <- data.frame(group = paste0(i,'-',tread,'vs',control),NUMBER = deg)
    gene_stats <- rbind(gene_stats,temp)
  }
  return(gene_stats)
}
#--------------------#
# stats annotation cluster celltype prop functions
stats_cell_prop <- function(main_annotation = main_annotation,
                                tread = "LC",
                                control = "N"){
  gene_stats <- data.frame(group = NULL,lfc = NULL,prop = NULL)
  for ( i in levels(factor(main_annotation$Celltype))){
    # i <- "B cells"
    tread_cell_id <- subset(main_annotation@meta.data,orig.ident == tread & Celltype == i )
    control_cell_id <- subset(main_annotation@meta.data,orig.ident == control & Celltype == i )
    lfc <- log2(dim(tread_cell_id)[1]/dim(control_cell_id)[1])
    PROP = (dim(tread_cell_id)[1] + dim(control_cell_id)[1]) / dim(main_annotation@meta.data)[1] *100
    temp <- data.frame(group = paste0(i,'-',tread,'vs',control),lfc = lfc,prop =PROP)
    gene_stats <- rbind(gene_stats,temp)
  }
  return(gene_stats)
}
#--------------------#
# mian & draw plot functions
DrawCellTypePropDEGGene <- function(Seurat,
                                    group_list,
                                    celltype = 'Celltype',
                                    color_low = "#fff6b7",
                                    color_heigh = "#f6416c",
                                    save_dir = './',
                                    project_id = 'satas cell & deg infor'){
  
  require(ggplot2)
  require(tidyverse)
  require(Seurat)
  # loading log modules
  logger <- log4r_init()
  # convert Celltype
  Seurat$Celltype <- Seurat[[`celltype`]]
  # batch analysis group
  merge_data <- data.frame()
  for (i in names(group_list)){
    group_id_1 <-  group_list[[i]]$tread
    group_id_2 <-  group_list[[i]]$control
    # get group id
    group_name <- paste0(group_id_1,' vs ',group_id_2)
    info(logger,paste0('DEG & Stats cell prop for : ', group_name,' do'))
    # calculation deg gene
    deg_temp<- stats_deg_gene(main_annotation = Seurat,
                              tread = group_id_1,
                              control =group_id_2)
    # stats cell prop
    lfc_temp <- stats_cell_prop(main_annotation = Seurat,
                                tread = group_id_1,
                                control =group_id_2)
    info(logger,paste0('DEG & Stats cell prop for : ', group_name,' done'))
    # data pre-process
    data <- deg_temp |> left_join(lfc_temp, by = 'group') |> mutate(cell_type = gsub('-.*', '', group), comparison = group_name )
    merge_data <- bind_rows(merge_data,data)
  }
  # save result
  info(logger,paste0('Save Analyis at :',file.path(save_dir,paste0(project_id,'-DrawCellTypePropDEGGene.csv'))))
  write.csv(merge_data,file.path(save_dir,paste0(project_id,'-DrawCellTypePropDEGGene.csv')))
  # draw plot
  info(logger,'Draw plot')
  p <- ggplot(merge_data, aes(x = lfc, y = cell_type)) +
    geom_point(aes(size = prop, color = NUMBER)) +
    scale_color_gradient(low = color_low, high = color_heigh) +
    scale_size(range = c(1, 10)) +
    scale_x_continuous(limits = c(-3, 3)) +
    geom_vline(xintercept = 0, alpha = 0.5) +
    theme_minimal() +
    labs(x = "log2(Tread/Control)", y = "Cell Type",
         size = "% of Total Cells", color = "No. Up DEG") +
    facet_wrap(~comparison, ncol = 3) +
    theme(legend.position = "bottom")+
    guides(color = guide_colorbar(label.theme = element_text(angle = 90)))
  return(p)
}
#--------------------#