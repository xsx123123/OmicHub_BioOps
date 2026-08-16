# Author : zhang jian
# date :  2024.10.28
# version : 1.0v
######################
# Description : SingleSampleSubClusterRereduction function is Single scRNA-seq Sample subcluter 
#               rRereduction function
#               SingleSampleSubClusterRereduction function can auto setting reduction PCA cutoff
######################
log4r_init <- function(){
  require(log4r)
  logger <- log4r::logger()
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
  logger <- log4r::logger(threshold = "INFO",appenders = list(console_appender(my_layout)))
  return(logger)
}
######################
AutoSettingPcCutoff <- function(data,plot_name,save_dir){
  # data <- sce
  # auto set pc cutoff
  # Determine percent of variation associated with each PC
  # Determine percent of variation associated with each PC
  pct <- data[["pca"]]@stdev / sum(data[["pca"]]@stdev) * 100
  # Calculate cumulative percents for each PC
  cumu <- cumsum(pct)
  # Determine which PC exhibits cumulative percent greater than 90% and % variation associated with the PC as less than 5
  co1 <- which(cumu > 90 & pct < 5)[1]
  # Determine the difference between variation of PC and subsequent PC
  co2 <- sort(which((pct[1:length(pct) - 1] - pct[2:length(pct)]) > 0.1), decreasing = T)[1] + 1
  # last point where change of % of variation is more than 0.1%.
  pcs <- max(co1, co2)
  # Create a dataframe with values
  plot_df <- data.frame(pct = pct,
                        cumu = cumu,
                        rank = 1:length(pct))
  # Elbow plot to visualize
  p3 <- ggplot(plot_df, aes(cumu, pct, label = rank, color = rank > pcs)) +
    ggtitle(paste0(plot_name," PCA Elbow Plot"))+
    xlab("CUMU")+
    ylab("PCT")+
    geom_text(size=3) +
    geom_vline(xintercept = subset(plot_df,plot_df$rank==pcs)$cumu,
               color = "blue",linetype="dashed") +
    theme_classic()+
    theme(plot.title = element_text(hjust = 0.5),
          legend.position = "none",
          legend.title = element_text(size = 15,face = "normal"),
          text = element_text(size = 9,family="sans"),
          axis.title.x = element_text(size = 7),
          axis.title.y = element_text(size = 7),
          axis.text.x = element_text(size = 5),
          axis.text.y = element_text(size = 5),
          axis.line.x=element_line(linetype=1,color="black",linewidth=0.3),
          axis.line.y=element_line(linetype=1,color="black",linewidth=0.3),
          axis.ticks.x=element_line(color="black",linewidth=0.3,lineend = 1),
          axis.ticks.y=element_line(color="black",linewidth=0.3,lineend = 1))
  # save plot
  ggsave(file.path(save_dir,paste0(plot_name,"-PCT-ElbowPlot.pdf")),width = 7,height = 3.5,device = "pdf",plot = p3)
  ggsave(file.path(save_dir,paste0(plot_name,"-pct-ElbowPlot.png")),width = 7,height = 3.5,device = "png",plot = p3,dpi=1000)
  #
  info(logger,paste0("Calculation PCA Cutoff is : ",pcs))
  # print_color_note(paste0("Calculation PCA Cutoff is : ",pcs))
  # return
  return(pcs)
}
######################
SingleSampleSubClusterRereduction <- function(Seurat = scData,
                                              AutoSettingPcCutoff_plot_name = 'AutoSettingPcCutoff',
                                              normalization.method =  "LogNormalize",
                                              scale.factor = 1e4,
                                              selection.method = "vst",
                                              nfeatures = 2000,
                                              resolution = 1.2,
                                              save_dir = './'
){
  require(Seurat)
  logger <- log4r_init()
  info(logger,'Create New SeuratObject')
  sce=CreateSeuratObject(counts = Seurat@assays$RNA$counts,
                         meta.data = Seurat@meta.data)
  # normalization
  info(logger,'NormalizeData SeuratObject')
  sce <- NormalizeData(sce, normalization.method =  normalization.method,  
                       scale.factor = scale.factor)
  # select HVG gene
  info(logger,'FindVariableFeatures')
  sce <- FindVariableFeatures(sce,selection.method = selection.method, nfeatures = nfeatures) 
  # scale
  info(logger,'ScaleData')
  sce <- ScaleData(sce) 
  # PCA
  info(logger,'RunPCA')
  sce <- RunPCA(object = sce, pc.genes = VariableFeatures(sce))
  # AutoSettingPcCutoff
  info(logger,'AutoSettingPcCutoff')
  pct <- AutoSettingPcCutoff(sce,
                             AutoSettingPcCutoff_plot_name,
                             save_dir)
  # find Neighbors & Clusters
  info(logger,'find Neighbors & Clusters')
  sce <- FindNeighbors(sce, dims = 1:pct)
  sce <- FindClusters(sce, resolution = resolution)
  # UMAP
  info(logger,'RunUMAP')
  sce <- RunUMAP(object = sce, dims = 1:pct, do.fast = TRUE)
  return(sce)
}