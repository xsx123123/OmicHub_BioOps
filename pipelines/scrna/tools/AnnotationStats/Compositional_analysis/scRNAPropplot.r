# Author : zhang jian
# date : 2025-1-19
# version :1.0v
#----------------------#
# 模拟数据
set.seed(123)
data <- data.frame(
  Cluster = rep(c("B", "CD14 Mono", "CD16 Mono", "CD4 T", "CD8 T", "Mk", 
                  "Mono/B", "Mono/T", "NK", "NKT"), each = 8),
  Condition = rep(c("Sepsis only", "Sepsis+ARDS",
                    "Sepsis only-1", "Sepsis+ARDS-1",
                    "Sepsis only-2", "Sepsis+ARDS-2",
                    "Sepsis only-3", "Sepsis+ARDS-3"), times = 10),
  Frequency = runif(80, 0.2, 0.8)  # 生成 80 个随机频率值，范围为 0.2 到 0.8
)


prepare_prop_data <- function(table_obj) {
  # 1. 保持矩阵形状转为数据框
  df <- as.data.frame.matrix(table_obj) %>%
    rownames_to_column(var = "Cluster")
  
  # 2. 转为长格式并计算比例
  df_long <- df %>%
    pivot_longer(
      cols = -Cluster, 
      names_to = "Condition", 
      values_to = "Frequency"
    ) %>%
    # --- 核心步骤：按样本分组计算比例 ---
    group_by(Condition) %>% 
    mutate(Sample_Total = sum(Frequency)) %>% # 先算出该样本的总细胞数
    mutate(Proportion = Frequency / Sample_Total) %>% # 计算比例 (0-1)
    mutate(Percent = Proportion * 100) %>% # 转为百分比 (0-100)
    ungroup() %>%
    # ------------------------------------
    # 自动识别分组 (A/B)
    mutate(Group = gsub("[0-9]", "", Condition)) 
  
  return(df_long)
}

#----------------------#
scRNAPropplot <- function(data,
                          Frequency = "Frequency",
                          Cluster = 'Cluster',
                          CellType = 'CellType',
                          Condition = 'Condition'){
  require(ggplot2)
  require(patchwork)
  colors_list_1 <- c("#CC79A7","#0072B2","#56B4E9","#009E73","#F5C710","#E69F00",
                     "#D55E00","#ff3b30","#ff9500","#ffcc00","#4cd964","#5ac8fa",
                     "#007aff","#5856d6")
  colors_list_2 <- c("#ECA669","#E06681","#8087E2","#E2D269", "#E64B35FF","#4DBBD5FF",
                     "#00A087FF","#3C5488FF","#F39B7FFF","#8491B4FF","#91D1C2FF",
                     "#DC0000FF","#7E6148FF","#B09C85FF")
  # draw propplot
  p1 <- ggplot(data, aes(x = Condition, y = Frequency, fill = Cluster)) +
    geom_bar(stat = "identity", position = "fill") +  # 堆叠比例图
    scale_y_continuous(labels = scales::percent) +  # y轴显示为百分比
    labs(x = NULL,y = Frequency,fill = CellType) +
    scale_fill_manual(values = colors_list_1)+
    theme_minimal() + 
    theme(axis.text.x = element_text(angle = 45, hjust = 0.99,vjust= 0.99),
          panel.grid.major = element_blank(),
          panel.grid.minor = element_blank())
  # draw propplot
  p2 <- ggplot(data, aes(x = Condition, y = Frequency, fill = Cluster)) +
    geom_bar(stat = "identity", position = "fill") +  # 堆叠比例图
    scale_y_continuous(labels = scales::percent) +  # y轴显示为百分比
    labs(x = NULL,y = Frequency,fill = CellType) +
    scale_fill_manual(values = colors_list_2)+
    theme_minimal() + 
    theme(axis.text.x = element_text(angle = 45, hjust = 0.99,vjust= 0.99),
          panel.grid.major = element_blank(),
          panel.grid.minor = element_blank())
  all <- p1 + p2 + patchwork::plot_layout()
  return(all)
}
#----------------------#