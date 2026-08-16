# author : zhang jian
# date : 2024.10.10
# version :  1.1v
# description : this is patch celltype levels deg scripts
#
# === Skill 化修复说明（skills/scrna-tcell-projectils, v0.9.0） ===
# 本文件复制自 tools/immune_annotation/ProjecTIL_Annotation.r，入包时做了以下最小修复，
# 其余逻辑与函数签名保持不变：
#   [FIX-1] ProjecTILs.classifier.pipeline: 日志语句引用了未定义变量 UseCore（运行必报错），
#           改为使用函数参数 cores。
#   [FIX-2] ProjecTILs.classifier.pipeline: 调用 FindClusterMarkersDotplot 时写死 save_dir='./'
#           （会写到 CWD 而非输出目录），改为继承外层 save_dir 参数。
#   [FIX-3] ProplotDimPlot: DimPlot_scCustom 内 reduction 硬编码为 'umap.harmony'
#           （输入对象无 harmony 降维时失败），改为新增函数参数 reduction（默认 'umap'）。
##### parameter
# log4r logger function
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
# Check_Seurat_version for ProjecTILs annotation
# @Query : Seurat object
Check_Seurat_version <- function(Query){
  if (grepl('^5.',Query@version) == T){
    cat('Convert Seurat v5 -> Seurat v3\n')
    Query[["RNA"]] <- as(object = Query[["RNA"]], Class = "Assay")
  }else{
    Query <-  Query
  }
  return(Query)
}
# ProjecTILs.classifier.pipeline
# @ scData : Seurat object
# @ ref    : ProjecTILs annotation reference
# @ name   : project ID
# @ reduction : Seurat object reduction tag
# @ cores     : Number of cores for parallel processing
# @ colors    : draw plot color
# @ save_dir  : ProjecTILs annotation save path
ProjecTILs.classifier.pipeline <- function(scData,ref,name,reduction = 'umap',cores = 20,
                                           colors = NULL,save_dir = './'){
  require(scCustomize)
  require(ProjecTILs)
  require(Seurat)
  if (is.null(colors)){
    my36colors <-c('#E5D2DD', '#53A85F', '#F1BB72', '#F3B1A0', '#D6E7A3', '#57C3F3', '#476D87',
                   '#E95C59', '#E59CC4', '#AB3282', '#23452F', '#BD956A', '#8C549C', '#585658',
                   '#9FA3A8', '#E0D4CA', '#5F3D69', '#C5DEBA', '#58A4C3', '#E4C755', '#F7F398',
                   '#AA9A59', '#E63863', '#E39A35', '#C1E6F3', '#6778AE', '#91D0BE', '#B53E2B',
                   '#712820', '#DCC1DD', '#CCE0F5',  '#CCC9E6', '#625D9E', '#68A180', '#3A6963',
                   '#968175')
    colors <- my36colors
  }else{
    colors <- colors
  }
  logger <- log4r_init()
  # Check_Seurat_version
  Query <- Check_Seurat_version(scData)
  # ProjecTILs.classifier
  # [FIX-1] 原脚本此处引用未定义变量 UseCore，运行必报错；改为函数参数 cores
  info(logger, paste0('ProjecTILs.classifier power by ',cores,' Core'))
  info(logger, 'Run ProjecTILs.classifier (Only Switch CellType Lables)')
  query.projected <- ProjecTILs.classifier(query = Query,
                                           ncores = cores,
                                           filter.cells = F,
                                           ref = ref)
  info(logger, 'Save Run ProjecTILs.classifie Annotation result ')
  saveRDS(query.projected,file.path(save_dir,paste0('ProjecTILs.classifier-',name,'-annotation.rds')))
  info(logger, 'Visablity Run ProjecTILs.classifie Annotation result ')
  # Visablity
  p <- DimPlot_scCustom(query.projected,group.by = 'functional.cluster',colors_use = colors,
                        reduction = reduction)+
    labs(x = 'UMAP-1',y = 'UMAP-2',title = 'name') +
    guides(color = guide_legend(keywidth = 1, keyheight = 1.25,ncol=1,override.aes = list(size = 5)))
  ggsave(file.path(save_dir,paste0('ProjecTILs.classifier-',name,'-annotation.png')),
         width = 6,height = 3.5,plot = p,dpi = 1000)
  ggsave(file.path(save_dir,paste0('ProjecTILs.classifier-',name,'-annotation.pdf')),
         width = 6,height = 3.5,plot = p)
  print(p)
  # Draw MarkersDotplot
  info(logger, 'FindClusterMarkersDotplot for ProjecTILs.classifie Annotation result ')
  # [FIX-2] 原脚本此处写死 save_dir='./'（markrt_list.csv 会落到 CWD）；改为继承外层 save_dir
  p <- FindClusterMarkersDotplot(query.projected,group_by = 'functional.cluster',
                                 save_dir=save_dir,
                                 test = "wilcox",
                                 color = viridis_plasma_dark_high)
  ggsave(file.path(save_dir,paste0('ProjecTILs.classifier-',name,'-annotation-Dotplot.png')),width = 20,
         height = 10,plot = p,dpi = 1000)
  ggsave(file.path(save_dir,paste0('ProjecTILs.classifier-',name,'-annotation-Dotplot.pdf')),width = 20,
         height = 10,plot = p)
  return(query.projected)
}
# FindClusterMarkersDotplot
# @Seurat           : Seurat object
# @group_by         : Deg group
# @save_dir         : group deg marker save path (dafult : ./)
# @topgene          : dotplot visablity top gene num
# @test             : findmaker test methods  (wilcox | bimod | t | MAST | DESeq2)
# @color            : draw Dotplot color
# @Extert_gene_list : add Extert_gene_list for draw Dotplot
FindClusterMarkersDotplot <-function(Seurat,group_by = 'Celltype',
                                     save_dir='./',
                                     test = "wilcox",
                                     topgene = 5,
                                     color = viridis_plasma_dark_high,
                                     Extert_gene_list = NULL){
  # Version : 1.1.1
  require(scCustomize)
  require(ggplot2)
  require(Seurat)
  # Seurat <- scData
  # group_by <- 'functional.cluster'
  # Extert_gene_list <- Tsubset_list 
  markrt_list <- c()
  Seurat@meta.data$celltype <- Seurat@meta.data[[group_by]]
  for (i in levels(factor(Seurat@meta.data$celltype))){
    # i <- 'Macrophages'
    info(logger, paste0('scRNA-seq Analysis FindMarkers ',i))
    cells1 <- subset(Seurat@meta.data,celltype == i )  |> rownames()
    cells2 <- subset(Seurat@meta.data,celltype != i )  |> rownames()
    temp_marker <-  FindMarkers(Seurat,
                                ident.1 = cells1, 
                                ident.2 = cells2,
                                only.pos = FALSE,
                                logfc.threshold = log(2),
                                test.use = test)
    temp_marker <- temp_marker |> arrange(-avg_log2FC) |> filter(pct.1 > 0.25) |>  dplyr::slice_head(n=topgene)
    markrt_list <- append(markrt_list,rownames(temp_marker))
  }
  markrt_list <- append(markrt_list, Extert_gene_list)
  list <- unlist(markrt_list)
  list <- unique(list)
  write.csv(list,file.path(save_dir,'markrt_list.csv'))
  # viridis_plasma_dark_high ,viridis_plasma_light_high,viridis_magma_dark_high,viridis_magma_light_high
  # viridis_inferno_dark_high,viridis_inferno_light_high,viridis_dark_high,viridis_light_high
  p <- DotPlot_scCustom(seurat_object = Seurat,
                        features = list,
                        group.by = `group_by`,
                        colors_use = viridis_plasma_dark_high) +
    theme(axis.text.x = element_text(angle = 45,vjust=0.9,hjust=0.9))
  return(p)
}
# FindClusterMarkersDotplot & add celltype tag
# @Seurat         : Seurat object
# @group_by       : Deg group
# @save_dir       : group deg marker save path (dafult : ./)
# @topgene        : dotplot visablity top gene num
# @test           : findmaker test methods (wilcox | bimod | t | MAST | DESeq2)
# @dotplot_color  : draw Dotplot color
# @celltype_color : Dotplot celltype color
FindClusterMarkersDotplotaddcelltype <-function(Seurat,group_by = 'Celltype',
                                                save_dir='./',
                                                test = "wilcox",
                                                topgene = 5,
                                                dotplot_color = viridis_plasma_dark_high,
                                                celltype_color = NULL){
  if (is.null(celltype_color)){
    my36colors <-c('#E5D2DD', '#53A85F', '#F1BB72', '#F3B1A0', '#D6E7A3', '#57C3F3', '#476D87',
                   '#E95C59', '#E59CC4', '#AB3282', '#23452F', '#BD956A', '#8C549C', '#585658',
                   '#9FA3A8', '#E0D4CA', '#5F3D69', '#C5DEBA', '#58A4C3', '#E4C755', '#F7F398',
                   '#AA9A59', '#E63863', '#E39A35', '#C1E6F3', '#6778AE', '#91D0BE', '#B53E2B',
                   '#712820', '#DCC1DD', '#CCE0F5',  '#CCC9E6', '#625D9E', '#68A180', '#3A6963',
                   '#968175')
    celltype_color <- my36colors
  }else{
    celltype_color <- celltype_color
  }
  # loading pacakge
  require(scCustomize)
  require(ggplot2)
  require(Seurat)
  # Seurat <- scData_Annotation
  # group_by <- 'functional.cluster'
  # Extert_gene_list <- Tsubset_list 
  markrt_list <- list()
  Seurat@meta.data$celltype <- Seurat@meta.data[[group_by]]
  for (i in levels(factor(Seurat@meta.data$celltype))){
    # i <- 'Th1'
    info(logger, paste0('scRNA-seq Analysis FindMarkers ',i))
    cells1 <- subset(Seurat@meta.data,celltype == i )  |> rownames()
    cells2 <- subset(Seurat@meta.data,celltype != i )  |> rownames()
    temp_marker <-  FindMarkers(Seurat,
                                ident.1 = cells1, 
                                ident.2 = cells2,
                                only.pos = FALSE,
                                logfc.threshold = log(2),
                                test.use = test)
    temp_marker <- temp_marker |> arrange(-avg_log2FC) |> filter(pct.1 > 0.25) |>  dplyr::slice_head(n=topgene) |> rownames()
    names(temp_marker) <- rep(i,topgene)
    markrt_list[[i]] <- temp_marker
  }
  gene_list <- c()
  for( i in c(1:length(markrt_list))){
    # i <- 1
    temp <- markrt_list[[i]]
    gene_list <- append(gene_list,temp)
  }
  unique_indices <- !duplicated(gene_list)
  unique_named_values <- gene_list[unique_indices]
  marker <- data.frame(unique_named_values,
                       group = names(unique_named_values))
  marker$unique_named_values <- fct_reorder(marker$unique_named_values, marker$group)
  write.csv(marker,file.path(save_dir,'markrt_list.csv'),row.names = F)
  # viridis_plasma_dark_high ,viridis_plasma_light_high,viridis_magma_dark_high,viridis_magma_light_high
  # viridis_inferno_dark_high,viridis_inferno_light_high,viridis_dark_high,viridis_light_high
  p <- DotPlot_scCustom(seurat_object = Seurat,
                        features = levels(marker$unique_named_values),
                        group.by = `group_by`,
                        colors_use = dotplot_color,
                        flip_axes = T) +
    theme(axis.text.x = element_text(angle = 45,vjust=0.9,hjust=0.9))
  marker$num =  as.numeric(rownames(marker))
  celltype <- c()
  for ( i in levels(factor(marker$group))){
    # i <- 'CD8_EarlyActiv'
    temp <- marker |>  dplyr::filter(group == i)
    celltype_site <- mean(temp$num) - 0.5
    names(celltype_site) <- i
    celltype <- append(celltype,celltype_site)
  }
  celltype_min <- c()
  for ( i in levels(factor(marker$group))){
    # i <- 'CD8_EarlyActiv'
    temp <- marker |>  dplyr::filter(group == i)
    celltype_site <- min(temp$num) - 0.5
    names(celltype_site) <- i
    celltype_min <- append(celltype_min,celltype_site)
  }
  celltype_max <- c()
  for ( i in levels(factor(marker$group))){
    # i <- 'CD8_EarlyActiv'
    temp <- marker |>  dplyr::filter(group == i)
    celltype_site <- max(temp$num) - 0.1
    names(celltype_site) <- i
    celltype_max <- append(celltype_max,celltype_site)
  }
  df <- data.frame(x = celltype,x_min= celltype_min,x_max = celltype_max,
                   y = rep(0.35,length(levels(factor(marker$group)))), label = c(names(celltype)))
  p1 <- ggplot() +
    geom_text(data = df, aes(x = x, y = y, label = label), size = 4,
              angle = 0,hjust = 0) +
    geom_segment(data = df,aes(x = x_min, xend = x_max, y = 0.3, yend = 0.3,
                               color = label), size = 1) +
    scale_color_manual(values = celltype_color)+
    scale_y_continuous(limits = c(0.3,0.6)) +
    scale_x_continuous(limits = c(0,max(df$x_max)+0.3),
                       expand = c(0,0)) +
    coord_flip() + 
    theme_void() +
    theme(legend.position = 'none')
  all <- p + p1 + patchwork::plot_layout(guides= 'collect',ncol =2,
                                         widths = c(2,1))
  return(all)
}
# stats & draw Seurat celltype propplot
# @data     : Seurat object
# @Celltype : Seurat meta.data Celltype
# @group.by : Seurat meta.data group infor
# @dir      : celltype prop save dir
# @name     : project ID
# @color_list : draw propplot color
Proplot <- function(data,Celltype,
                    group.by,dir,
                    name,color_list = NULL){
  # Proplot 2.0v
  # data <- cs91a108v001_data
  temp <- data@meta.data |> dplyr::select(all_of(c(Celltype, group.by))) 
  colnames(temp)[1] <- 'Celltype'
  temp$Celltype <- as.factor(temp$Celltype)
  list <- levels(temp$Celltype)
  temp$Celltype <- as.character(temp$Celltype)
  colnames(temp)[2] <- 'Group'
  rate_data <- as.data.frame(table(temp$Celltype,temp$Group))
  rate_data$Var1 <- factor(rate_data$Var1,levels = list)
  # convert rate
  rate_data_1 <- data.frame()
  for(i in levels(rate_data$Var2)){
    # i <- 'SC1'
    temp_data <- subset(rate_data,rate_data$Var2==i)
    temp_sum <- sum(temp_data$Freq)
    temp_data$rate <- temp_data$Freq/temp_sum
    rate_data_1 <- rbind(rate_data_1,temp_data)
  }
  # convert %
  rate_data_1$rate <- rate_data_1$rate*100
  # change col name
  colnames(rate_data_1)[1] <- "Cell_cluster_name"
  colnames(rate_data_1)[2] <- "group"
  colnames(rate_data_1)[3] <- "frequently"
  colnames(rate_data_1)[4] <- "rate"
  write.csv(rate_data_1,file.path(dir,paste0(name,'-celltyoe.prop.csv')))
  if (is.null(color_list)) {
    colour1 <- c('#E5D2DD', '#53A85F', '#F1BB72', '#F3B1A0', '#D6E7A3', '#57C3F3', '#476D87',
                 '#E95C59', '#E59CC4', '#AB3282', '#23452F', '#BD956A', '#8C549C', '#585658',
                 '#9FA3A8', '#E0D4CA', '#5F3D69', '#C5DEBA', '#58A4C3', '#E4C755', '#F7F398',
                 '#AA9A59', '#E63863', '#E39A35', '#C1E6F3', '#6778AE', '#91D0BE', '#B53E2B',
                 '#712820', '#DCC1DD', '#CCE0F5',  '#CCC9E6', '#625D9E', '#68A180', '#3A6963',
                 '#968175')
  } else {
    colour1 <- color_list
  }
  p <- rate_data_1 |>
    ggplot(aes(x=group,y=rate,fill=Cell_cluster_name))+
    geom_bar(position = 'stack',stat="identity",width=0.5)+
    labs(x="",y = "Cell cluster frequently (%)",title = )+
    scale_fill_manual(values=colour1) +
    scale_y_continuous(expand = c(0,0),limits = c(0,100)) +
    theme_minimal() +
    guides(fill=guide_legend(ncol=1,title="Cell cluster Type",
                             keywidth = 1, keyheight = 1,
                             override.aes = list(size=0.02,alpha=1)))
  return(p)
}
# Draw Seurat celltype umap & propplot  merge plot
# @scData_Annotation    : Seurat object
# @Celltype : Seurat meta.data Celltype
# @group.by : Seurat meta.data group infor
# @dir      : celltype prop save dir
# @name     : project ID
# @colors   : umap & propplot color
# @reduction: Seurat object reduction tag (default : 'umap')
# [FIX-3] 原脚本 DimPlot_scCustom 内 reduction 硬编码为 'umap.harmony'，输入对象无 harmony
#         降维时必然失败；改为新增函数参数 reduction，默认 'umap'。
ProplotDimPlot <- function(scData_Annotation,Celltype,group.by,save_dir,name,
                           colors = NULL,reduction = 'umap'){
  if (is.null(colors)){
    my36colors <-c('#E5D2DD', '#53A85F', '#F1BB72', '#F3B1A0', '#D6E7A3', '#57C3F3', '#476D87',
                   '#E95C59', '#E59CC4', '#AB3282', '#23452F', '#BD956A', '#8C549C', '#585658',
                   '#9FA3A8', '#E0D4CA', '#5F3D69', '#C5DEBA', '#58A4C3', '#E4C755', '#F7F398',
                   '#AA9A59', '#E63863', '#E39A35', '#C1E6F3', '#6778AE', '#91D0BE', '#B53E2B',
                   '#712820', '#DCC1DD', '#CCE0F5',  '#CCC9E6', '#625D9E', '#68A180', '#3A6963',
                   '#968175')
    colors <- my36colors
  }else{
    colors <- colors
  }
  p <- Proplot(scData_Annotation,Celltype,group.by,save_dir,name,color_list = colors)
  p1 <- DimPlot_scCustom(scData_Annotation,group.by = 'functional.cluster',colors_use = colors,
                         reduction = reduction,pt.size = 0.7)+
    labs(x = 'UMAP-1',y = 'UMAP-2',title = NULL,color = 'CellType') + 
    guides(color = guide_legend(keywidth = 1, keyheight = 1.2,ncol=1,
                                override.aes = list(size = 4)))
  legend <- get_legend(p1)
  p <- p + theme(legend.position = "none")
  p1 <- p1 + theme(legend.position = "none",plot.title = element_blank())
  all <- p1 + p + legend + patchwork::plot_layout(nrow  = 1,widths = c(2,1,1),
                                                  axes = 'collect') + 
    patchwork::plot_annotation(title = name) &
    theme(plot.title = element_text(hjust = 0.5))
  return(all)
}
