# Author : zhang jian
# Date : 2025-3-14
# Version : 1.0v
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
# CalculationPercentAverageExp
CalculationPercentAverageExp <- function(seurat_obj, gene = gene_list, group_by = 'celltype') {
  require(scCustomize)
  require(Seurat)
  require(tidyverse)
  
  # init log4r
  logger <- log4r_init()
  
  seurat_obj@meta.data[[group_by]] <- factor(seurat_obj@meta.data[[group_by]]) 
  
  # 计算 Percent_Expressing
  data <- scCustomize::Percent_Expressing(seurat_obj, gene, threshold = 0, group_by = group_by)
  
  info(logger,"Calculation Gene Percent Average Exp")
  
  # 处理 Percent_Expressing 结果格式
  data_Percent_Expressing <- data %>%
    rownames_to_column(var = "gene") %>%
    rename_with(~ gsub("^RNA\\.", "", .), starts_with("RNA")) %>%
    pivot_longer(cols = -gene, names_to = "variable", values_to = "pct_exp")
  
  # 计算 AverageExpression
  data <- AverageExpression(seurat_obj, features = gene, assays = 'RNA', return.seurat = FALSE, group.by = group_by)
  
  info(logger,"Calculation Gene Average Expression")
  
  data <- as.data.frame(data) %>%
    rownames_to_column(var = "gene")
  
  # 处理列名
  if (length(levels(factor(seurat_obj@meta.data[[group_by]]))) == 1) {
    colnames(data) <- c("gene", levels(factor(seurat_obj@meta.data[[group_by]]))[1])
  } else {
    data <- data
  }
  
  # 处理 AverageExpression 结果格式
  data_AverageExpression <- data %>%
    rename_with(~ gsub("^RNA\\.", "", .), starts_with("RNA")) %>%
    pivot_longer(cols = -gene, names_to = "variable", values_to = "avg_exp")
  
  # 合并数据
  merged_df <- data_Percent_Expressing %>%
    left_join(data_AverageExpression, by = c("gene", "variable"))
  
  return(merged_df)
}
