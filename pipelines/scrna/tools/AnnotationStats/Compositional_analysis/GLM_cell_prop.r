# draw ggplot
data2plot <- function(data,save_dir,pair){
	p <- ggplot(data, aes(x = celltype, y = coef_glm)) +
	geom_point(aes(y = coef_glm,color = -log(padj_aov)),size = 3)  +
	geom_hline(yintercept = 0) +
	labs(x = 'Celltype',
		y = 'coef_glm',
		title = paste0(pair[1],' vs ',pair[2])) +
	coord_flip() +
	theme_bw()
	ggsave(file.path(save_dir,paste0(pair[1],' vs ',pair[2],'GLMTest.png')),
	       width = 6,height = 4,dpi =1000,plot = p)
	ggsave(file.path(save_dir,paste0(pair[1],' vs ',pair[2],'GLMTest.pdf')),
	       width = 6,height = 4,dpi =1000,plot = p)
}
# freq_glm_aov Test function
CalculationRateglmTest <- function(seurat = seurat_object,
                                celltype = 'celltype',
                                group = 'group',
                                pair = c('Control','Treate')) {  # Added pair as an argument
  # Description : this is celltype prop status fisher test function
  # @seurat   : analysis seurat object 
  # @celltype : cell annotation result in meta.data
  # @group    : group infor in meta.data
  # @pair     : group pair infor
  require(Seurat)
  require(tidyverse) 
  freq_glm_aov <- function(samples, conditions, have_identity){
	sample_conditions <- unique(data.frame(sample = samples, condition = conditions))
	sample_conditions <- setNames(sample_conditions$condition, sample_conditions$sample)

	freq <- table(samples, factor(have_identity, levels=c(TRUE,FALSE)))
	m <- glm(freq ~ sample_conditions[rownames(freq)], family = "binomial")
	aov <- anova(m, test = "Chisq")
	res <- setNames(c(coef(m)[2], aov$Pr[2]), c("coef_glm","pval_aov"))
	return(res)
  }
	# Seurat freq_glm_aov analysis
	region_enrichment <- data.frame(celltype = levels(seurat@meta.data$`celltype`),
	                                t(sapply(levels(seurat@meta.data$`celltype`), function(celltype){
    								freq_glm_aov(samples = seurat$orig.ident,
                 					conditions = factor(seurat@meta.data$`group`, levels = rev(pair)),
                 					seurat@meta.data$`celltype` == celltype)})),
									row.names=NULL)
	# Seurat freq_glm_aov result
	region_enrichment$padj_aov <- p.adjust(region_enrichment$pval_aov)
	return(region_enrichment)
}
################################
# how to use
# data clean
# rds_dir <- '/titan3/local_zhang_jian/scRNA-seq/UNIVERscRNAseq/10xRNA/s1912x10t001_2024.11.7/Seurat/s1912x10t001_interger_all-scRNA-seq-result/output/s1912x10t001_main_annotation_v2.2.rds'
# main_annotation <- read_rds(rds_dir)
# prop_test <- subset(main_annotation,orig.ident %in% c("EB24001","EB24002","EB24003","EB24004","EB24006","EB24008"))
# prop_test@meta.data <- prop_test@meta.data %>%
#   dplyr::mutate(group = dplyr::case_when(
#     orig.ident %in% c("EB24001", "EB24002", "EB24003") ~ "Control",
#     orig.ident %in% c("EB24004", "EB24006", "EB24008") ~ "Treate",
#    TRUE ~ orig.ident  # 对于其他情况保持原值
#  ))
# table(prop_test$group)
# seurat <- prop_test
# CalculationRatefisherTest
# data <- CalculationRateglmTest(seurat = prop_test,
#                                celltype = 'celltype_main',
#                                group = 'group',
#      				    	     pair = c('Control','Treate'))
# save_dir <- '/titan3/local_zhang_jian/scRNA-seq/scRNA-seq_analysis'
# name <- 'glm-test'
# data2plot(data,save_dir,pair)