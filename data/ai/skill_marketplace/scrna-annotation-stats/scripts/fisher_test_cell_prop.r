# draw ggplot
data2plot <- function(data,save_dir,pair){
	p <- ggplot(data, aes(x = celltype, y = log2(oddsratio))) +
	geom_point(aes(y = log2(oddsratio),color = -log(padj_fisher)),size = 3)  +
	geom_vline(xintercept = 0) +
	labs(x = 'Celltype',
		y = 'log2(oddsratio)',
		title = paste0(pair[1],' vs ',pair[2])) +
	coord_flip() +
	theme_bw()
	ggsave(file.path(save_dir,paste0(pair[1],' vs ',pair[2]),'fisherTest.png'),
	       width = 6,height = 4,dpi =1000,plot = p)
	ggsave(file.path(save_dir,paste0(pair[1],' vs ',pair[2]),'fisherTest.pdf'),
	       width = 6,height = 4,dpi =1000,plot = p)
}
# output table html
gt2html <- function(data,save_dir,name){
	require(gt)
	gt_table <- data %>%
	gt() %>%
	tab_header(
		title = "Cell Type Enrichment Results",
		subtitle = "Odds Ratio and Fisher's P-value Adjustment"
	) %>%
	fmt_number(
		columns = c(oddsratio, pval_fisher, padj_fisher),
		decimals = 4
	) %>%
	cols_label(
		celltype = "Cell Type",
		oddsratio = "Odds Ratio",
		pval_fisher = "P-value (Fisher)",
		padj_fisher = "Adjusted P-value"
	) %>%
	data_color(
		columns = vars(oddsratio),
		colors = scales::col_numeric(palette = c("white", "red"), domain = NULL)
	)
	gt_table %>% gtsave(file.path(save_dir,paste0(name,'-Test.html'))) 
}
# calculation cell Rate fisherTest
CalculationRatefisherTest <- function(seurat = seurat_object,
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
  # freq_fisher Test function
  freq_fisher <- function(conditions, have_identity) {
    freq <- table(factor(have_identity, levels = c(TRUE, FALSE)), conditions)
    test <- fisher.test(freq)
    res <- setNames(c(test$estimate, test$p.value), c("oddsratio", "pval_fisher"))
    return(res)
  }
  # celltype_enrichment
  region_enrichment <- data.frame(
    celltype = levels(seurat@meta.data$`celltype`),
    t(sapply(levels(seurat@meta.data$`celltype`), function(ct) {
      freq_fisher(conditions = factor(seurat@meta.data$`group`, levels = pair),
                  have_identity = seurat@meta.data$`celltype` == ct)
    })),
    row.names = NULL
  )
  # Fisher test result
  region_enrichment$padj_fisher <- p.adjust(region_enrichment$pval_fisher)
  
  return(region_enrichment)
}		