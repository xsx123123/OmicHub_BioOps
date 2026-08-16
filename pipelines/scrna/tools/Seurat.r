##################################
rm(list = ls())
##################################
suppressMessages(library("yaml"))
suppressMessages(library("getopt"))
suppressMessages(library("stringr"))
suppressMessages(library("crayon"))
suppressMessages(library("praise"))
suppressMessages(library("dplyr"))
suppressMessages(library("scater"))
suppressMessages(library("Seurat"))
suppressMessages(library("HGNChelper"))
suppressMessages(library("scCustomize"))
suppressMessages(library("SingleR"))
suppressMessages(library("patchwork"))
suppressMessages(library("stringr"))
suppressMessages(library("crayon"))
suppressMessages(library("praise"))
suppressMessages(library("progress"))
suppressMessages(library("ggplot2"))
suppressMessages(library("homologene"))
suppressMessages(library("celldex"))
suppressMessages(library("ggpubr"))
suppressMessages(library("ggrepel"))
suppressMessages(library("parallel"))
suppressMessages(library("clustree"))
suppressMessages(library("gtools"))
suppressMessages(library("cowplot"))
suppressMessages(library("lubridate"))
suppressMessages(library("patchwork"))
suppressMessages(library("uwot"))
suppressMessages(library("viridis"))
suppressMessages(library("decontX"))
suppressMessages(library("tidyverse"))
suppressMessages(library("tools"))
suppressMessages(library("data.table"))
suppressMessages(library("sommer"))
suppressMessages(library("BiocParallel"))
options(future.globals.maxSize = 8000 * 1024^2)
##################################
source('/glusterfs/home/local_zhang_jian/zj_library/scRNA_seq_multisample_pipeline/multi_sample_function.r')
##################################
rds <- '/glusterfs/home/local_wang_haoyu/project_sc/2024-04-22-zhong-scGEX-VDJ-FB-Sample18-summary/Rwkdir/GEX_Seuratlist_Sample18_240523.rds'
save_dir <- '/titan3/local_zhang_jian/scRNA-seq/2024-04-22-zhong-scGEX-VDJ-FB-Sample18-summary'
Seurat <- readRDS(rds)
project_name <- 'zhong-scGEX-VDJ-FB-Sample18-summar'
##################################
merge <- scCustomize::Merge_Seurat_List(Seurat,add.cell.ids = names(Seurat),merge.data = TRUE,project = project_name)
# merge <- JoinLayers(merge)
PatchDeallist <- SplitObject(merge, split.by = "orig.ident")
# NormalFeature
sclist <- NormalFeature(PatchDeallist)
# merge seurat object
merge <- scCustomize::Merge_Seurat_List(sclist,add.cell.ids = NULL,merge.data = TRUE,project = project_name)
merge <- JoinLayers(merge)
saveRDS(merge,file.path(save_dir,"scrna_seq_merge.rds"))
# create new seurat object
all_project <- CreateNewSeurat(merge)
# remove batch by Seurat 5.0
# all_project <- DealPatch(all_project,DealPatch_dir,1.2,100)
DealPatch_dir <- save_dir
all_project <- DealPatchHarmony(all_project,save_dir,1.2,100)
# save data
saveRDS(all_project,file.path(output_dir,"scrna_seq_Harmony_interget.rds"))
# all_project <- readRDS(file.path(output_dir,"scrna_seq_interget.rds"))
# AmbientRNAContamination
Ambient <- AmbientRNAContamination(all_project$JoinLayers,save_dir)
# visablity RNAContamination
DrawAmbientRNAContamination(Ambient,save_dir,"umap.harmony")
saveRDS(Ambient,file.path(save_dir,"Ambient_interget.rds"))
# SingleR auto manual
# SingleData <- AutoSigleRAnn_cell(Ambient,9606,save_dir,"umap.harmony")
SingleData <- AutoSigleRAnn_Cluster(Ambient,9606,save_dir,"umap.harmony")
##########