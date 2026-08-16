# ==============================================================================
# Seurat Integration Functions (v5 IntegrateLayers)
# Author: zhang jian
# Description: Handles multi-sample integration using Seurat v5 'IntegrateLayers'.
#              Supports CCA, RPCA, Harmony, and FastMNN.
#              Refactored for modularity, SCT support, and robustness.
# ==============================================================================

# ==============================================================================
# Function: MergeSeuratObjectBatchCheck
# Description: Performs a quick merging, normalization, and clustering of Seurat
#              objects to assess batch effects before formal integration.
#              It generates Elbow plots to help determine the optimal number of
#              PCs and produces initial UMAP/tSNE plots.
# @ data : A merged Seurat object (or list of objects).
# @ savedir : Output directory for plots and metadata.
# @ resolution : Clustering resolution (default: 0.8).
# @ scale_factor : Scale factor for LogNormalization (default: 10000).
# @ normalization_method : Normalization method (default: 'LogNormalize').
# @ selection_method : Feature selection method (default: 'vst').
# @ nfeatures : Number of highly variable features to select (default: 2000).
# ==============================================================================
MergeSeuratObjectBatchCheck <- function(data, savedir,
                                        resolution = 0.8,
                                        scale_factor = 10000,
                                        normalization_method = 'LogNormalize',
                                        selection_method = 'vst',
                                        nfeatures = 2000){
  # data <- sclist
  # savedir <- seurat_dir

  # Log the start of the batch check process
  info(logger, '  Merge function use DrawElbowPlot auto setting PCs')

  # Normalize data
  # DEBUG: Logging normalization parameters to ensure correct settings are used
  info(logger, paste0("  Normalizing data with :", normalization_method, ' scale.factor :', scale_factor))
  data <- NormalizeData(data, normalization.method = normalization_method, scale_factor = scale_factor)

  # Find Variable Features
  # DEBUG: Logging feature selection parameters

  info(logger, paste0("  FindVariable Features selection.method:", selection_method, ' nfeatures :', nfeatures))
  data <- FindVariableFeatures(data, selection.method = selection_method, nfeatures = nfeatures)

  # Scale and PCA
  # COMMENTS: Scaling is essential before PCA to ensure high-variance genes don't dominate.
  info(logger, "  Scaling data and running PCA...")
  data <- ScaleData(data)
  data <- RunPCA(data)

  # Determine optimal PCs using ElbowPlot
  # COMMENTS: We calculate the elbow plot to visually inspect the variance explained by PCs.
  info(logger, "  Generating ElbowPlot for PCA...")
  PCA <- ElbowPlot(data, ndims=50, reduction="pca")

  # Auto-detect PC cutoff (assuming DrawElbowPlot returns the number of PCs)
  pc <- DrawElbowPlot(data, "ElbowPlot-auto", savedir)

  # Save Elbow Plot
  info(logger, paste0("  Saving ElbowPlot to ", savedir))
  ggsave(file.path(savedir, "scRNA_ElbowPlot_PCA.pdf"), plot = PCA, width = 10, height = 8)
  ggsave(file.path(savedir, "scRNA_ElbowPlot_PCA.png"), plot = PCA, width = 10, height = 8, dpi=1000)

  # Cluster
  # DEBUG: Logging the number of PCs used for neighbor finding
  info(logger, paste0("  Running PCA (FindNeighbors) with :", pc, ' PCs'))
  data <- FindNeighbors(data, dims = 1:pc)

  # DEBUG: Logging resolution for clustering
  info(logger, paste0("  Running FindClusters with :", resolution, ' resolution'))
  data <- FindClusters(data, resolution = resolution)

  # Dimensionality Reduction: UMAP
  info(logger, paste0("  Running UMAP with :", resolution, ' resolution'))
  data <- RunUMAP(data, dims = 1:pc, umap.method = 'uwot')

  # Dimensionality Reduction: tSNE
  info(logger, paste0("  Running TSNE with :", resolution, ' resolution'))
  data <- RunTSNE(data, dims = 1:pc, check_duplicates = FALSE)

  # Visability UMAP
  # COMMENTS: Generate UMAP plots colored by sample ID (orig.ident) and cluster ID to check for batch effects.
  info(logger, "  Generating and saving UMAP plots...")
  p1 <- DimPlot(data, reduction = "umap", group.by = "orig.ident")
  p2 <- DimPlot(data, reduction = "umap", label = TRUE, repel = TRUE)
  plot_raw <- p1 + p2
  ggsave(file.path(savedir, "scRNA_merged_umap_clusters.pdf"), plot = plot_raw, width = 12, height = 5)
  ggsave(file.path(savedir, "scRNA_merged_umap_clusters.png"), plot = plot_raw, width = 12, height = 5, dpi=1000)

  # Visability tSNE
  # COMMENTS: Generate tSNE plots as an alternative visualization.
  info(logger, "  Generating and saving tSNE plots...")
  p1 <- DimPlot(data, reduction = "tsne", group.by = "orig.ident")
  p2 <- DimPlot(data, reduction = "tsne", label = TRUE, repel = TRUE)
  plot_raw <- p1 | p2
  ggsave(file.path(savedir, "scRNA_merged_tsne_clusters.pdf"), plot = plot_raw, width = 12, height = 5)
  ggsave(file.path(savedir, "scRNA_merged_tsne_clusters.png"), plot = plot_raw, width = 12, height = 5, dpi=1000)

  return(data)
}

# Seurat integer function!
# COMMENTS: Helper function to iterate through resolutions for CCA clusters.
# Purpose: Applies FindClusters function at multiple resolutions to evaluate cluster stability.
# Input: SeuratObj - Seurat object to cluster, dafult_res - default resolution to use,
#        res_list - vector of resolution values to test
# Output: Seurat object with clusters computed at all tested resolutions
FinClusterResCCA <- function(SeuratObj = SeuratObj, dafult_res = 1.2,
                             res_list = c(0.2,0.4,0.6,0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.2)){
  suppressMessages(require(crayon))
  suppressMessages(require(tidyverse))
  # Check_log_models()
  res_list <- res_list
  # Loop through all resolutions except the default one
  for (i in res_list[-which(res_list == dafult_res)]){
    info(logger, paste0('  FindClusters CCA Interget Cluster res : ', i))
    SeuratObj <- FindClusters(SeuratObj,
                              resolution = i,
                              cluster.name = paste0('cca_clusters_res_', i))
  }
  # Apply default resolution clustering
  info(logger, paste0(crayon::bold(crayon::yellow('  FindClusters CCA Interget Cluster dafult res : ', dafult_res))))
  SeuratObj <- FindClusters(SeuratObj,
                            resolution = dafult_res,
                            cluster.name = paste0('cca_clusters_res_', dafult_res))
  # Set the default clustering column
  SeuratObj$cca_clusters <- SeuratObj[[paste0('cca_clusters_res_', dafult_res)]]
  return(SeuratObj)
}

# COMMENTS: Helper function to iterate through resolutions for Harmony clusters.
# Purpose: Applies FindClusters function at multiple resolutions to evaluate cluster stability for Harmony integration.
# Input: SeuratObj - Seurat object to cluster, dafult_res - default resolution to use,
#        res_list - vector of resolution values to test
# Output: Seurat object with clusters computed at all tested resolutions
FinClusterResharmony <- function(SeuratObj = SeuratObj, dafult_res = 1.2,
                             res_list = c(0.2,0.4,0.6,0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.2)){
  suppressMessages(require(crayon))
  suppressMessages(require(tidyverse))
  # Check_log_models()
  res_list <- res_list
  # Loop through all resolutions except the default one
  for (i in res_list[-which(res_list == dafult_res)]){
    info(logger, paste0('  FindClusters harmony Interget Cluster res : ', i))
    SeuratObj <- FindClusters(SeuratObj,
                              resolution = i,
                              cluster.name = paste0('harmony_clusters_res_', i))
  }
  # Apply default resolution clustering
  info(logger, paste0(crayon::bold(crayon::yellow('  FindClusters harmony Interget Cluster dafult res : ', dafult_res))))
  SeuratObj <- FindClusters(SeuratObj,
                            resolution = dafult_res,
                            cluster.name = paste0('harmony_clusters_res_', dafult_res))
  # Set the default clustering column
  SeuratObj$harmony_clusters <- SeuratObj[[paste0('harmony_clusters_res_', dafult_res)]]
  return(SeuratObj)
}

# COMMENTS: Helper function to iterate through resolutions for RPCA clusters.
# Purpose: Applies FindClusters function at multiple resolutions to evaluate cluster stability for RPCA integration.
# Input: SeuratObj - Seurat object to cluster, dafult_res - default resolution to use,
#        res_list - vector of resolution values to test
# Output: Seurat object with clusters computed at all tested resolutions
FinClusterResrpca <- function(SeuratObj = SeuratObj, dafult_res = 1.2,
                              res_list = c(0.2,0.4,0.6,0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.2)){
  suppressMessages(require(crayon))
  suppressMessages(require(tidyverse))
  # Check_log_models()
  res_list <- res_list
  # Loop through all resolutions except the default one
  for (i in res_list[-which(res_list == dafult_res)]){
    info(logger, paste0('  FindClusters rpca Interget Cluster res : ', i))
    SeuratObj <- FindClusters(SeuratObj,
                              resolution = i,
                              cluster.name = paste0('rpca_clusters_res_', i))
  }
  # Apply default resolution clustering
  info(logger, paste0(crayon::bold(crayon::yellow('  FindClusters rpca Interget Cluster dafult res : ', dafult_res))))
  SeuratObj <- FindClusters(SeuratObj,
                            resolution = dafult_res,
                            cluster.name = paste0('rpca_clusters_res_', dafult_res))
  # Set the default clustering column
  SeuratObj$rpca_clusters <- SeuratObj[[paste0('rpca_clusters_res_', dafult_res)]]
  return(SeuratObj)
}

# COMMENTS: Helper function to iterate through resolutions for SCVI clusters.
# Purpose: Applies FindClusters function at multiple resolutions to evaluate cluster stability for SCVI integration.
# Input: SeuratObj - Seurat object to cluster, dafult_res - default resolution to use,
#        res_list - vector of resolution values to test
# Output: Seurat object with clusters computed at all tested resolutions
FinClusterResscvi <- function(SeuratObj = SeuratObj, dafult_res = 1.2,
                              res_list = c(0.2,0.4,0.6,0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.2)){
  suppressMessages(require(crayon))
  suppressMessages(require(tidyverse))
  # Check_log_models()
  res_list <- res_list
  # Loop through all resolutions except the default one
  for (i in res_list[-which(res_list == dafult_res)]){
    info(logger, paste0('  FindClusters scvi Interget Cluster res : ', i))
    SeuratObj <- FindClusters(SeuratObj,
                              resolution = i,
                              cluster.name = paste0('scvi_clusters_res_', i))
  }
  # Apply default resolution clustering
  info(logger, paste0(crayon::bold(crayon::yellow('  FindClusters scvi Interget Cluster dafult res : ', dafult_res))))
  SeuratObj <- FindClusters(SeuratObj,
                            resolution = dafult_res,
                            cluster.name = paste0('scvi_clusters_res_', dafult_res))
  # Set the default clustering column
  SeuratObj$rpca_clusters <- SeuratObj[[paste0('scvi_clusters_res_', dafult_res)]]
  return(SeuratObj)
}

# COMMENTS: Helper function to iterate through resolutions for MNN clusters.
# Purpose: Applies FindClusters function at multiple resolutions to evaluate cluster stability for MNN integration.
# Input: SeuratObj - Seurat object to cluster, dafult_res - default resolution to use,
#        res_list - vector of resolution values to test
# Output: Seurat object with clusters computed at all tested resolutions
FinClusterResmnn <- function(SeuratObj = SeuratObj, dafult_res = 1.2,
                             res_list = c(0.2,0.4,0.6,0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.2)){
  suppressMessages(require(crayon))
  suppressMessages(require(tidyverse))
  # Check_log_models()
  res_list <- res_list
  # Loop through all resolutions except the default one
  for (i in res_list[-which(res_list == dafult_res)]){
    info(logger, paste0('  FindClusters mnn Interget Cluster res : ', i))
    SeuratObj <- FindClusters(SeuratObj,
                              resolution = i,
                              cluster.name = paste0('mnn_clusters_res_', i))
  }
  # Apply default resolution clustering
  info(logger, paste0(crayon::bold(crayon::yellow('  FindClusters mnn Interget Cluster dafult res : ', dafult_res))))
  SeuratObj <- FindClusters(SeuratObj,
                            resolution = dafult_res,
                            cluster.name = paste0('mnn_clusters_res_', dafult_res))
  # Set the default clustering column
  SeuratObj$mnn_clusters <- SeuratObj[[paste0('mnn_clusters_res_', dafult_res)]]
  return(SeuratObj)
}

# ==============================================================================
# Function: DealPatch
# Description: Performs multi-method integration (CCA, RPCA, Harmony, FastMNN) on Seurat objects.
#              Includes pre-processing, integration, clustering, visualization and saving results.
# @ data : A merged Seurat object to integrate.
# @ savedir : Output directory for plots and integrated objects.
# @ Resolute : Clustering resolution (default: 0.8).
# @ k.weight : Weight parameter for integration methods (default: 100).
# @ reduceType : Whether to generate tSNE plots in addition to UMAP (default: FALSE).
# ==============================================================================
DealPatch <- function(data, savedir, Resolute, k.weight, reduceType = 'FALSE'){

  tempdata <- data
  # check package
  packagelist <- as.data.frame(installed.packages())
  needlist <- c("SeuratWrappers","harmony","batchelor","ggraph")

  # COMMENTS: Check if required packages are installed.
  packagelist <- as.data.frame(installed.packages(), stringsAsFactors = F)
  debug(logger, "  Checking required packages for integration methods...")
  miss_pkgs <- needlist[!needlist %in% packagelist$Package]
  if (length(miss_pkgs) == 0) {
    # 所有包都已安装的正常分支
    info(logger, "  All required integration packages (SeuratWrappers, harmony) are already installed.")
  } else {
    # 有缺失包的分支，精准打印缺失的包名
    miss_str <- paste(miss_pkgs, collapse = "、")
    warn(logger, paste0("  Missing required packages: ", miss_str))
    
    # 可选：额外给用户输出对应的安装命令，更友好
    info(logger, "  You can install missing packages with the following commands: ")
    if ("SeuratWrappers" %in% miss_pkgs) {
      info(logger, "  remotes::install_github('satijalab/seurat-wrappers')")
    }
    if ("harmony" %in% miss_pkgs) {
      info(logger, "  install.packages('harmony') # 若CRAN安装失败，可运行 remotes::install_github('immunogenomics/harmony')")
    }
    
    # 终止运行时也带上缺失包信息，错误提示更清晰
    stop(paste0("Missing required packages: ", miss_str, ", please install them first to continue."), call. = F)
  }

  # loading package
  info(logger, "  Loading required libraries...")
  suppressMessages(library(SeuratWrappers))
  suppressMessages(library(harmony))
  suppressMessages(library(batchelor))
  # k.weight=30
  # Resolute <- 0.8
  if (missing(k.weight)) {
    if (min(table(tempdata$orig.ident)) < 100){
      warn(logger, paste0("  You should seting k.weight < ", min(table(tempdata$orig.ident))))
      # print_color_note_warring(paste0(" you should seting k.weight < ",min(table(tempdata$orig.ident))))
      stop()
    }
  } else {
  }
  #----------------------------------
  # split merge data
  # COMMENTS: Split data by 'orig.ident' for integration steps.
  info(logger, "  Splitting data by orig.ident for integration...")
  obj <- tempdata
  obj[["RNA"]] <- split(obj[["RNA"]], f = obj$orig.ident)

  # COMMENTS: Pre-integration processing (Normalize -> FindVariables -> Scale -> PCA)
  info(logger, "  Performing standard pre-integration processing...")
  obj <- NormalizeData(obj)
  obj <- FindVariableFeatures(obj)
  obj <- ScaleData(obj)
  obj <- RunPCA(obj)

  # auto setting pc cutoff
  info(logger, "  Automatically determining PC cutoff (Non-Integrated)...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-not-Integrate", savedir)

  obj <- FindNeighbors(obj, dims = 1:pc, reduction = "pca")
  obj <- FindClusters(obj, resolution = Resolute, cluster.name = "unintegrated_clusters")
  obj <- RunUMAP(obj, reduction = "pca", dims = 1:pc, reduction.name = "umap.unintegrated")

  if(reduceType == 'TRUE'){
    info(logger, "  Running tSNE (Unintegrated)...")
    obj <- RunTSNE(obj, reduction = "pca", dims = 1:pc, reduction.name = "tsne.unintegrated", check_duplicates = FALSE)
    p <- DimPlot(obj, reduction = "tsne.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
    ggsave(file.path(savedir, "tsne.unintegrated.pdf"), width = 8, height = 7, plot = p)
    ggsave(file.path(savedir, "tsne.unintegrated.png"), width = 8, height = 7, plot = p, dpi=1000)
  }

  # save integrated plot
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
  ggsave(file.path(savedir, "umap.unintegrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "umap.unintegrated.png"), width = 8, height = 7, plot = p, dpi=1000)
  #----------------------------------
  # print run condition
  info(logger, "  CCA Integration DO")
  # print_color_note_UP("CCA Integration DO!!")

  # run CCA integrated method
  # COMMENTS: Performing CCA Integration
  info(logger, "  Executing CCA Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = CCAIntegration,
                    orig.reduction = "pca", new.reduction = "integrated.cca",
                    verbose = FALSE, k.weight=k.weight)
  }, level = "DEBUG")

  # auto setting pc cutoff
  debug(logger, "  Determining PC cutoff for CCA Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-cca-Integrate", savedir)

  # cluster & reduce dim
  debug(logger, "  Clustering and UMAP for CCA Integrated data...")
  obj <- FindNeighbors(obj, reduction = "integrated.cca", dims = 1:pc)
  obj <- FinClusterResCCA(SeuratObj = obj, dafult_res = 1.2)
  p <- DrawClusterTree(obj, integetmethods = 'CCA')
  ggsave(file.path(savedir, "cca.integrated.res.Tree.pdf"), width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "cca.integrated.res.Tree.png"), width = 10, height = 10, plot = p, dpi=1000)

  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "cca_clusters")
  obj <- RunUMAP(obj, reduction = "integrated.cca", dims = 1:pc, reduction.name = "umap.cca")
  if(reduceType == 'TRUE'){
    obj <- RunTSNE(obj, reduction = "integrated.cca", dims = 1:pc, reduction.name = "tsne.cca", check_duplicates = FALSE)
  }

  # save integrated plot
  p <- DimPlot(obj, reduction = "umap.cca", group.by ="orig.ident")  + labs(title = "CCA.Integration")
  ggsave(file.path(savedir, "cca.integrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "cca.integrated.png"), width = 8, height = 7, plot = p, dpi=1000)

  # print run condition
  info(logger, "  CCA Integration DONE")
  #----------------------------------
  # print run condition
  info(logger, "  RPCA Integration DO")
  # print_color_note_UP("RPCA Integration DO!!")

  # run rpca integrated method
  # COMMENTS: Performing RPCA Integration
  info(logger, "  Executing RPCA Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = RPCAIntegration,
                    orig.reduction = "pca", new.reduction = "integrated.rpca",
                    verbose = FALSE)
  }, level = "DEBUG")

  # auto setting pc cutoff
  info(logger, "  Determining PC cutoff for RPCA Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-RPCA-Integrate", savedir)

  # cluster & reduce dim
  info(logger, "  Clustering and UMAP for RPCA Integrated data...")
  obj <- FindNeighbors(obj, reduction = "integrated.rpca", dims = 1:pc)
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "rpca_clusters")
  obj <- FinClusterResrpca(SeuratObj = obj, dafult_res = 1.2)
  p <- DrawClusterTree(obj, integetmethods = 'RPCA')
  ggsave(file.path(savedir, "rpca.integrated.res.Tree.pdf"), width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "rpca.integrated.res.Tree.png"), width = 10, height = 10, plot = p, dpi=1000)

  obj <- RunUMAP(obj, reduction = "integrated.rpca", dims = 1:pc, reduction.name = "umap.rpca")
  if(reduceType == 'TRUE'){
    obj <- RunTSNE(obj, reduction = "integrated.rpca", dims = 1:pc, reduction.name = "tsne.rpca", check_duplicates = FALSE)
  }

  # save integrated plot
  p <- DimPlot(obj, reduction = "umap.rpca", group.by ="orig.ident")  + labs(title = "RPCA.Integration")
  ggsave(file.path(savedir, "rpca.integrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "rpca.integrated.png"), width = 8, height = 7, plot = p, dpi=1000)

  #print run condition
  info(logger, "  RPCA Integration DONE")
  #----------------------------------
  # print run condition
  info(logger, "  Harmony Integration DO")

  # run Harmony integrated method
  # COMMENTS: Performing Harmony Integration
  info(logger, "  Executing Harmony Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = HarmonyIntegration,
                    orig.reduction = "pca", new.reduction = "harmony",
                    verbose = FALSE)
  }, level = "DEBUG")

  # auto setting pc cutoff
  info(logger, "  Determining PC cutoff for Harmony Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-Harmony-Integrate", savedir)

  # cluster & reduce dim
  info(logger, "  Clustering and UMAP for Harmony Integrated data...")
  obj <- FindNeighbors(obj, reduction = "harmony", dims = 1:pc)
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "harmony_clusters")
  obj <- FinClusterResharmony(SeuratObj = obj, dafult_res = 1.2)
  p <- DrawClusterTree(obj, integetmethods = 'Harmony')
  ggsave(file.path(savedir, "harmony.integrated.res.Tree.pdf"), width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "harmony.integrated.res.Tree.png"), width = 10, height = 10, plot = p, dpi=1000)

  obj <- RunUMAP(obj, reduction = "harmony", dims = 1:pc,
                 reduction.name = "umap.harmony")
  if(reduceType == 'TRUE'){
  obj <- RunTSNE(obj, reduction = "harmony", dims = 1:pc,
                  reduction.name = "tsne.harmony", check_duplicates = FALSE)
  }

  # save integrated plot
  p <- DimPlot(obj, reduction = "umap.harmony", group.by ="orig.ident")  + labs(title = "Harmony.Integration")
  ggsave(file.path(savedir, "harmony.integrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "harmony.integrated.png"), width = 8, height = 7, plot = p, dpi=1000)

  # print run condition
  info(logger, "  Harmony Integration DONE")
  #----------------------------------
  # print run condition
  info(logger, "  FastMNN Integration DO")
  # run MNN integrated method
  # COMMENTS: Performing FastMNN Integration
  info(logger, "  Executing FastMNN Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = FastMNNIntegration,
                    new.reduction = "integrated.mnn",
                    verbose = FALSE)
  }, level = "DEBUG")

  # auto setting pc cutoff
  info(logger, "  Determining PC cutoff for FastMNN Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-mnn-Integrate", savedir)

  # cluster & reduce dim
  info(logger, "  Clustering and UMAP for FastMNN Integrated data...")
  obj <- FindNeighbors(obj, reduction = "integrated.mnn", dims = 1:pc)
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "mnn_clusters")
  obj <- FinClusterResmnn(SeuratObj = obj, dafult_res = 1.2)
  p <- DrawClusterTree(obj, integetmethods = 'MNN')
  ggsave(file.path(savedir, "mnn.integrated.res.Tree.pdf"), width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "mnn.integrated.res.Tree.png"), width = 10, height = 10, plot = p, dpi=1000)

  obj <- RunUMAP(obj, reduction = "integrated.mnn", dims = 1:pc,
                 reduction.name = "umap.mnn")
  if(reduceType == 'TRUE'){
    obj <- RunTSNE(obj, reduction = "harmony", dims = 1:pc,
                 reduction.name = "tsne.mnn", check_duplicates = FALSE)
  }

  # save integrated plot
  p <- DimPlot(obj, reduction = "umap.mnn", group.by ="orig.ident")  + labs(title = "mnn.Integration")
  ggsave(file.path(savedir, "mnn.integrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "mnn.integrated.png"), width = 8, height = 7, plot = p, dpi=1000)

  # print run condition
  info(logger, "  FastMNN Integration DONE")
  #----------------------------------
  # visablity
  info(logger, "  Generating comparison plots for all integration methods...")
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="unintegrated_clusters", label = T) +
    NoLegend() + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.cca", group.by ="cca_clusters", label = T) +
    NoLegend() + labs(title = "CCAIntegration")
  p2 <- DimPlot(obj, reduction = "umap.rpca", group.by ="rpca_clusters", label = T) +
    NoLegend()+ labs(title = "RPCAIntegration")
  p3 <- DimPlot(obj, reduction = "umap.harmony", group.by ="harmony_clusters", label = T)+
    NoLegend() + labs(title = "HarmonyIntegration")
  p4 <- DimPlot(obj, reduction = "umap.mnn", group.by ="mnn_clusters", label = T)+
    NoLegend() + labs(title = "FastMNNIntegration")

  # merge plot
  all <- p + p1 + p2 + p3 + p4 + patchwork::plot_layout(ncol = 3) + patchwork::plot_annotation(tag_levels = 'A') & theme_pubclean() &
         theme(legend.position = 'bottom')
  qs::qsave(all,file.path(savedir, "Integration-Methods_plot.qs"))
  ggsave(file.path(savedir, "Integration-Methods.pdf"), width = 12, height = 6, plot = all)
  ggsave(file.path(savedir, "Integration-Methods.png"), width = 12, height = 6, plot = all, dpi=1000)

  #----------------------------------
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.cca", group.by ="orig.ident") +  labs(title = "CCAIntegration")
  p2 <- DimPlot(obj, reduction = "umap.rpca", group.by ="orig.ident") + labs(title = "RPCAIntegration")
  p3 <- DimPlot(obj, reduction = "umap.harmony", group.by ="orig.ident")+ labs(title = "HarmonyIntegration")
  p4 <- DimPlot(obj, reduction = "umap.mnn", group.by ="orig.ident")+  labs(title = "FastMNNIntegration")

  # merge plot
  all <- p + p1 + p2 + p3 + p4 + patchwork::plot_layout(ncol = 3) + 
         patchwork::plot_annotation(tag_levels = 'A') & theme_pubclean() &
         theme(legend.position = 'bottom')
  qs::qsave(all,file.path(savedir, "Integration-Methods-orig.ident_plot.qs"))
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.pdf"), width = 10, height = 12, plot = all)
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.png"), width = 10, height = 12, plot = all, dpi=1000)
  
  #----------------------------------

  # COMMENTS: Saving final integrated object and converting to v3 assay for compatibility
  info(logger, "  Saving final integrated object...")
  data.combined <- obj
  # saveRDS(data.combined, file.path(savedir, "integration.rds"))
  qs::qsave(data.combined, file.path(savedir, "integration_all.qs"))

  # convert a v5 assay to a v3 assay
  info(logger, "  Converting RNA assay to v3 format for compatibility...")
  data.combined[["RNA3"]] <- as(object = data.combined[["RNA"]], Class = "Assay")
  qs::qsave(data.combined, file.path(savedir, "integrationAssayv3_all.qs"))

  # return data
  info(logger, "  Joining layers and returning list...")
  scrna_seq_merge <- JoinLayers(data.combined)
  data_list <- list(data.combined, scrna_seq_merge)
  names(data_list) <- c("Origin", "JoinLayers")
  return(data_list)

  info(logger, "  DealPatch input integration & integration JoinLayers data name : JoinLayers ")

}

# ==============================================================================
# Function: DealPatchCCA
# Description: Performs CCA-only integration on Seurat objects.
#              Includes pre-processing, CCA integration, clustering, visualization and saving results.
# @ data : A merged Seurat object to integrate using CCA method.
# @ savedir : Output directory for plots and integrated objects.
# @ Resolute : Clustering resolution (default: 0.8).
# @ k.weight : Weight parameter for integration methods (default: 100).
# @ reduceType : Whether to generate tSNE plots in addition to UMAP (default: FALSE).
# ==============================================================================
DealPatchCCA <- function(data, savedir, Resolute, k.weight, reduceType='FALSE'){
  info(logger,  crayon::blue(crayon::bold("  Only run CCA integer")))
  # print dim parameter
  info(logger,  crayon::blue(crayon::bold("  Dafult setting dim = 1: 30 !!!!")))
  # Resolute <- 0.8
  tempdata <- data
  # k.weight=30
  # Resolute <- 0.8
  if (missing(k.weight)) {
    if (min(table(tempdata$orig.ident)) < 100){
      warn(logger, paste0("  You should seting k.weight < ", min(table(tempdata$orig.ident))))
      # print_color_note_warring(paste0(" you should seting k.weight < ",min(table(tempdata$orig.ident))))
      stop()
    }
  } else {
  }
  #----------------------------------
  # split merge data
  # COMMENTS: Split layers for integration - this is required for CCA integration
  debug(logger, "  Splitting layers by orig.ident (CCA only)...")
  obj <- tempdata
  obj[["RNA"]] <- split(obj[["RNA"]], f = obj$orig.ident)

  # Pre-processing steps for CCA integration
  debug(logger, "  Pre-processing (Normalize->FindVar->Scale->PCA) (CCA only)...")
  obj <- NormalizeData(obj)  # Normalize the data
  obj <- FindVariableFeatures(obj)  # Find variable features across cells
  obj <- ScaleData(obj)  # Scale the data to remove technical variation
  obj <- RunPCA(obj)  # Run principal component analysis

  # Auto-setting PC cutoff for unintegrated data
  debug(logger, "  Auto-setting PC cutoff (Non-Integrated) (CCA only)...")
  pc <- AutoSettingPcCutoff(obj, "Auto-pc-not-Integrate", savedir)

  # Find neighbors and clusters for unintegrated data
  obj <- FindNeighbors(obj, dims = 1:pc, reduction = "pca")
  obj <- FindClusters(obj, resolution = Resolute, cluster.name = "unintegrated_clusters")
  obj <- RunUMAP(obj, reduction = "pca", dims = 1:pc, reduction.name = "umap.unintegrated")
  #----------------------------------
  # print run condition
  info(logger, "  CCA Integration DO")
  # print_color_note_UP("CCA Integration DO!!")

  # Run CCA integration method
  info(logger, "  Executing CCA Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = CCAIntegration,
                    orig.reduction = "pca", new.reduction = "integrated.cca",
                    verbose = FALSE, k.weight=k.weight)
  }, level = "DEBUG")

  # Auto-setting PC cutoff for integrated data
  info(logger, "  Auto-setting PC cutoff for CCA Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-not-Integrate", savedir)

  # Cluster and visualize integrated data
  info(logger, "  Clustering and UMAP for CCA Integrated data...")
  obj <- FindNeighbors(obj, reduction = "integrated.cca", dims = 1:pc)
  obj <- FinClusterResCCA(SeuratObj = obj, dafult_res = 1.2)  # Apply clustering at multiple resolutions
  p <- DrawClusterTree(obj, integetmethods = 'CCA')  # Draw cluster tree
  qs::qsave(p,file.path(savedir, "cca.integrated.res.Tree_plot.qs"))
  ggsave(file.path(savedir, "cca.integrated.res.Tree.pdf"),
         width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "cca.integrated.res.Tree.png"),
         width = 10, height = 10, plot = p, dpi=1000)
  # Run UMAP for visualization
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "cca_clusters")
  obj <- RunUMAP(obj, reduction = "integrated.cca", dims = 1:pc, reduction.name = "umap.cca")
  if(reduceType == 'TRUE'){
    # Run tSNE if requested
    obj <- RunTSNE(obj, reduction = "integrated.cca", dims = 1:pc,
                    reduction.name = "tsne.cca", check_duplicates = FALSE)
  }

  # Save integrated object
  qs::qsave(obj, file.path(savedir, "integration.qs"))
  # print run condition
  info(logger, "  CCA Integration DONE")
  # print_color_note_DOWN("CCA Integration DONE!!")
  #----------------------------------
  #----------------------------------
  # Visualize results - comparing unintegrated vs CCA integrated
  debug(logger, "Generating comparison plots (CCA vs Unintegrated)...")
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="unintegrated_clusters", label = T) +
    NoLegend() + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.cca", group.by ="cca_clusters", label = T) +
    NoLegend() + labs(title = "CCAIntegration")
  # merge plot
  all <- p + p1 + patchwork::plot_layout(ncol = 1)
  all <- all + patchwork::plot_annotation(tag_levels = 'A')
  ggsave(file.path(savedir, "Integration-Methods.pdf"), width = 8, height = 8, plot = all)
  ggsave(file.path(savedir, "Integration-Methods.png"), width = 8, height = 8, plot = all, dpi=1000)
  
  #----------------------------------
  # Visualize by sample identity
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.cca", group.by ="orig.ident") +  labs(title = "CCAIntegration")
  # merge plot
  all <- p + p1 + patchwork::plot_layout(ncol = 2,guides = 'collect') & theme_pubclean() &
  theme(legend.position = 'bottom')
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.pdf"), width = 10, height = 10, plot = all)
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.png"), width = 10, height = 10, plot = all, dpi=1000)
  
  #----------------------------------
  # Prepare final results
  data.combined <- obj
  debug(logger, "Converting RNA assay to v3 format...")
  qs::qsave(data.combined, file.path(savedir, "integration.qs"))
  data.combined[["RNA3"]] <- as(object = data.combined[["RNA"]], Class = "Assay")
  qs::qsave(data.combined, file.path(savedir, "integrationAssayv3.qs"))
  # return data
  # return data
  debug(logger, "Joining layers and returning list...")
  scrna_seq_merge <- JoinLayers(data.combined)
  data_list <- list(data.combined, scrna_seq_merge)
  names(data_list) <- c("Origin", "JoinLayers")
  return(data_list)
  info(logger, "DealPatchCCA input integration & integration JoinLayers data name : JoinLayers ")
  # print_color_note("DealPatchCCA input integration & integration JoinLayers data name : JoinLayers ")
}

# ==============================================================================
# Function: DealPatchSCVI
# Description: Performs SCVI-only integration on Seurat objects.
#              Includes pre-processing, SCVI integration, clustering, visualization and saving results.
# @ data : A merged Seurat object to integrate using SCVI method.
# @ savedir : Output directory for plots and integrated objects.
# @ Resolute : Clustering resolution (default: 0.8).
# @ k.weight : Weight parameter for integration methods (default: 100).
# @ reduceType : Whether to generate tSNE plots in addition to UMAP (default: FALSE).
# ==============================================================================
DealPatchSCVI <- function(data, savedir, Resolute, k.weight, reduceType='FALSE',
                          conda_env = NULL){
  
  warn(logger, "  !!! RUN SCVI Integration Must INSTALL scvi-tools PYTHON package !!! ")
  warn(logger, paste0("  !!! scvi-tools CONDA ENVIRONMENT PATH: ", conda_env, " !!!"))

  # print dim parameter
  info(logger,  crayon::blue(crayon::bold("  Dafult setting dim = 1: 30 !!!!")))
  # Resolute <- 0.8
  tempdata <- data
  # k.weight=30
  # Resolute <- 0.8
  if (missing(k.weight)) {
    if (min(table(tempdata$orig.ident)) < 100){
      warn(logger, paste0("  You should seting k.weight < ", min(table(tempdata$orig.ident))))
      stop()
    }
  } else {
  }
  #----------------------------------
  # split merge data
  # COMMENTS: Split layers for integration - this is required for CCA integration
  debug(logger, "  Splitting layers by orig.ident (SCVI only)...")
  obj <- tempdata
  obj[["RNA"]] <- split(obj[["RNA"]], f = obj$orig.ident)

  # Pre-processing steps for SCVI integration
  debug(logger, "  Pre-processing (Normalize->FindVar->Scale->PCA) (SCVI only)...")
  obj <- NormalizeData(obj)  # Normalize the data
  obj <- FindVariableFeatures(obj)  # Find variable features across cells
  obj <- ScaleData(obj)  # Scale the data to remove technical variation
  obj <- RunPCA(obj)  # Run principal component analysis

  # Auto-setting PC cutoff for unintegrated data
  debug(logger, "  Auto-setting PC cutoff (Non-Integrated) (SCVI only)...")
  pc <- AutoSettingPcCutoff(obj, "Auto-pc-not-Integrate", savedir)

  # Find neighbors and clusters for unintegrated data
  obj <- FindNeighbors(obj, dims = 1:pc, reduction = "pca")
  obj <- FindClusters(obj, resolution = Resolute, cluster.name = "unintegrated_clusters")
  obj <- RunUMAP(obj, reduction = "pca", dims = 1:pc, reduction.name = "umap.unintegrated")
  #----------------------------------
  # print run condition
  info(logger, "  SCVI Integration DO")

  # Run CCA integration method
  info(logger, "  Executing SCVI Integration...")
  require(SeuratWrappers)
  # check python env
  require(reticulate)
  use_condaenv(conda_env, required = TRUE)
  py_config()
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = scVIIntegration,
                    orig.reduction = "pca", new.reduction = "integrated.scvi",
                    conda_env = conda_env,
                    verbose = FALSE, k.weight=k.weight)
  }, level = "DEBUG")

  # Auto-setting PC cutoff for integrated data
  info(logger, "  Auto-setting PC cutoff for SCVI Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-not-Integrate", savedir)

  # Cluster and visualize integrated data
  info(logger, "  Clustering and UMAP for SCVI Integrated data...")
  obj <- FindNeighbors(obj, reduction = "integrated.scvi", dims = 1:pc)
  obj <- FinClusterResSCVI(SeuratObj = obj, dafult_res = 1.2)  # Apply clustering at multiple resolutions
  p <- DrawClusterTree(obj, integetmethods = 'SCVI')  # Draw cluster tree
  qs::qsave(p,file.path(savedir, "scvi.integrated.res.Tree_plot.qs"))
  ggsave(file.path(savedir, "scvi.integrated.res.Tree.pdf"),
         width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "scvi.integrated.res.Tree.png"),
         width = 10, height = 10, plot = p, dpi=1000)
  # Run UMAP for visualization
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "cca_clusters")
  obj <- RunUMAP(obj, reduction = "integrated.scvi", dims = 1:pc, reduction.name = "umap.scvi")
  if(reduceType == 'TRUE'){
    # Run tSNE if requested
    obj <- RunTSNE(obj, reduction = "integrated.scvi", dims = 1:pc,
                    reduction.name = "tsne.scvi", check_duplicates = FALSE)
  }

  # print run condition
  info(logger, "  SCVI Integration DONE")
  #----------------------------------
  # Visualize results - comparing unintegrated vs CCA integrated
  debug(logger, "Generating comparison plots (SCVI vs Unintegrated)...")
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="unintegrated_clusters", label = T) +
    NoLegend() + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.scvi", group.by ="scvi_clusters", label = T) +
    NoLegend() + labs(title = "SCVIIntegration")
  # merge plot
  all <- p + p1 + patchwork::plot_layout(ncol = 1)
  all <- all + patchwork::plot_annotation(tag_levels = 'A')
  ggsave(file.path(savedir, "Integration-Methods.pdf"), width = 8, height = 8, plot = all)
  ggsave(file.path(savedir, "Integration-Methods.png"), width = 8, height = 8, plot = all, dpi=1000)
  
  #----------------------------------
  # Visualize by sample identity
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.scvi", group.by ="orig.ident") +  labs(title = "SCVIIntegration")
  # merge plot
  all <- p + p1 + patchwork::plot_layout(ncol = 2,guides = 'collect') & theme_pubclean() &
  theme(legend.position = 'bottom')
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.pdf"), width = 10, height = 10, plot = all)
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.png"), width = 10, height = 10, plot = all, dpi=1000)
  
  #----------------------------------
  # Prepare final results
  data.combined <- obj
  debug(logger, "Converting RNA assay to v3 format...")
  qs::qsave(data.combined, file.path(savedir, "integration_scvi.qs"))
  data.combined[["RNA3"]] <- as(object = data.combined[["RNA"]], Class = "Assay")
  qs::qsave(data.combined, file.path(savedir, "integrationAssayv3_scvi.qs"))

  debug(logger, "Joining layers and returning list...")
  scrna_seq_merge <- JoinLayers(data.combined)
  data_list <- list(data.combined, scrna_seq_merge)
  names(data_list) <- c("Origin", "JoinLayers")
  return(data_list)
  info(logger, "DealPatchSCVI input integration & integration JoinLayers data name : JoinLayers ")
  
}

# ==============================================================================
# Function: DealPatchRPCA
# Description: Performs RPCA-only integration on Seurat objects.
#              Includes pre-processing, RPCA integration, clustering, visualization and saving results.
# @ data : A merged Seurat object to integrate using  method.
# @ savedir : Output directory for plots and integrated objects.
# @ Resolute : Clustering resolution (default: 0.8).
# @ k.weight : Weight parameter for integration methods (default: 100).
# @ reduceType : Whether to generate tSNE plots in addition to UMAP (default: FALSE).
# ==============================================================================
DealPatchRPCA <- function(data, savedir, Resolute, k.weight, reduceType='FALSE'){
  info(logger,  crayon::blue(crayon::bold("  Only run RPCA integer")))
  # print dim parameter
  info(logger,  crayon::blue(crayon::bold("  Dafult setting dim = 1: 30 !!!!")))
  # Resolute <- 0.8
  tempdata <- data
  # k.weight=30
  # Resolute <- 0.8
  if (missing(k.weight)) {
    if (min(table(tempdata$orig.ident)) < 100){
      warn(logger, paste0("  You should seting k.weight < ", min(table(tempdata$orig.ident))))
      # print_color_note_warring(paste0(" you should seting k.weight < ",min(table(tempdata$orig.ident))))
      stop()
    }
  } else {
  }
  #----------------------------------
  # split merge data
  # COMMENTS: Split layers for integration - this is required for CCA integration
  debug(logger, "  Splitting layers by orig.ident (RPCA only)...")
  obj <- tempdata
  obj[["RNA"]] <- split(obj[["RNA"]], f = obj$orig.ident)

  # Pre-processing steps for CCA integration
  debug(logger, "  Pre-processing (Normalize->FindVar->Scale->PCA) (RPCA only)...")
  obj <- NormalizeData(obj)  # Normalize the data
  obj <- FindVariableFeatures(obj)  # Find variable features across cells
  obj <- ScaleData(obj)  # Scale the data to remove technical variation
  obj <- RunPCA(obj)  # Run principal component analysis

  # Auto-setting PC cutoff for unintegrated data
  debug(logger, "  Auto-setting PC cutoff (Non-Integrated) (CCA only)...")
  pc <- AutoSettingPcCutoff(obj, "Auto-pc-not-Integrate", savedir)

  # Find neighbors and clusters for unintegrated data
  obj <- FindNeighbors(obj, dims = 1:pc, reduction = "pca")
  obj <- FindClusters(obj, resolution = Resolute, cluster.name = "unintegrated_clusters")
  obj <- RunUMAP(obj, reduction = "pca", dims = 1:pc, reduction.name = "umap.unintegrated")
  #----------------------------------
  # print run condition
  info(logger, "  CCA Integration DO")
  # print_color_note_UP("CCA Integration DO!!")

  # Run CCA integration method
  info(logger, "  Executing RPCA Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = RPCAIntegration,
                    orig.reduction = "pca", new.reduction = "integrated.rpca",
                    verbose = FALSE)
  }, level = "DEBUG")

  # auto setting pc cutoff
  info(logger, "  Determining PC cutoff for RPCA Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-RPCA-Integrate", savedir)

  # cluster & reduce dim
  info(logger, "  Clustering and UMAP for RPCA Integrated data...")
  obj <- FindNeighbors(obj, reduction = "integrated.rpca", dims = 1:pc)
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "rpca_clusters")
  obj <- FinClusterResrpca(SeuratObj = obj, dafult_res = 1.2)
  p <- DrawClusterTree(obj, integetmethods = 'RPCA')
  ggsave(file.path(savedir, "rpca.integrated.res.Tree.pdf"), width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "rpca.integrated.res.Tree.png"), width = 10, height = 10, plot = p, dpi=1000)

  obj <- RunUMAP(obj, reduction = "integrated.rpca", dims = 1:pc, reduction.name = "umap.rpca")
  if(reduceType == 'TRUE'){
    obj <- RunTSNE(obj, reduction = "integrated.rpca", dims = 1:pc, reduction.name = "tsne.rpca", check_duplicates = FALSE)
  }

  # save integrated plot
  p <- DimPlot(obj, reduction = "umap.rpca", group.by ="orig.ident")  + labs(title = "RPCA.Integration")
  ggsave(file.path(savedir, "rpca.integrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "rpca.integrated.png"), width = 8, height = 7, plot = p, dpi=1000)
  
  info(logger, "  RPCA Integration DONE")
  
  #----------------------------------
  #----------------------------------
  # Visualize results - comparing unintegrated vs CCA integrated
  debug(logger, "Generating comparison plots (RPCA vs Unintegrated)...")
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="unintegrated_clusters", label = T) +
    NoLegend() + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.rpca", group.by ="rpca_clusters", label = T) +
    NoLegend() + labs(title = "RPCAIntegration")
  # merge plot
  all <- p + p1 + patchwork::plot_layout(ncol = 1)
  all <- all + patchwork::plot_annotation(tag_levels = 'A')
  ggsave(file.path(savedir, "Integration-Methods.pdf"), width = 8, height = 8, plot = all)
  ggsave(file.path(savedir, "Integration-Methods.png"), width = 8, height = 8, plot = all, dpi=1000)
  
  #----------------------------------
  # Visualize by sample identity
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
  p1 <- DimPlot(obj, reduction = "umap.rpca", group.by ="orig.ident") +  labs(title = "RPCAIntegration")
  # merge plot
  all <- p + p1 + patchwork::plot_layout(ncol = 2,guides = 'collect') & theme_pubclean() &
  theme(legend.position = 'bottom')
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.pdf"), width = 10, height = 10, plot = all)
  ggsave(file.path(savedir, "Integration-Methods-orig.ident.png"), width = 10, height = 10, plot = all, dpi=1000)
  
  #----------------------------------
  # Prepare final results
  data.combined <- obj
  debug(logger, "Converting RNA assay to v3 format...")
  qs::qsave(data.combined, file.path(savedir, "integration_rpca.qs"))
  data.combined[["RNA3"]] <- as(object = data.combined[["RNA"]], Class = "Assay")
  qs::qsave(data.combined, file.path(savedir, "integrationAssayv3_rpca.qs"))
  # return data
  # return data
  debug(logger, "Joining layers and returning list...")
  scrna_seq_merge <- JoinLayers(data.combined)
  data_list <- list(data.combined, scrna_seq_merge)
  names(data_list) <- c("Origin", "JoinLayers")
  return(data_list)
  info(logger, "DealPatchRPCA input integration & integration JoinLayers data name : JoinLayers ")
}


# ==============================================================================
# Function: DealPatchHarmony
# Description: Performs Harmony-only integration on Seurat objects.
#              Includes pre-processing, Harmony integration, clustering, visualization and saving results.
# @ data : A merged Seurat object to integrate using Harmony method.
# @ savedir : Output directory for plots and integrated objects.
# @ Resolute : Clustering resolution (default: 0.8).
# @ k.weight : Weight parameter for integration methods (default: 100) - not used in Harmony but kept for consistency.
# @ reduceType : Whether to generate tSNE plots in addition to UMAP (default: FALSE).
# ==============================================================================
DealPatchHarmony <- function(data, savedir, Resolute, k.weight, reduceType = 'FALSE'){
  # data <- all_project
  # print dim parameter
  info(logger, "  Dafult setting dim = 1: 30 !!!!")
  # Resolute <- 0.8
  tempdata <- data
  # check package
  packagelist <- as.data.frame(installed.packages())
  needlist <- c("SeuratWrappers","harmony","batchelor")
  # COMMENTS: Verify required packages are installed for Harmony integration
  if (all(needlist %in% packagelist$Package) == T){
    info(logger, "  DealPatch need Install SeuratWrappers & harmony Package")
    # print_color_note_NOTE("DealPatch need Install SeuratWrappers & harmony Package")
  }else{
    warn(logger, "  SeuratWrappers & harmony Package not intall")
    # print_color_note_warring("SeuratWrappers & harmony Package not intall")
    stop()
  }
  # loading package
  info(logger, "  Loading required libraries for Harmony integration...")
  suppressMessages(library(SeuratWrappers))
  suppressMessages(library(harmony))
  suppressMessages(library(batchelor))
  # k.weight=30
  # Resolute <- 0.8
  if (missing(k.weight)) {
    if (min(table(tempdata$orig.ident)) < 100){
      warn(logger, paste0("  You should seting k.weight < ", min(table(tempdata$orig.ident))))
      # print_color_note_warring(paste0(" you should seting k.weight < ",min(table(tempdata$orig.ident))))
      stop()
    }
  } else {
  }
  #----------------------------------
  # split merge data
  # COMMENTS: Split layers by 'orig.ident' for Harmony integration steps
  info(logger, "  Splitting layers by orig.ident (Harmony only)...")
  obj <- tempdata
  obj[["RNA"]] <- split(obj[["RNA"]], f = obj$orig.ident)

  # Pre-processing steps for Harmony integration
  info(logger, "  Pre-processing (Normalize->FindVar->Scale->PCA) (Harmony only)...")
  obj <- NormalizeData(obj)  # Normalize the data
  obj <- FindVariableFeatures(obj)  # Find variable features across cells
  obj <- ScaleData(obj)  # Scale the data to remove technical variation
  obj <- RunPCA(obj)  # Run principal component analysis

  # Auto-setting PC cutoff for unintegrated data
  info(logger, "  Auto-setting PC cutoff (Non-Integrated) (Harmony only)...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-not-Integrate", savedir)

  # Find neighbors and clusters for unintegrated data
  obj <- FindNeighbors(obj, dims = 1:pc, reduction = "pca")
  obj <- FindClusters(obj, resolution = Resolute, cluster.name = "unintegrated_clusters")
  obj <- RunUMAP(obj, reduction = "pca", dims = 1:pc, reduction.name = "umap.unintegrated")
  # Save unintegrated plot
  p <- DimPlot(obj, reduction = "umap.unintegrated", group.by ="orig.ident")  + labs(title = "UNIntegration")
  ggsave(file.path(savedir, "umap.unintegrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "umap.unintegrated.png"), width = 8, height = 7, plot = p, dpi=1000)
  #----------------------------------
  # print run condition
  info(logger, '  Harmony Integration DO')

  # Run Harmony integration method
  info(logger, "  Executing Harmony Integration...")
  obj <- with_logging(logger, {
    IntegrateLayers(object = obj, method = HarmonyIntegration,
                    orig.reduction = "pca", new.reduction = "harmony",
                    verbose = FALSE)
  }, level = "DEBUG")

  # Auto-setting PC cutoff for integrated data
  info(logger, "  Auto-setting PC cutoff for Harmony Integrated data...")
  pc <- AutoSettingPcCutoff(obj, "auto-pc-Harmony-Integrate", savedir)

  # Cluster and visualize integrated data
  info(logger, "  Clustering and UMAP for Harmony Integrated data...")
  obj <- FindNeighbors(obj, reduction = "harmony", dims = 1:pc)
  # obj <- FindClusters(obj, resolution = Resolute, cluster.name = "harmony_clusters")
  obj <- FinClusterResharmony(SeuratObj = obj, dafult_res = 1.2)  # Apply clustering at multiple resolutions
  p <- DrawClusterTree(obj, integetmethods = 'Harmony')  # Draw cluster tree
  ggsave(file.path(savedir, "harmony.integrated.res.Tree.pdf"), width = 10, height = 10, plot = p)
  ggsave(file.path(savedir, "harmony.integrated.res.Tree.png"), width = 10, height = 10, plot = p, dpi=1000)

  obj <- RunUMAP(obj, reduction = "harmony", dims = 1:pc,
                 reduction.name = "umap.harmony")
  if(reduceType == 'TRUE'){
    # Run tSNE if requested
    obj <- RunTSNE(obj, reduction = "harmony", dims = 1:pc,
                    reduction.name = "tsne.harmony", check_duplicates = FALSE)
  }

  # Save integrated plot
  p <- DimPlot(obj, reduction = "umap.harmony", group.by ="orig.ident")  + labs(title = "Harmony.Integration")
  ggsave(file.path(savedir, "harmony.integrated.pdf"), width = 8, height = 7, plot = p)
  ggsave(file.path(savedir, "harmony.integrated.png"), width = 8, height = 7, plot = p, dpi=1000)

  info(logger, '  Harmony Integration DONE')
  #----------------------------------
  # Prepare final results
  data.combined <- obj
  info(logger, "  Saving final integrated object...")
  # saveRDS(data.combined, file.path(savedir, "integration.rds"))
  qs::qsave(data.combined, file.path(savedir, "integration_harmony.qs"))

  # Convert a v5 assay to a v3 assay for compatibility
  info(logger, "  Converting RNA assay to v3 format...")
  data.combined[["RNA3"]] <- as(object = data.combined[["RNA"]], Class = "Assay")
  qs::qsave(data.combined, file.path(savedir, "integrationAssayv3_harmony.qs"))
  # return data

  info(logger, "  Joining layers and returning list...")
  scrna_seq_merge <- JoinLayers(data.combined)
  data_list <- list(data.combined, scrna_seq_merge)
  names(data_list) <- c("Origin", "JoinLayers")
  return(data_list)
}
# ==============================================================================
# Function: DimPlotIntegrscRNA
# Description: Draws UMAP plots of integrated data based on the integration method used.
#              Dispatches to appropriate plotting function depending on integration method.
# @ Ambient : A Seurat object containing integrated data.
# @ UMAP_dir : Directory to save the UMAP plots.
# @ intergetmethods : Integration method used ('CCA', 'Harmony', or 'ALL').
# ==============================================================================
DimPlotIntegrscRNA <- function(Ambient, UMAP_dir, intergetmethods){
  # COMMENTS: Helper function to dispatch plotting based on integration method
  # Purpose: Selects the appropriate UMAP visualization based on the integration method that was used
  # Input: Ambient - Seurat object with integrated data, UMAP_dir - output directory for plots,
  #        intergetmethods - the integration method used ('CCA', 'Harmony', or 'ALL')
  # Output: Calls appropriate plotting function based on the integration method
  debug(logger, paste0("  Drawing UMAP plot for integration method: ", intergetmethods))

  if (intergetmethods %in% c('CCA','ALL')){
    # Generate UMAP plot for CCA integrated data
    debug(logger, "  Calling UMAP plot for CCA integration...")
    DimPlotIntegr(Ambient, "Integr", "umap.cca", UMAP_dir)
  }else{
    if (intergetmethods %in% c('Harmony')){
      # Generate UMAP plot for Harmony integrated data
      debug(logger, "  Calling UMAP plot for Harmony integration...")
      DimPlotIntegr(Ambient, "Integr", "umap.harmony", UMAP_dir)
    }
  }
}

# ==============================================================================
# Main Function: IntergetPatch
# Description: Master controller for integration pipeline.
# @ all_project : A merged Seurat object to integrate.
# @ DealPatch_dir : Output directory for plots and integrated objects.
# @ DealPatchmethod : Integration method to use ('Harmony', 'CCA', or 'ALL').
# @ Resolute : Clustering resolution (default: 0.8).
# @ k.weight : Weight parameter for integration methods (default: 100).
# @ reduceType : Whether to generate tSNE plots in addition to UMAP (default: FALSE).
# ==============================================================================
IntergetPatch <- function(all_project,
                          DealPatch_dir,
                          DealPatchmethod = 'Harmony',
                          Resolute = 0.8,
                          k.weight = 100,
                          reduceType = "FALSE",
                          scvi_path = NULL){

  # COMMENTS: Dispatcher function to select the appropriate integration workflow.
  info(logger, paste0("  Starting Integration Pipeline with method: ", DealPatchmethod))
  debug(logger, paste0("  Integration parameters - method: ", DealPatchmethod, ", resolution: ", Resolute, ", k.weight: ", k.weight, ", reduceType: ", reduceType))

  if (DealPatchmethod == 'CCA'){
    warn(logger, '  Interget scRNA-seq by Seurat CCA methods')
    debug(logger, "  Running CCA integration method...")
    all_project <- DealPatchCCA(all_project, DealPatch_dir, Resolute, k.weight, reduceType)
  }else{
    if (DealPatchmethod == 'Harmony'){
        debug(logger, "  Running Harmony integration method...")
        all_project <- DealPatchHarmony(all_project, DealPatch_dir, Resolute, k.weight, reduceType)
        warn(logger, '  Interget scRNA-seq by harmony methods')
    }else{
      if (DealPatchmethod == 'ALL'){
        debug(logger, "  Running ALL integration methods (CCA, RPCA, Harmony, FastMNN)...")
        all_project <- DealPatch(all_project, DealPatch_dir, Resolute, k.weight, reduceType)
        warn(logger, '  Interget scRNA-seq by CCA & harmony & RPCA & FastMNN methods')
      }else{ 
        if(DealPatchmethod == 'RPCA'){
          debug(logger, "  Running RPCA integration method...")
          all_project <- DealPatchRPCA(all_project, DealPatch_dir, Resolute, k.weight, reduceType)
          warn(logger, '  Interget scRNA-seq by harmony methods')
        } else{
          debug(logger, "  Running SCVI integration method...")
          all_project <- DealPatchSCVI(all_project, DealPatch_dir, Resolute, k.weight, reduceType,
                                       conda_env = scvi_path)
          warn(logger, '  Interget scRNA-seq by SCVI methods')
        }
      }
    }
  }
  debug(logger, paste0("  Integration pipeline completed with method: ", DealPatchmethod))
  return(all_project)
}

# ==============================================================================
# Helper: Cluster Tree Visualization (Refactored)
# ==============================================================================
DrawClusterTree <- function(SeuratObj = SeuratObj,integetmethods = 'CCA'){
  # reference : Luke Zappia (https://lazappi.id.au/posts/2017-07-19-building-a-clustering-tree/)
  # Check_log_models()
  info(logger, '  Visablity Seurat findCluster result ')
  colour1 <- c('#E5D2DD', '#53A85F', '#F1BB72', '#F3B1A0', '#D6E7A3', '#57C3F3', '#476D87',
               '#E95C59', '#E59CC4', '#AB3282', '#23452F', '#BD956A', '#8C549C', '#585658',
               '#9FA3A8', '#E0D4CA', '#5F3D69', '#C5DEBA', '#58A4C3', '#E4C755', '#F7F398',
               '#AA9A59', '#E63863', '#E39A35', '#C1E6F3', '#6778AE', '#91D0BE', '#B53E2B',
               '#712820', '#DCC1DD', '#CCE0F5',  '#CCC9E6', '#625D9E', '#68A180', '#3A6963',
               '#968175')
  # Graphs
  suppressMessages(require(igraph))
  # Plotting
  suppressMessages(require(ggraph))
  suppressMessages(require(viridis))
  suppressMessages(require(tidyr))
  suppressMessages(require(dplyr))
  if (integetmethods == 'CCA'){
    clusterings <- SeuratObj@meta.data |> dplyr::select(matches('res_'))|>
    dplyr::select(matches('cca_clusters'))|>
    rename_with(~ gsub("^.*_clusters_res_", "res.", .))
  }else{
    if (integetmethods == 'Harmony'){
      clusterings <- SeuratObj@meta.data |> dplyr::select(matches('res_'))|>
      dplyr::select(matches('harmony_clusters'))|>
      rename_with(~ gsub("^.*_clusters_res_", "res.", .))
    }else{
      if (integetmethods == 'RPCA'){
        clusterings <- SeuratObj@meta.data |> dplyr::select(matches('res_'))|>
        dplyr::select(matches('rpca_clusters'))|>
        rename_with(~ gsub("^.*_clusters_res_", "res.", .))
      }else{
        if (integetmethods == 'MNN'){
          clusterings <- SeuratObj@meta.data |> dplyr::select(matches('res_'))|>
          dplyr::select(matches('mnn_clusters'))|>
          rename_with(~ gsub("^.*_clusters_res_", "res.", .))
        }
      }
    }
  }
  info(logger, '  moved from a cluster in the lower resolution to each cluster in the higher resolution')
  edges <- getEdges(clusterings)
  info(logger, '  Getting the nodes information')
  nodes <- getNodes(clusterings)
  # Create tree graph
  graph <- edges |>
    # Remove edges without any cell...
    dplyr::filter(TransCount > 0) |>
    # ...or making up only a small proportion of the new cluster
    dplyr::filter(TransPropTo > 0.02) |>
    # Rename the nodes
    dplyr::mutate(FromNode = paste0("R", FromRes, "C", FromClust)) |>
    dplyr::mutate(ToNode = paste0("R", ToRes, "C", ToClust)) |>
    # Reorder columns
    dplyr::select(FromNode, ToNode, everything()) |>
    mutate(TransCount = as.numeric(TransCount),
            TransPropTo = as.numeric(TransPropTo)) |>
    # Build a graph using igraph
    graph_from_data_frame(vertices = nodes, directed = TRUE)
  info(logger, '  Draw findCluster Cluster Tree plot')
  p <- ggraph(graph, layout = "tree") +
    # Plot the edges, colour is the number of cells and transparency is the
    # proportion contribution to the new cluster
    geom_edge_link() +
    # Plot the nodes, size is the number of cells
    geom_node_point(aes(colour = factor(Res),
                        size = Size)) +
    geom_node_text(aes(label = Cluster), size = 3) +
    # Adjust the scales
    scale_size(range = c(4, 15)) +
    scale_color_manual(values = colour1)+
    scale_edge_colour_gradientn(colours = colour1) +
    # Add legend labels
    guides(size = guide_legend(title = "Cluster Size", title.position = "top"),
           colour = guide_legend(title = "Clustering Resolution",
                                 title.position = "top"),
           edge_colour = guide_edge_colorbar(title = "Cell Count (log)",
                                             title.position = "top"),
           edge_alpha = guide_legend(title = "Cluster Prop",
                                     title.position = "top", nrow = 2)) +
    # Remove the axes as they don't really mean anything
    theme_void() +
    theme(legend.position = "bottom")
  return(p)
}

# Keep original helper functions (getEdges, getNodes) as they are logic-heavy and specific
getEdges <- function(clusterings) {
  transitions <- lapply(1:(ncol(clusterings) - 1), function(i) {
    from.res <- sort(colnames(clusterings))[i]
    to.res <- sort(colnames(clusterings))[i + 1]
    from.clusters <- sort(unique(clusterings[, from.res]))
    to.clusters <- sort(unique(clusterings[, to.res]))
    trans.df <- expand.grid(FromClust = from.clusters, ToClust = to.clusters)
    trans <- apply(trans.df, 1, function(x) {
      is.from <- clusterings[, from.res] == x[1]
      is.to <- clusterings[, to.res] == x[2]
      count <- sum(is.from & is.to)
      c(count, count / sum(is.from), count / sum(is.to))
    })
    trans.df$FromRes <- as.numeric(gsub("res.", "", from.res))
    trans.df$ToRes <- as.numeric(gsub("res.", "", to.res))
    trans.df$TransCount <- trans[1, ]
    trans.df$TransPropFrom <- trans[2, ]
    trans.df$TransPropTo <- trans[3, ]
    return(trans.df)
  })
  do.call("rbind", transitions)
}

getNodes <- function(clusterings) {
  
  clusterings %>%
    tidyr::gather(key = Res, value = Cluster) %>%      # gather 属于 tidyr 包
    dplyr::group_by(Res, Cluster) %>%                  # group_by 属于 dplyr 包
    dplyr::summarise(Size = dplyr::n()) %>%            # summarise 和 n() 属于 dplyr 包
    dplyr::ungroup() %>%                               # ungroup 属于 dplyr 包
    dplyr::mutate(                                     # mutate 属于 dplyr 包
      Res = as.numeric(gsub("res.", "", Res)),         # gsub, as.numeric 是 R 基础包(base)，不需要加前缀
      Node = paste0("R", Res, "C", Cluster)            # paste0 是 R 基础包(base)
    ) %>%
    dplyr::select(Node, dplyr::everything())           # select 和 everything 属于 dplyr 包
}

# ==============================================================================
# Function: DimPlotIntegr
# Description: Standardized UMAP plotting helper.
# ==============================================================================
DimPlotIntegr <- function(data, name, reDname, figure_dir){
  p <- DimPlot(data, reduction = reDname, group.by = 'orig.ident') +
    ggtitle(paste0(name, " UMAP")) + theme_classic()

  ggsave(file.path(figure_dir, paste0(name, "-", reDname, ".pdf")), plot = p, width = 8, height = 6)
  ggsave(file.path(figure_dir, paste0(name, "-", reDname, ".png")), plot = p, width = 8, height = 6, dpi = 1000)
}
# ==============================================================================
# END 
# ==============================================================================