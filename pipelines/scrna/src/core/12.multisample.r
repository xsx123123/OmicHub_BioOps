# ==============================================================================
# Multi-Sample scRNA-seq Analysis Pipeline
# Author: zhang jian
# Description: Main workflow for integrating multiple scRNA-seq samples.
#              QC -> Integration (CCA/Harmony/RPCA/MNN) -> Clustering -> Annotation.
# ==============================================================================
multisample_scRNA_seq_analysis <- function(ctx,
                                           normalization_method = "LogNormalize"){
  
  # Unpack Context
  list2env(ctx, envir = environment())

  # 1. Input & QC
  # Using DNBC4_10X to load all samples at once.
  # Returns a list of Seurat objects (one per sample).
  info(logger, '  Loading samples and performing QC...')

  # Create samples & group info
  group_data <- cellRangerlist_dataframe |> dplyr::select(c(name,group))
  cellRangerlist <- ctx$cellRangerlist_dataframe$CellRanger
  names(cellRangerlist) <- ctx$cellRangerlist_dataframe$name
  infor <- data.frame(infor = ctx$cellRangerlist_dataframe$name, 
                      group = ctx$cellRangerlist_dataframe$group)

  # 'list' variable comes from global config/parameter.r
  Seurat_list <- DNBC4_10X(scRNAtype = ctx$scRNAtype,scRNAAutofilted = scRNAAutofilted,
                           cellRangerlist,group_data,Cellranger_dir,origin_tax_ID,
                           cellRangerlist_dataframe = ctx$cellRangerlist_dataframe)
  
  # Write QC summary
  qc_summary_data <- build_qc_summary(Cellranger_dir, ctx$cellRangerlist_dataframe)
  write_step_summary("qc", qc_summary_data, Cellranger_dir)

  # 2. Doublet Detection (Per Sample)
  # Run DoubletFinder BEFORE integration on individual samples
  info(logger, '  Running DoubletFinder on individual samples...')
  Seurat_list <- Checkdoublet(Seurat_list,
                              num.cores = NULL,
                              sct_doubletFinder = FALSE,
                              save_dir = doublet_dir)


  debug(logger, '  Saving Seurat_list_Doublet by qs package (so fast as possible)')
  qs::qsave(Seurat_list, file.path(doublet_dir, "Seurat_list_Doublet.qs"))

  info(logger,'  Draw Doublet Plot ... ')
  DoubletPlot(Seurat_list,ctx$doublet_dir)
  write_step_summary("doublet", list(
    samples = list(),
    metrics = list(),
    artifacts = list(list(type = "dir", path = "QC/doublet"))
  ), ctx$doublet_dir)

  # 3. Merge for Initial Check (Optional but good for Batch Effect viz)
  # Merge raw counts to check batch effect before correction
  info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  info(logger, crayon::bold(crayon::inverse(">>> STEP 9: Merging samples")))
  info(logger, '  Merging samples for batch effect check...')
  # Merge_Seurat_List is likely a helper, but Seurat::merge works too
  # Assuming 'project_name' is global
  debug(logger, paste0('  Merging ',names(Seurat_list),'samples'))
  merged_obj <- merge(x = Seurat_list[[1]],
                      y = Seurat_list[-1],
                      add.cell.ids = names(Seurat_list),
                      project = ctx$project_name)
  # Standardize v5 layers
  merged_obj <- JoinLayers(merged_obj)
  # SplitObject data by orig.ident
  PatchDeallist <- SplitObject(merged_obj, split.by = "orig.ident")
  # NormalFeature
  sclist <- NormalFeature(PatchDeallist)
  # merge seurat object
  merge <- scCustomize::Merge_Seurat_List(sclist,add.cell.ids = NULL,merge.data = TRUE,project = ctx$project_name)
  merge <- JoinLayers(merge)
  # save merge data
  qs::qsave(merge, file.path(ctx$output_dir, "scrna_seq_merge.qs"))
  # check Batch
  info(logger, '  Check multisample scRNA-seq Batch effect')
  merge <- MergeSeuratObjectBatchCheck(merge,ctx$BatchCheck_dir,
                                       resolution = 0.8,scale_factor = 10000,
                                       normalization_method = 'LogNormalize',
                                       selection_method = 'vst',
                                       nfeatures = 2000)
  write_step_summary("batch_check", list(
    samples = list(),
    metrics = list(),
    artifacts = list(list(type = "dir", path = "BatchCheck"))
  ), ctx$BatchCheck_dir)
  all_project <- CreateNewSeurat(merge)
  # 4. Integration
  # We use the optimized 'IntergetPatch' (renamed/refactored logic)
  # Input: merged object. The function will handle Splitting, Normalization (SCT/Log), and Integration.
  info(logger, paste0('  Running Integration... Method: ', ctx$intergetmethods, ' | Normalization: ', normalization_method))
  
  # Note: IntergetPatch expects the merged object.
  # It calls PrepareIntegration -> Split -> Normalize -> IntegrateLayers
  info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  info(logger, crayon::bold(crayon::inverse(">>> STEP 10 : Integration multisample scRNA-seq data")))
  info(logger, paste0('  Integration multisample scRNA-seq data DealPatchmethod :',ctx$intergetmethods,' Resolute : ',1.2,' k.weight : ',100))
  integrated_data <-  IntergetPatch(all_project,DealPatch_dir,
                                    DealPatchmethod = ctx$intergetmethods,
                                    Resolute = 1.2,k.weight = 100,reduceType = ctx$reduceType,
                                    scvi_path = scvi_path_conda)
  # Result is a list: Origin (v5 split layers) and JoinLayers (merged)
  integrated_obj <- integrated_data$Origin
  info(logger, crayon::blue(crayon::bold('  join layers for integrated seurat data')))
  integrated_obj <- JoinLayers(integrated_obj, assay = "RNA")
  # Save Checkpoint
  qs::qsave(integrated_obj, file.path(ctx$doublet_dir, "scrna_seq_integrated.rds"))
  write_step_summary("integration", list(
    samples = list(),
    metrics = list(integration_method = ctx$intergetmethods),
    artifacts = list(
      list(type = "dir", path = "DealPatch"),
      list(type = "rds", path = "QC/doublet/scrna_seq_integrated.rds")
    )
  ), ctx$DealPatch_dir)
  # 5. Ambient RNA (DecontX)
  # Usually DecontX runs on raw counts. We can run it on the integrated object's RNA assay.
  info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  info(logger, crayon::bold(crayon::inverse(">>> STEP 11 : Detect Ambient RNA by DecontX")))
  info(logger, '  Estimating Ambient RNA...')
  integrated_obj <- AmbientRNAContamination(integrated_obj, ctx$RNAContamination_dir)
  DrawAmbientRNAContamination_UMAP(integrated_obj,
                                   ctx$RNAContamination_dir,
                                   ctx$intergetmethods)
  invisible(gc(verbose = FALSE))
  info(logger, '  Freed memory after Ambient RNA analysis.')
  write_step_summary("ambient_rna", list(
    samples = list(),
    metrics = list(),
    artifacts = list(
      list(type = "qs", path = file.path("QC/RNAContamination", paste0(ctx$project_name, "_decontX_results.qs"))),
      list(type = "png", path = "QC/RNAContamination/AmbientRNAContamination.png")
    )
  ), ctx$RNAContamination_dir)
  # 6. Visualization & Stats
  info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  info(logger, crayon::bold(crayon::inverse(">>> STEP 12 : draw UMAP/tSNE for Integrated object")))
  # UMAP/tSNE already computed in IntergetPatch
  draw_umap_tsne_plot(integrated_obj, reduceType = ctx$reduceType, 
                      intergetmethods = ctx$intergetmethods, 
                      name = 'Integrated', figure_dir = ctx$figure_dir)
  StatCellCluster(integrated_obj, output_dir)
  
  # 7. Marker Genes
  info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  info(logger, crayon::bold(crayon::inverse(">>> STEP 13 : Finding Cluster Markers gene")))
  # Use default assay (RNA or SCT) or specific 'integrated' data if needed?
  # FindMarkers usually needs 'data' slot.
  # For v5 integration, we should JoinLayers before DE if we want to test on corrected data (or raw data).
  # Best practice: DE on RNA counts/data (JoinLayers needed), Cluster on Integrated reduction.
  
  # Ensure layers are joined for DE
  integrated_obj <- JoinLayers(integrated_obj)


  info(logger, '  FindClusterMarkers for scRNA-seq (wilcox)')
  FindClusterMarkers(integrated_obj,
                     intergetmethods = ctx$intergetmethods,
                     save_dir = ctx$cluster_marker_gene_dir,
                     test = "wilcox",
                     topgene = 30)

  info(logger, '  FindClusterMarkersDotplot for scRNA-seq')

  draw_res_DimPlot(integrated_obj, 
                 intergetmethods = ctx$intergetmethods,
                 ctx$figure_dir,
                 ctx$cluster_marker_gene_dir)
  write_step_summary("cluster_markers", list(
    samples = list(),
    metrics = list(),
    artifacts = list(
      list(type = "dir", path = "cluster/marker_gene"),
      list(type = "dir", path = "cluster/UMAP-plot"),
      list(type = "dir", path = "cluster/tSNE-plot")
    )
  ), ctx$cluster_marker_gene_dir)

  # 8. Annotation
  if(origin_tax_ID %in% c(9606, 10090)){
    info(logger, '  Running Automated Annotation (SingleR)...')
    # cella Level
    integrated_obj <- RunSingleR_Unified(integrated_obj, origin_tax_ID, annotation_SinglR_dir, level = "cell")
    # Cluster Level
    integrated_obj <- RunSingleR_Unified(integrated_obj, origin_tax_ID, annotation_SinglR_dir, level = "cluster")
    # save annotated integrated data
    # qs::qsave(integrated_obj, file.path(annotation_SinglR_dir, "scrna_seq_integrated_annotated.qs"))
    # Visualize SingleR
    # Assuming standard fields like 'SingleR_ImmGen_cluster' exist now
    # Check what was generated and plot
    meta_cols <- colnames(integrated_obj@meta.data)
    singler_cols <- grep("SingleR_.*_cluster", meta_cols, value = TRUE)
    # Map integration method to the UMAP reduction name produced by IntergetPatch
    umap_reduction <- switch(intergetmethods,
                             "CCA"   = "umap.cca",
                             "Harmony" = "umap.harmony",
                             "RPCA"  = "umap.rpca",
                             "ALL"   = "umap.cca",  # CCA is the primary/default result
                             "SCVI"  = "umap.scvi",
                             "umap")
    for(col in singler_cols){
      info(logger, paste0("  Drawing SingleR annotation for: ", col))
      VisualizeAnnotation(integrated_obj, group_by = col, save_dir = annotation_SinglR_dir,
                          prefix = "Integrated", reduction = umap_reduction)
    }
    
  } else {
    info(logger, paste0("  Skipping SingleR for TaxID: ", origin_tax_ID))
  }
  
  write_step_summary("annotation", list(
    samples = list(),
    metrics = list(),
    artifacts = list(
      list(type = "dir", path = "annotation/auto-annotation-SinglR"),
      list(type = "dir", path = "annotation/proportions-plot")
    )
  ), ctx$annotation_dir)
  
  # Write report JSON for the Quarto report. This rescans final outputs so
  # the report captures plots, tables, object files, and cell metadata written by all steps.
  result_root <- file.path(ctx$root_dir, ctx$save_output_name)
  generate_report_json(
    result_dir = result_root,
    project_name = ctx$project_name,
    species_tax_id = ctx$origin_tax_ID,
    integration_method = ctx$intergetmethods,
    pipeline_version = if (exists("ScriptsVersion")) ScriptsVersion else "unknown"
  )
  
  # info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
  # info(logger, crayon::bold(crayon::inverse(">>> STEP 14 : Seurat format to Annodata")))
  # Seurat2h5ad(Seurat_obj = integrated_obj,
  #             project_name = ctx$project_name,
  #             save_dir = ctx$output_dir,assay_to_use = "RNA",
  #             logger = logger)

  # info(logger, '  >>> Multi-Sample Analysis Complete. 🎉🎉🎉')
}
# ==============================================================================
# END 
# ==============================================================================
