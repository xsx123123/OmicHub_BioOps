# ==============================================================================
# 09.06.vis_data_export.r
# 功能：负责表达量数据的计算与导出
# 包括：按 celltype/cluster/自定义分组计算平均表达量，以及 DEG 结果的合并注释
# ==============================================================================

#' 计算各细胞类型的平均基因表达量
#'
#' @description 
#' 计算 Seurat 对象中各 Celltype 的平均表达量，并将结果保存为 CSV 文件。
#'
#' @param data Seurat 对象
#' @return 平均表达量数据框
#' @export
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

#' 计算各 Cluster 的平均基因表达量
#'
#' @description 
#' 计算 Seurat 对象中各 seurat_clusters 的平均表达量，并将结果保存为 CSV 文件。
#'
#' @param data Seurat 对象
#' @return 平均表达量数据框
#' @export
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

#' 按自定义分组计算平均基因表达量
#'
#' @description 
#' 根据用户指定的 metadata 列（DIY 参数）计算平均表达量，并将结果保存为 CSV 文件。
#'
#' @param data Seurat 对象
#' @param DIY 分组列名（必须是 metadata 中的因子列）
#' @return 平均表达量数据框
#' @export
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

#' 合并 DEG 结果与平均表达量
#'
#' @description 
#' 将差异分析结果（DEG）与计算好的平均表达量表进行合并。
#'
#' @param diy_gene_expression 平均表达量数据框
#' @param deg 差异基因分析结果
#' @return 合并后的数据框
#' @export
gene_expression_deg_merge <- function(diy_gene_expression,deg){
  colnames(diy_gene_expression) <- paste0("Average-gene-expression-",colnames(diy_gene_expression))
  
  diy_gene_expression$gene <- rownames(diy_gene_expression)
  merge_data <- left_join(deg,diy_gene_expression,by="gene")
  # return deg data
  return(merge_data)
}

#' 注释 DEG 结果（添加 Gene Symbol/Name）
#'
#' @description 
#' 使用提供的数据库（db）为 DEG 结果添加 SYMBOL 和 GENENAME 注释。
#'
#' @param deg 差异基因分析结果（需包含 gene 列）
#' @param db 注释数据库（需支持 select 操作）
#' @return 注释后的数据框
#' @export
annotation_deg_result <- function(deg,db){
  annotation_data <- select(db, keys=deg$gene, columns=c("SYMBOL", "GENENAME"), keytype="SYMBOL")
  # change colname
  colnames(annotation_data) <- c("gene","GENE NAME")
  merge_data <- left_join(deg,annotation_data,by="gene")
  return(merge_data)
}
# ==============================================================================
# END 
# ==============================================================================
