Robustness_analysis <- function(seurat,
                                pair = c('Control', 'Treate'),
                                celltype = 'celltype_main',
                                group = 'group',
                                name = 'Robustness_analysis',
                                output_dir = "./") {  # Output file name
  
  org_status <- unique(data.frame(organoid = seurat$orig.ident,
                                  status = factor(seurat@meta.data$`group`, levels = pair)))
  org_status <- setNames(org_status$status, org_status$organoid)
  number <- length(levels(seurat@meta.data$`celltype`))
  
  # Open a PNG device to save the combined plot
  png(file.path(output_dir,paste0(name,'-barplot.png')), width = 14,
      height = 3.5,
      units = "in",
      res = 700)  # Set the output file and size
  # Set up the layout for multiple plots (e.g., arrange them in 1 row, number of columns based on the number of regions)
  par(mfrow = c(1, number), mar = c(5, 4, 4, 1))  # Adjust margins to avoid overlap
  
  for(region in levels(seurat@meta.data$`celltype`)){
    props <- setNames(sapply(sort(unique(seurat$orig.ident)), function(orig.ident)
      mean(seurat@meta.data$`celltype`[seurat$orig.ident == orig.ident] == region)),
      sort(unique(seurat$orig.ident)))
    
    # Create the barplot
    barplot(props[order(props)],
            col = ifelse(org_status[names(props)[order(props)]] == pair[1], "#cdcdcd", "#303030"),
            ylab = "Proportions", main = region, las = 2, cex.names = 0.8)
  }
  # Close the file device to save the plot
  dev.off()
}