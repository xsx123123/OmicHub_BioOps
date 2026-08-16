library(Seurat)
# loading gene matirx
count <- read.csv('/titan3/local_zhang_jian/scRNA-seq/alts/regional_cell_sampling_Log2TPM_fixed.txt',sep = '\t')
# Create Seurat object
intestinal <- CreateSeuratObject(count)
intestinal$celltype <- gsub('^.*_','',Cells(intestinal))
saveRDS(intestinal,file.path('/titan3/local_zhang_jian/scRNA-seq/alts/intestinal_alts.rds'))
save_dir <- '/titan3/local_zhang_jian/scRNA-seq/alts'
SingleSampleSubClusterRereduction(Seurat = intestinal,AutoSettingPcCutoff_plot_name = 'AutoSettingPcCutoff',
                                  normalization.method =  "LogNormalize",
                                  scale.factor = 1e4,
                                  election.method = "vst",
                                  nfeatures = 2000,
                                  resolution = 1.2,
                                  save_dir = save_dir)




