# Seurat Seurat result Dir s4 class
# ==============================================================================
# Function: create_dir
# Description: Iterates through a list of directory paths. Checks if each directory
#              exists; if not, creates it recursively.
# Parameters:
#   list_dir: A vector of directory paths to check/create.
# ==============================================================================
create_dir <- function(list_dir){
  for (i in list_dir) {
    if(!dir.exists(i)){
      dir.create(i, recursive = TRUE, showWarnings = FALSE)
      if(exists("logger") && inherits(logger, "logger")) info(logger, paste("  Created directory:", i))
    }
  }
}


# R tree command function
print_tree <- function(path = ".", indent = 0, is_last = TRUE) {
  files <- list.files(path, full.names = TRUE)
  dirs <- files[file.info(files)$isdir]
  files <- files[!file.info(files)$isdir]
  if (identical(path, ".")) {
    cat("🌳", basename(path), "\n", sep = "")
  } else {
    cat(paste(rep("│   ", max(0, indent - 1)), collapse = ""), 
        if (is_last) "└── " else "├── ", basename(path), "\n", sep = "")
  }
  
  for (i in seq_along(dirs)) {
    is_last <- i == length(dirs)
    print_tree(dirs[i], indent + 1, is_last)
  }
  
  if (length(files) > 0) {
    cat(paste(rep("│   ", indent), collapse = ""), "|── ", basename(files), "\n", sep = "")
  }
}

create_scRNA_dir <- function(root_dir,save_output_name){
    # set save dir (output&figure) dir
    save_dir <- file.path(root_dir,save_output_name)
    output_dir <- file.path(save_dir,"output")
    # set QC dir path
    figure_dir <- file.path(save_dir,"figure")
    BatchCheck_dir <- file.path(save_dir,"BatchCheck")
    DealPatch_dir <- file.path(save_dir,"DealPatch")
    qc_dir <- file.path(save_dir,"QC")
    Cellranger_dir <- file.path(qc_dir,"Cellranger-result")
    RNAContamination_dir <- file.path(qc_dir,"RNAContamination")
    doublet_dir <- file.path(qc_dir,"doublet")
    # set cluster dir path
    cluster_dir <- file.path(save_dir,"cluster")
    UMAP_dir <- file.path(cluster_dir,"UMAP-plot")
    tsne_dir <- file.path(cluster_dir,"tSNE-plot")
    cluster_marker_gene_dir <- file.path(cluster_dir,"marker_gene")
    DoHeatmap_dir <- file.path(cluster_dir,"DoHeatmap-plot")
    DotPlot_dir <- file.path(cluster_dir,"DotPlot-plot")
    subset_cell_cluster <- file.path(figure_dir,"subset_cell_cluster")
    # set annotation dir path
    annotation_dir <- file.path(save_dir,"annotation")
    annotation_SinglR_dir <- file.path(annotation_dir,"auto-annotation-SinglR")
    annotation_CellID_dir <- file.path(annotation_dir,"auto-annotation-CellID")
    proportions_dir <- file.path(annotation_dir,"proportions-plot")
    deg_figure_dir <-  file.path(figure_dir,"deg")
    marker_gene_output_dir <-  file.path(deg_figure_dir,"marker_gene")
    # create dir one by one
    create_dir(c(save_dir,output_dir,figure_dir,qc_dir,Cellranger_dir,RNAContamination_dir,doublet_dir,
                cluster_dir,UMAP_dir,tsne_dir,DoHeatmap_dir,cluster_marker_gene_dir,annotation_dir,
                annotation_SinglR_dir,annotation_CellID_dir,proportions_dir,DotPlot_dir,subset_cell_cluster,
                BatchCheck_dir,DealPatch_dir,deg_figure_dir,marker_gene_output_dir))
    #-----------------------------------------#
    # define SeuratResDir
    setClass("SeuratResDir",
            slots = list(save_dir = "character",
                        output_dir = "character",
                        figure_dir = "character",
                        qc_dir = "character",
                        Cellranger_dir = "character",
                        RNAContamination_dir = "character",
                        doublet_dir = 'character',
                        BatchCheck_dir = "character",
                        DealPatch_dir = "character",
                        cluster_dir = "character",
                        UMAP_dir = "character",
                        tsne_dir = "character",
                        DoHeatmap_dir = "character",
                        cluster_marker_gene_dir = "character",
                        annotation_dir = "character",
                        annotation_SinglR_dir =  "character",
                        annotation_CellID_dir =  "character",
                        proportions_dir = "character",
                        DotPlot_dir = "character",
                        subset_cell_cluster = "character",
                        deg_figure_dir = "character",
                        marker_gene_output_dir = 'character'))
    #-----------------------------------------#
    # create SeuratResDir S4 class
    SeuratResDir <- new("SeuratResDir", save_dir = file.path(root_dir,save_output_name),
                        output_dir = file.path(save_dir,"output"),
                        figure_dir = file.path(save_dir,"figure"),
                        qc_dir = file.path(save_dir,"QC"),
                        Cellranger_dir = file.path(qc_dir,"Cellranger-result"),
                        RNAContamination_dir = file.path(qc_dir,"RNAContamination"),
                        doublet_dir = file.path(qc_dir,"doublet"),
                        BatchCheck_dir = file.path(save_dir,"BatchCheck"),
                        DealPatch_dir = file.path(save_dir,"DealPatch"),
                        cluster_dir = file.path(save_dir,"cluster"),
                        UMAP_dir = file.path(cluster_dir,"UMAP-plot"),
                        tsne_dir = file.path(cluster_dir,"tSNE-plot"),
                        DoHeatmap_dir = file.path(cluster_dir,"DoHeatmap-plot"),
                        cluster_marker_gene_dir = file.path(cluster_dir,"marker_gene"),
                        annotation_dir = file.path(save_dir,"annotation"),
                        annotation_SinglR_dir =  file.path(annotation_dir,"auto-annotation-SinglR"),
                        annotation_CellID_dir = file.path(annotation_dir,"auto-annotation-CellID") ,
                        proportions_dir = file.path(annotation_dir,"proportions-plot"),
                        DotPlot_dir = file.path(cluster_dir,"DotPlot-plot"),
                        subset_cell_cluster = file.path(figure_dir,"subset_cell_cluster"),
                        deg_figure_dir = file.path(figure_dir,"deg"),
                        marker_gene_output_dir = file.path(deg_figure_dir,"marker_gene"))
    return(SeuratResDir)
}
# ==============================================================================
# END 
# ==============================================================================
