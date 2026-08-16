# find seurat clutster marker powered by FindAllMarkers
# FindAllTopMarker version : 1.0v
# FindAllTopMarker & extert marker by suite cutoff
FindAllTopMarker <- function(Seurat = Data,
                             group_by = 'seurat_clusters',
                             logfc.threshold = log(2),
                             top_n = 15,
                             pct_diff = 0.25,
                             p_val_cutoff = 0.05){
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
  Idents(Seurat) <- Seurat@meta.data[[group_by]]
  all_Markers <- FindAllMarkers(Seurat,logfc.threshold = logfc.threshold)
  Markers <- all_Markers |> scCustomize::Add_Pct_Diff() |> dplyr::filter(pct.1 > pct_diff) 
  Top_Marker <- data_frame()
  Markers$cluster <- factor(Markers$cluster)
  logger <- log4r_init()
  for (i in levels(Markers$cluster)){
    info(logger,paste0('Extert ',i, " Cluster Top Marker"))
    # i = '0'
    Extert <- Markers |> dplyr::filter(cluster == i)
    Extert <- Extert |> dplyr::arrange(-avg_log2FC) |> dplyr::filter(p_val < p_val_cutoff) |> dplyr::slice_head(n = top_n)
    Top_Marker <- rbind(Top_Marker,Extert)
  }
  return(Top_Marker)
}
# Calculation Everyone Cluster TOP marker
Top_Marker <-  FindAllTopMarker(Seurat = Data,group_by = 'seurat_clusters')
write.csv(Top_Marker,file.path(save_dir,'Top_marker.csv'))