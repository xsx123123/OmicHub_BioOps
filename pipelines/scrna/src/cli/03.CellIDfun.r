# author  : zhang jian
# version : 1.1v
# date    : 2025-2-6
# description : this is scRNA-seq annotation pipeline power by CelliD
# visablity color list
colour <- c("#DC143C","#0000FF","#20B2AA","#FFA500","#9370DB","#98FB98","#F08080","#1E90FF","#7CFC00","#FFFF00",
            "#808000","#FF00FF","#FA8072","#7B68EE","#9400D3","#800080","#A0522D","#D2B48C","#D2691E","#87CEEB",
            "#40E0D0","#5F9EA0","#FF1493","#0000CD","#008B8B","#FFE4B5","#8A2BE2","#228B22","#E9967A","#4682B4",
            "#32CD32","#F0E68C","#FFFFE0","#EE82EE","#FF6347","#6A5ACD","#9932CC","#8B008B","#8B4513","#DEB887",
            "#f6bcfd","#8dd3c6","#ffc512","#ffa300","#ff7d00","#ff6581","#f8d90d","#a5da6b","#e578d6","#ffd2d8",
            "#90e4cd","#84dce0","#fe65b3","#D3F8E2","#E4C1F9","#F5B7B1","#A0E8AF","#FFF0F5","#FFC48C","#A8E6CE",
            "#DC143C","#0000FF","#20B2AA","#FFA500","#9370DB","#98FB98","#F08080","#1E90FF")
# main function
# check log models function
Check_log_models <- function(){
  # loading packages
  require(log4r)
  require(stringr)
  require(crayon)
  require(praise)
  # Check log models
  if (exists("logger") && class(logger) == "logger") {
    cat("The logger object exists and is of class 'logger \n")
  } else {
    cat("The logger object don't exists & loading log4r models \n")
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
    logger <- log4r::logger()
    logger <- log4r::logger(threshold = "INFO",appenders = list(console_appender(my_layout)))
  }
}
# PanglaoDB database deal function
CelliDPanglaoDB <- function(organ,species,PanglaoDB_ref){
  # loading packages
  require(tidyverse)
  ref <- PanglaoDB_ref
  organlist <- ref |> dplyr::select(organ);organlist <- names(table(organlist))
  # print_color_note_UP(paste0("CelliD PanglaoDB Can annotation Tissue"))
  info(logger, 'CelliD PanglaoDB Can annotation Tissue 🔽 ')
  print(organlist)
  # print_color_note_DOWN("CelliD PanglaoDB Can annotation Tissue")
  info(logger, 'CelliD PanglaoDB Can annotation Tissue 🔼 ')
  # check organ
  if (organ %in% organlist){
    panglao <- ref |> dplyr::filter(organ == organ) |> dplyr::filter(str_detect(species,species)) |>
      dplyr::group_by(`cell type`) |> dplyr::summarise(geneset = list(`official gene symbol`))
    # create ref cell maker ref
    panglao_gs <- setNames(panglao$geneset, panglao$`cell type`)
    if (max(sapply(panglao_gs, length)) < 10){
      warn(logger, 'Reference Gene set is very few')
      # print_color_note_warring("Reference Gene set is very few !!!")
      panglao_gs <- panglao_gs
    }else{
      panglao_gs <- panglao_gs[sapply(panglao_gs, length) >= 10]
    }
    # Mn cell marker convert
    if (species == "Mm"){
      for (i in c(1:length(names(panglao_gs)))){
        panglao_gs[[i]] <- paste(toupper(substr(panglao_gs[[i]], 1, 1)), tolower(substr(panglao_gs[[i]], 2, nchar(panglao_gs[[i]]))), sep = "")
      }
    }
  }else{
    stop("Error")
  }
  return(panglao_gs)
}
# Cellmarker database deal function
CelliDCellmarker <- function(organ,species,Cellmarker_Humanref,Cellmarker_Mouseref){
  # loading packages
  require(tidyverse)
  Humanref <- Cellmarker_Humanref
  if (species == "Hs"){
    organlist <- Humanref |> dplyr::select(tissue_class);organlist <- names(table(organlist))
    organlist <- na.omit(organlist)
    # print_color_note_UP(paste0("CellMarker Can annotation Tissue"))
    info(logger, 'CellMarker Can annotation Tissue 🔽 ')
    print(organlist)
    info(logger, 'CellMarker Can annotation Tissue 🔼 ')
    # check organ
    if (organ %in% organlist){
      cellmarker <- Humanref |> dplyr::filter(tissue_class == organ) |> 
        dplyr::group_by(`cell_name`) |> dplyr::summarise(geneset = list(`marker`))
      # create ref cell maker ref
      panglao_gs <- setNames(cellmarker$geneset, cellmarker$`cell_name`)
      if (max(sapply(panglao_gs, length)) < 10){
        warn(logger, 'Reference Gene set is very few')
        # print_color_note_warring("Reference Gene set is very few !!!")
        panglao_gs <- panglao_gs
      }else{
        panglao_gs <- panglao_gs[sapply(panglao_gs, length) >= 10]
      }
    }else{
      stop("Error")
    }
  }else{
    if (species == "Mm"){
      Mouseref <- Cellmarker_Mouseref
      organlist <- Mouseref |> dplyr::select(tissue_class);organlist <- names(table(organlist))
      organlist <- na.omit(organlist)
      print_color_note_UP(paste0("CellMarker Can annotation Tissue"))
      print(organlist)
      print_color_note_DOWN("CellMarker Can annotation Tissue")
      # check organ
      if (organ %in% organlist){
        cellmarker <- Mouseref |> dplyr::filter(tissue_class == organ) |> 
          dplyr::group_by(`cell_name`) |> dplyr::summarise(geneset = list(`marker`))
        # create ref cell maker ref
        panglao_gs <- setNames(cellmarker$geneset, cellmarker$`cell_name`)
        if (max(sapply(panglao_gs, length)) < 10){
          warn(logger, 'Reference Gene set is very few')
          # print_color_note_warring("Reference Gene set is very few !!!")
          panglao_gs <- panglao_gs
        }else{
          panglao_gs <- panglao_gs[sapply(panglao_gs, length) >= 10]
        }
      }else{
        stop("Error")
      }
    }
  }
  return(panglao_gs)
}
# check AnnGeneSet scRNAref
check_AnnGeneSet_scRNAref <- function(scRNAref){
  if (scRNAref %in% c('Cellmarker','PanglaoDB')){
    info(logger, 'scRNA-seq CelliD Annotation Power by CelliD ')
  }else{
    warn(logger, 'Please check the settings for viewing the annotated dataset name (scRNAref) ')
  }
}
# Get scRNA-seq annotation geneset function
AnnGeneSet <- function(scRNAref,organ,species,Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref){
  check_AnnGeneSet_scRNAref(scRNAref)
  if(scRNAref == "Cellmarker"){
    info(logger, 'scRNA-seq CelliD Annotation Reference : Cellmarker 2.0 ')
    # Cellmarker database
    pathway <- CelliDCellmarker(organ,species,Cellmarker_Humanref,Cellmarker_Mouseref)
  }else{
    if (scRNAref == "PanglaoDB"){
      info(logger, 'scRNA-seq CelliD Annotation Reference : PanglaoDB ')
      # PanglaoDB database
      pathway <- CelliDPanglaoDB(organ,species,PanglaoDB_ref)
    }
  }
  return(pathway)
}
# annotation
checkCellmarkerAnno <- function(SingleCell,scRNAref,organ,species,Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref,pathways){
  require(CelliD)
  # SingleCellExperiment
  if(max(sapply(pathways, length)) < 10){
    # print warring
    warn(logger, 'Because ref gene set is very few Annotation will use  minSize = 1')
    # print_color_note_warring(" Because ref gene set is very few;Annotation will use  minSize = 1 ")
    # SingleCellExperiment enrichment
    HGT_gs <- CelliD::RunCellHGT(SingleCell,
                         pathways = pathways,
                         dims = 1:30,
                         n.features = 200,
                         minSize = 1)
  }else{
    info(logger, 'RunCellHGT')
    # SingleCellExperiment enrichment
    HGT_gs <- CelliD::RunCellHGT(SingleCell,
                         pathways = pathways,
                         dims = 1:30,
                         n.features = 200,
                         minSize = 10)
  }
  return(HGT_gs)
}
# CelliD annotation
CelliDAnnotation <- function(data,HGT_panglao_gs,panglao_gs){
  panglao_gs_prediction <- rownames(HGT_panglao_gs)[apply(HGT_panglao_gs, 2, which.max)]
  if (max(sapply(panglao_gs, length)) < 10){
    panglao_gs_prediction_signif <- panglao_gs_prediction
  }else{
    panglao_gs_prediction_signif <- ifelse(apply(HGT_panglao_gs, 2, max)>2, yes = panglao_gs_prediction, "unassigned")
  }
  data$gs_prediction <- panglao_gs_prediction_signif
  # return
  return(data)
}
# CelliD Visablity
CelliDVisablity <- function(data,scRNAref,reduce,panglao_gs){
  require(patchwork)
  require(ggplot2)
  # get subtitle 
  if (scRNAref == "Cellmarker"){
    subtitle = paste0("Reference scRNA-seq gene set : CellMarker 2.0")
  }else{
    if (scRNAref == "PanglaoDB"){
      subtitle = paste0("Reference scRNA-seq gene set : PanglaoDB")
    }
  }
  # Add warring infor
  if (max(sapply(panglao_gs, length)) < 10){
    subtitle = paste0("CelliD annotation results are unreliable","\n",subtitle)
  }else{
    subtitle = subtitle
  }
  data$gs_prediction <- factor(data$gs_prediction)
  colour[which(levels(data$gs_prediction) == "unassigned")] <- "#AEC6CF"
  p1 <- DimPlot(data,reduction =reduce,cols = colour,label = T)
  p2 <- DimPlot(data,reduction =reduce,cols = colour,
                group.by = "gs_prediction") + ggtitle(paste0("Annotation Power by ",scRNAref)) + labs(subtitle = subtitle)+
    theme(plot.subtitle = element_text(hjust = 0.5,colour = "blue"))
  # fix ggplot2
  if (max(sapply(panglao_gs, length)) < 10){
    p2 <- p2 + theme(plot.subtitle = element_text(hjust = 0.5,colour = "red"))
  }else{
    p2 <- p2
  }
  # fix ggplot2
  all <- p1 + p2 + patchwork::plot_layout(ncol = 1)
  return(all)
}
# CelliD one scripts
CelliDAnnotationpipeline <- function(scData,scRNAref,organ,species,root_dir,reduce,
                                     Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref){
  # Loading packages
  require(CelliD)
  require(Seurat)
  require(SingleCellExperiment)
  require(patchwork)
  require(ggplot2)
  # scRNAref = 'Cellmarker'
  # organ = 'Blood'
  # species = 'Hs'
  # data = data$JoinLayers
  # Seurat 2 SingleCellExperiment
  info(logger, 'Seurat -> SingleCellExperiment ')
  SingleCell <- as.SingleCellExperiment(scData)
  # run MCA for SingleCellExperiment
  info(logger, 'CelliD runMCA')
  SingleCell <- CelliD::RunMCA(SingleCell,
                                 nmcs = 30,
                                 reduction.name = "MCA")
  pathways <- AnnGeneSet(scRNAref,organ,species,Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref)
  # SingleCellExperiment enrichment
  info(logger, 'check Cellmarker & panglao Anno')
  HGT_panglao_gs <- checkCellmarkerAnno(SingleCell,scRNAref,organ,species,Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref,pathways)
  # ada annotation for SingleCellExperiment
  info(logger, 'CelliD Annotation')
  scData <- CelliDAnnotation(scData,HGT_panglao_gs,pathways)
  scData$gs_prediction <- as.character(scData$gs_prediction)
  scData$gs_prediction[is.na(scData$gs_prediction)] <- "Unknown"
  scData$gs_prediction <- iconv(scData$gs_prediction, to = "UTF-8")
  # DimPlot_scCustom(scData,group.by = 'gs_prediction',reduction = 'umap.cca')
  # reduce <- 'umap.cca'
  info(logger, 'CelliD Annotation Visablity')
  all <- CelliDVisablity(scData,scRNAref,reduce,pathways)
  ggsave(plot = all,file.path(root_dir,paste0(organ,"-",species,"-",scRNAref,"-CelliD-Annotation.pdf")),width = 13,height = 10)
  ggsave(plot = all,file.path(root_dir,paste0(organ,"-",species,"-",scRNAref,"-CelliD-Annotation.png")),width = 13,height = 10,dpi = 1000)
  return(scData)
}
# CelliD one scripts
CelliDAnnotationpipeline_scRNA <- function(SingleData,scRNAref,organ,species,intergetmethods,
                                           Seuratname,annotation_CelliD_dir,
                                           Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref){
  # Loading packages
  require(CelliD)
  require(ggplot2)
  require(Seurat)
  # check log models                       
  Check_log_models()
  # auto annotation for redim methods
  if (intergetmethods %in% c('CCA','ALL')){
    CelliDData <- CelliDAnnotationpipeline(SingleData,scRNAref,organ,species,
                                           annotation_CelliD_dir,"umap.cca",
                                           Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref)
  }else{
    if (intergetmethods %in% c('Harmony')){
      CelliDData <- CelliDAnnotationpipeline(SingleData,scRNAref,organ,species,
                                             annotation_CelliD_dir,"umap.harmony",
                                             Cellmarker_Humanref,Cellmarker_Mouseref,PanglaoDB_ref)
    }
  }
  return(CelliDData)
}
# ==============================================================================
# END 
# ==============================================================================