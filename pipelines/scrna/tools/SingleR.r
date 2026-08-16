# Verion: 1.1v
# Date: 2024.8.29
# Author: Jian Zhang
# loading SingleR Packages
require(SingleR)
require(dplyr)
require(BiocParallel)
# loading SingleR reference
MouseImmGenref <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/MouseImmGen.rds")
MouseRNAref <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/MouseRNA.rds")
HuamnBlueprintEncode <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/HuamnBlueprintEncode.rds")
HumanDICEImmuneCell <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/HumanDICEImmuneCell.rds")
HumanMonacoImmune <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/HumanMonacoImmune.rds")
HumanNovershternHematopoietic <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/HumanNovershternHematopoietic.rds")
HumanPrimaryCellAtla <- readRDS("/glusterfs/home/local_zhang_jian/dataset/Celldex/HumanPrimaryCellAtla.rds")
##----SingleR Auto Annotation functions ----##
# print run condition
print_color_note_UP <- function(logo){
  # input print with print
  if (is.na(width_print)){
    width_print <- 80
  }else{
    width_print <- width_print
  }
  # print subfactor of print dafult:(●´∀｀●)ﾉ
  logo_style_1 <- "(●´∀｀●)ﾉ"
  logo_style_2 <- "(￣▽￣)~*"
  padded_text_style1 <- str_pad(logo_style_1, width=width_print, pad = "#", side = "both")
  padded_text_style2 <- str_pad(logo_style_2, width=width_print, pad = "#", side = "both")
  # pint
  cat(bold(cyan(padded_text_style1)),"\n")
  cat("\n")
  cat(bold(str_pad(logo, width=width_print, pad = " ", side = "both"),"\n"))
  cat("\n")
}
# print run condition
print_color_note_DOWN <- function(logo){
  # input print with print
  if (is.na(width_print)){
    width_print <- 80
  }else{
    width_print <- width_print
  }
  # print subfactor of print dafult:(●´∀｀●)ﾉ
  logo_style_1 <- "(●´∀｀●)ﾉ"
  logo_style_2 <- "(￣▽￣)~*"
  padded_text_style1 <- str_pad(logo_style_1, width=width_print, pad = "#", side = "both")
  padded_text_style2 <- str_pad(logo_style_2, width=width_print, pad = "#", side = "both")
  # pint
  cat("\n")
  cat(bold(str_pad(logo, width=width_print, pad = " ", side = "both"),"\n"))
  cat("\n")
  cat(bold(cyan(padded_text_style2)))
  cat("\n")
}
# print run condition
print_color_note_warring <- function(logo){
  # input print with print
  if (is.na(width_print)){
    width_print <- 80
  }else{
    width_print <- width_print
  }
  # print subfactor of print dafult:(●´∀｀●)ﾉ
  logo_style_1 <- "(σ｀д′)σ"
  logo_style_2 <- "(σ｀д′)σ"
  padded_text_style1 <- str_pad(logo_style_1, width=width_print, pad = "#", side = "both")
  padded_text_style2 <- str_pad(logo_style_2, width=width_print, pad = "#", side = "both")
  # pint
  cat(bold(bgRed(padded_text_style1)),"\n")
  cat("\n")
  cat(bold(str_pad(logo, width=width_print, pad = " ", side = "both"),"\n"))
  cat("\n")
  cat(bold(bgRed(padded_text_style2)))
  cat("\n")
}
# Check tax ID
Check_tax_ID <- function(tax_ID){
  # Check tax_ID
  if (tax_ID == 9606){
    tax_ID <- "human"
  }else if(tax_ID == 10090){
    tax_ID <- "mouse"
  }else{
    print_color_note_warring('tax_ID not in human & mouse')
    stop()
  }
  return(tax_ID)
}
## SigleRAnn cell levels
AutoSigleRAnn_cell <- function(data, tax_ID, annotation_SinglR_dir){
  # Redame : This is auto SigleR annotation function
  # data : seurat object
  # tax_ID : special taxid human : 9606 & mouse 10090
  # annotation_SinglR_dir : singleR annotation output dir
  Check_tax_ID(tax_ID)
  # save data@meta.data -> rds
  Idents(data) <- data$seurat_clusters
  # get log data
  data_for_SingleR <- LayerData(data, assay = "RNA", layer = "data")
  rename_safe <- function(df, old, new){
    if (old %in% colnames(df)) {
      warning(paste("Column name", old, "already exists in the dataframe. Renaming skipped."))
      df
    } else {
      df <- df |> dplyr::rename(!!new := !!old)
      df
    }
  }
  if (tax_ID == 10090){
    Mouse_list <- c("MouseImmGenref" = MouseImmGenref, "MouseRNAref" = MouseRNAref)
    for (i in names(Mouse_list)){
      print_color_note_UP(paste0("SingleR Reference : ", i, " Auto annotation (Cell levels) DO!!!"))
      data@meta.data <- data@meta.data |> dplyr::select(orig.ident,nCount_RNA,nFeature_RNA,percent.mt,seurat_clusters)
      # MouseImmGenref label.main
      Mouse.main <- SingleR(test = data_for_SingleR,
                            ref = Mouse_list[[i]],
                            labels = Mouse_list[[i]]$label.main,
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            check.missing = F,
                            BPPARAM = MulticoreParam(workers = 40))
      # rename
      data@meta.data$main.labels <- Mouse.main$labels
      data@meta.data$main.labels_1 <- Mouse.main$labels
      data@meta.data <- rename_safe(data@meta.data, "main.labels_1", paste0(i, "_main_labels"))
      # MouseImmGenref  label.fine
      Mouse.fine <- SingleR(test = data_for_SingleR,
                            ref = Mouse_list[[i]],
                            labels = Mouse_list[[i]]$label.fine,
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            BPPARAM = MulticoreParam(workers = 40))
      # rename
      data@meta.data$fine.labels <- Mouse.fine$labels
      data@meta.data$fine.labels_1 <- Mouse.fine$labels
      data@meta.data <- rename_safe(data@meta.data, "fine.labels_1", paste0(i, "_fine_labels"))
      print_color_note_DOWN(paste0("SingleR Reference: ", i, " Auto annotation (Cell levels) DONE !!!"))
      saveRDS(data@meta.data, file.path(annotation_SinglR_dir, paste0(i, "-", "scrna_seq_cell_interget_SigleAnnData.rds")))
    }
  } else if (tax_ID == 9606){
    human_list <- c("HuamnBlueprintEncode" = HuamnBlueprintEncode,
                    "HumanDICEImmuneCell" = HumanDICEImmuneCell,
                    "HumanMonacoImmune" = HumanMonacoImmune,
                    "HumanNovershternHematopoietic" = HumanNovershternHematopoietic,
                    "HumanPrimaryCellAtla" = HumanPrimaryCellAtla)
    for (i in names(human_list)){
      print_color_note_UP(paste0("SingleR Reference: ", i, " Auto annotation (Cell levels) DO!!!"))
      data@meta.data <- data@meta.data |> dplyr::select(orig.ident,nCount_RNA,nFeature_RNA,percent.mt,seurat_clusters)
      human.main <- SingleR(test = data_for_SingleR,
                            ref = human_list[[i]],
                            labels = human_list[[i]]$label.main,
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            BPPARAM = MulticoreParam(workers = 40))
      # rename
      data@meta.data$main.labels <- human.main$labels
      data@meta.data$main.labels_1 <- human.main$labels
      data@meta.data <- rename_safe(data@meta.data, "main.labels_1", paste0(i, "_main_labels"))
      # MouseImmGenref  label.fine
      human.fine <- SingleR(test = data_for_SingleR,
                            ref = human_list[[i]],
                            labels = human_list[[i]]$label.fine,
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            BPPARAM = MulticoreParam(workers = 40))
      # rename
      data@meta.data$fine.labels <- human.fine$labels
      data@meta.data$fine.labels_1 <- human.fine$labels
      data@meta.data <- rename_safe(data@meta.data, "fine.labels_1", paste0(i, "_fine_labels"))
      # save result
      print_color_note_DOWN(paste0("SingleR Reference: ", i, " Auto annotation (Cell levels) DONE!!!"))
      saveRDS(data@meta.data, file.path(annotation_SinglR_dir, paste0(i, "-", "scrna_seq_cell_interget_SigleAnnData.rds")))
    }
  }
  return(data)
}
## SigleRAnn Cluster levels
AutoSigleRAnn_Cluster <- function(data, tax_ID, annotation_SinglR_dir){
  # Redame : This is auto SigleR annotation function
  # data : seurat object
  # tax_ID : special taxid human : 9606 & mouse 10090
  # annotation_SinglR_dir : singleR annotation output dir
  Check_tax_ID(tax_ID)
  # save data@meta.data -> rds
  Idents(data) <- data$seurat_clusters
  sce_data <- as.SingleCellExperiment(data)
  rename_safe <- function(df, old, new){
    if (old %in% colnames(df)) {
      warning(paste("Column name", old, "already exists in the dataframe. Renaming skipped."))
      df
    } else {
      df <- df |> dplyr::rename(!!new := !!old)
      df
    }
  }
  if (tax_ID == 10090){
    Mouse_list <- c("MouseImmGenref" = MouseImmGenref, "MouseRNAref" = MouseRNAref)
    for (i in names(Mouse_list)){
      print_color_note_UP(paste0("SingleR Reference: ", i, " Auto annotation (Cluster levels) DO!!!"))
      data@meta.data <- data@meta.data |> dplyr::select(orig.ident,nCount_RNA,nFeature_RNA,percent.mt,seurat_clusters)
      # MouseImmGenref label.main
      Mouse.main <- SingleR(sce_data,
                            ref = Mouse_list[[i]],
                            clusters = Idents(data),
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            labels = Mouse_list[[i]]$label.main,
                            BPPARAM = MulticoreParam(workers = 20))
      # rename
      cluster.ids <- Mouse.main$labels
      names(cluster.ids) <- levels(data)
      data <- RenameIdents(data, cluster.ids)
      data$Celltype <- Idents(data)
      colnames(data@meta.data)[which(colnames(data@meta.data) == "Celltype")] <- paste0(i, "_main_cluster")
      # data@meta.data <- rename_safe(data@meta.data, "Celltype", paste0(i, "_main_cluster_labels"))
      Idents(data) <- data$seurat_clusters
      # MouseImmGenref  label.fine
      Mouse.fine <- SingleR(sce_data,
                            ref = Mouse_list[[i]],
                            clusters = Idents(data),
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            labels = Mouse_list[[i]]$label.fine,
                            BPPARAM = MulticoreParam(workers = 20))
      # rename
      cluster.ids <- Mouse.fine$labels
      names(cluster.ids) <- levels(data)
      data <- RenameIdents(data, cluster.ids)
      data$Celltype <- Idents(data)
      colnames(data@meta.data)[which(colnames(data@meta.data) == "Celltype")] <- paste0(i, "_fine_cluster")
      # data@meta.data <- rename_safe(data@meta.data, "Celltype", paste0(i, "_fine_cluster_labels"))
      Idents(data) <- data$seurat_clusters
      # save RDS
      print_color_note_DOWN(paste0("SingleR Reference: ", i, " Auto annotation (Cluster levels) DONE!!!"))
      saveRDS(data@meta.data, file.path(annotation_SinglR_dir, paste0(i, "-", "scrna_seq_cluster_interget_SigleAnnData.rds")))
    }
  } else if (tax_ID == 9606){
    human_list <- c("HuamnBlueprintEncode" = HuamnBlueprintEncode,
                    "HumanDICEImmuneCell" = HumanDICEImmuneCell,
                    "HumanMonacoImmune" = HumanMonacoImmune,
                    "HumanNovershternHematopoietic" = HumanNovershternHematopoietic,
                    "HumanPrimaryCellAtla" = HumanPrimaryCellAtla)
    for (i in names(human_list)){
      print_color_note_UP(paste0("SingleR Reference: ", i, " Auto annotation (Cluster levels) DO!!!"))
      data@meta.data <- data@meta.data |> dplyr::select(orig.ident,nCount_RNA,nFeature_RNA,percent.mt,seurat_clusters)
      # human.main
      human.main <- SingleR(sce_data,
                            ref = human_list[[i]],
                            clusters = Idents(data),
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            labels = human_list[[i]]$label.main,
                            BPPARAM = MulticoreParam(workers = 20))
      # rename
      cluster.ids <- human.main$labels
      names(cluster.ids) <- levels(data)
      data <- RenameIdents(data, cluster.ids)
      data$Celltype <- Idents(data)
      colnames(data@meta.data)[which(colnames(data@meta.data) == "Celltype")] <- paste0(i, "_main_cluster")
      # data@meta.data <- rename_safe(data@meta.data, "Celltype_main_labels", paste0(i, "_main_cluster_labels"))
      Idents(data) <- data$seurat_clusters
      # label.fine
      human.fine <- SingleR(sce_data,
                            ref = human_list[[i]],
                            clusters = Idents(data),
                            assay.type.test = "logcounts",
                            assay.type.ref = "logcounts",
                            labels = human_list[[i]]$label.fine,
                            BPPARAM = MulticoreParam(workers = 20))
      # annotation
      cluster.ids <- human.fine$labels
      names(cluster.ids) <- levels(data)
      data <- RenameIdents(data, cluster.ids)
      data$Celltype <- Idents(data)
      colnames(data@meta.data)[which(colnames(data@meta.data) == "Celltype")] <- paste0(i, "_fine_cluster")
      # data@meta.data <- rename_safe(data@meta.data, "Celltype_fine_labels", paste0(i, "_fine_cluster_labels"))
      Idents(data) <- data$seurat_clusters
      # save rds
      print_color_note_DOWN(paste0("SingleR Reference: ", i, " Auto annotation (Cluster levels) DONE!!!"))
      saveRDS(data@meta.data, file.path(annotation_SinglR_dir, paste0(i, "-", "scrna_seq_cluster_interget_SigleAnnData.rds")))
    }
  }
  return(data)
}
##----SingleR Auto Annotation functions ----##