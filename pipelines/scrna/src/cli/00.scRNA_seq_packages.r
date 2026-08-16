# ---------------------------------------------- #
# CheckPackage function
CheckPackage <- function(needlist){
  packagelist <- as.data.frame(installed.packages())
  if (all(needlist %in% packagelist$Package) == T){
    info(logger,'  scRNA-seq Analysis depend package have intsll')
  }else{
    warn(logger, "  scRNA-seq Analysis depend package don't all intsll")
    print_color_note(paste0("Not install R package : ",needlist[which((needlist %in% packagelist$Package)==F)]))
    stop()
  }
}
# ---------------------------------------------- #
# set scRNA-seq analysis pacjage
needlist <- c("SeuratWrappers","harmony","Seurat","HGNChelper","scCustomize","SingleR",
              "homologene","celldex","parallel","patchwork","stringr","crayon","praise",
              "progress","ggplot2","ggpubr","clustree","ggplotify","dplyr","tidyverse",
              "cowplot","uwot","ggrepel","decontX",'qs','zellkonverter')
# ---------------------------------------------- #
# loading scRNA-seq R Packages
info(logger,'  loading qs package')
suppressMessages(library("qs"))
info(logger,'  loading dplyr package')
suppressMessages(library("dplyr"))
info(logger,'  loading scater package')
suppressMessages(library("scater"))
info(logger,'  loading Seurat package')
suppressMessages(library("Seurat"))
info(logger,'  loading HGNChelper package')
suppressMessages(library("HGNChelper"))
info(logger,'  loading scCustomize package')
suppressMessages(library("scCustomize"))
info(logger,'  loading SingleR package')
suppressMessages(library("SingleR"))
info(logger,'  loading patchwork package')
suppressMessages(library("patchwork"))
info(logger,'  loading stringr package')
suppressMessages(library("stringr"))
info(logger,'  loading crayon package')
suppressMessages(library("crayon"))
info(logger,'  loading praise package')
suppressMessages(library("praise"))
info(logger,'  loading progress package')
suppressMessages(library("progress"))
info(logger,'  loading ggplot2 package')
suppressMessages(library("ggplot2"))
info(logger,'  loading homologene package')
suppressMessages(library("homologene"))
info(logger,'  loading celldex package')
suppressMessages(library("celldex"))
info(logger,'  loading ggpubr package')
suppressMessages(library("ggpubr"))
info(logger,'  loading ggrepel package')
suppressMessages(library("ggrepel"))
info(logger,'  loading parallel package')
suppressMessages(library("parallel"))
info(logger,'  loading clustree package')
suppressMessages(library("clustree"))
info(logger,'  loading gtools package')
suppressMessages(library("gtools"))
info(logger,'  loading cowplot package')
suppressMessages(library("cowplot"))
info(logger,'  loading lubridate package')
suppressMessages(library("lubridate"))
info(logger,'  loading patchwork package')
suppressMessages(library("patchwork"))
info(logger,'  loading uwot package')
suppressMessages(library("uwot"))
info(logger,'  loading viridis package')
suppressMessages(library("viridis"))
info(logger,'  loading decontX package')
suppressMessages(library("decontX"))
info(logger,'  loading tidyverse package')
suppressMessages(library("tidyverse"))
info(logger,'  loading tools package')
suppressMessages(library("tools"))
info(logger,'  loading data.table package')
suppressMessages(library("data.table"))
info(logger,'  loading sommer package')
suppressMessages(library("sommer"))
info(logger,'  loading BiocParallel package')
suppressMessages(library("BiocParallel"))
info(logger,'  loading pander package')
suppressMessages(library("pander"))
info(logger,'  loading DoubletFinder package')
suppressMessages(library("DoubletFinder"))
info(logger,'  loading zellkonverter package')
suppressMessages(library("zellkonverter"))
# ---------------------------------------------- #
# Check scRNA-SEQ Package INSTLL
CheckPackage(needlist)
# ==============================================================================
# END 
# ==============================================================================