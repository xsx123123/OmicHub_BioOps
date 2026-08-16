# ==============================================================================
# Script: Initialize_Project.r
# Description: Handles project setup including parameter extraction, 
#              reference loading, and directory structure creation.
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Extract Global Variables from Options
# ------------------------------------------------------------------------------

# info(logger,crayon::yellow(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
# info(logger, crayon::bold(crayon::inverse(">>> STEP 1: Extracting Global Variables from Options")))

project_name <- opt$projectname
Seuratname <- project_name
origin_tax_ID <- opt$origintaxID
homologene_id <- origin_tax_ID 
scRNAref <-  opt$scRNAref
organ <- opt$organ
species <- Getspecies(origin_tax_ID)
scRNAAutofilted <- opt$autofiltedcell
nFeature_RNA_cutoff_1 <- opt$nFeature_RNA_parameter_min
nFeature_RNA_cutoff_2 <- opt$nFeature_RNA_parameter_max
percent.mt_cutoff <- opt$maxmt
PCs_cutoff  <- opt$PCscutoff
threads <- opt$threads
annotation_reference <- opt$AnnReference
reduceType <- opt$reduceType

# Detailed Debug for Analysis Parameters
if (exists("logger") && logger$threshold == "DEBUG") {
  debug(logger, "  --- Analysis Parameters ---")
  debug(logger, paste0("  project_name          : ", crayon::blue(project_name)))
  debug(logger, paste0("  Seuratname            : ", crayon::blue(Seuratname)))
  debug(logger, paste0("  origin_tax_ID         : ", crayon::blue(origin_tax_ID)))
  debug(logger, paste0("  homologene_id         : ", crayon::blue(homologene_id)))
  debug(logger, paste0("  scRNAref              : ", crayon::blue(scRNAref)))
  debug(logger, paste0("  organ                 : ", crayon::blue(organ)))
  debug(logger, paste0("  species               : ", crayon::blue(species)))
  debug(logger, paste0("  scRNAAutofilted       : ", crayon::blue(scRNAAutofilted)))
  debug(logger, paste0("  nFeature_RNA_min      : ", crayon::blue(nFeature_RNA_cutoff_1)))
  debug(logger, paste0("  nFeature_RNA_max      : ", crayon::blue(nFeature_RNA_cutoff_2)))
  debug(logger, paste0("  percent.mt_cutoff     : ", crayon::blue(percent.mt_cutoff)))
  debug(logger, paste0("  PCs_cutoff            : ", crayon::blue(PCs_cutoff)))
  debug(logger, paste0("  threads               : ", crayon::blue(threads)))
  debug(logger, paste0("  annotation_reference  : ", crayon::blue(annotation_reference)))
  debug(logger, paste0("  reduceType            : ", crayon::blue(reduceType)))
}

# Check pipeline parameter
Check_input_parameter(opt$origintaxID,
                       opt$scRNAref,
                       opt$intergetmethods,
                       opt$AnnReference,
                       opt$reduceType)

# ------------------------------------------------------------------------------
# 2. Load Reference Datasets (Species Specific)
# ------------------------------------------------------------------------------
log_step(logger, 2, "Loading Reference Datasets")
info(logger, paste0('  Loading reference datasets for species: ', species))

ScTypeDB <- file.path(PIPELINE_PATH, yaml$singeler_reference$ScTypeDB)

if (species == "Hs") {
  Cellmarker_Human_dir <- file.path(PIPELINE_PATH, yaml$singeler_reference$Cell_marker_Human)
  Cellmarker_Humanref <- fread(Cellmarker_Human_dir, sep = "\t", header = T, check.names = F)
  if (annotation_reference %in% c("HuamnBlueprintEncode", "HumanDICEImmuneCell", "HumanMonacoImmune", "HumanNovershternHematopoietic", "HumanPrimaryCellAtla")) {
    ref_path <- file.path(PIPELINE_PATH, yaml$singeler_reference[[annotation_reference]])
    assign(annotation_reference, readRDS(ref_path))
    info(logger, paste0('  Loaded SingleR Human Ref: ', annotation_reference))
  }
} else if (species == "Mm") {
  Cellmarker_Mouse_dir <- file.path(PIPELINE_PATH, yaml$singeler_reference$Cell_marker_Mouse)
  Cellmarker_Mouseref <- fread(Cellmarker_Mouse_dir, sep = "\t", header = T, check.names = F)
  if (annotation_reference %in% c("MouseImmGen", "MouseRNA")) {
    ref_path <- file.path(PIPELINE_PATH, yaml$singeler_reference[[annotation_reference]])
    assign(annotation_reference, readRDS(ref_path))
    info(logger, paste0('  Loaded SingleR Mouse Ref: ', annotation_reference))
  }
}

info(logger, paste0('  Loaded SingleR PanglaoDB Ref'))

PanglaoDB_dir <- file.path(PIPELINE_PATH, yaml$singeler_reference$PanglaoDB_markers)
PanglaoDB_ref <- read.table(PanglaoDB_dir, sep = "\t", header = T, check.names = F)

# ------------------------------------------------------------------------------
# 3. Load Analysis Packages
# ------------------------------------------------------------------------------
log_step(logger, 3, "Loading Analysis Packages")
# Check and Load Required Packages
source(file.path(PIPELINE_PATH, yaml$scripts$scRNA_seq_pacaksges))
# ------------------------------------------------------------------------------
# 4. Read Sample Sheet
# ------------------------------------------------------------------------------
log_step(logger, 4, "Reading Sample Sheet")
info(logger, '  Reading scRNA-seq sample sheet...')
cellRangerlist_dataframe <- suppressWarnings(read.table(opt$scRNAseqdataframe, header = T, sep = ","))

# Check if library_type column exists
if (!"library_type" %in% colnames(cellRangerlist_dataframe)) {
  error(logger, "scRNA-seq.conf file must contain 'library_type' column!")
  stop("Error: scRNA-seq.conf file missing library_type column")
}

# Validate each sample's library_type
valid_lib_types <- c("10x", "DNBC4")
invalid_samples <- cellRangerlist_dataframe$name[!cellRangerlist_dataframe$library_type %in% valid_lib_types]
if (length(invalid_samples) > 0) {
  error(logger, paste0("Invalid library_type for samples: ", paste(invalid_samples, collapse = ", ")))
  error(logger, paste0("Valid library types are: ", paste(valid_lib_types, collapse = " | ")))
  stop("Error: Invalid library_type in scRNA-seq.conf")
}

info(logger, '  scRNA-seq sample sheet ')
cat("\n")
print(tibble::as_tibble(cellRangerlist_dataframe))
cat("\n")
# sample & group info extert form sample sheet
list <- cellRangerlist_dataframe$CellRanger
names(list) <- cellRangerlist_dataframe$name
infor <- data.frame(infor = cellRangerlist_dataframe$name, 
                    group = cellRangerlist_dataframe$group,
                    library_type = cellRangerlist_dataframe$library_type)
# ------------------------------------------------------------------------------
# 5. Create Directory Structure
# ------------------------------------------------------------------------------
log_step(logger, 5, "Creating Directory Structure")
root_dir <- check_path(opt$outputdir)
save_output_name <- paste0(project_name, "-scRNA-seq-result")
SeuratResDir <- create_scRNA_dir(root_dir, save_output_name)
info(logger, '  scRNA-seq Analysis result directory structure: ')
cat('\n')
print_tree(file.path(root_dir,save_output_name))
cat('\n')
# ------------------------------------------------------------------------------
# 6. Global Directory Assignments
# ------------------------------------------------------------------------------
# info(logger,crayon::blue(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<')))
# info(logger, crayon::bold(crayon::inverse(">>> STEP 6: Assigning Global Directory Variables")))
save_dir <- SeuratResDir@save_dir
output_dir <- SeuratResDir@output_dir
figure_dir <- SeuratResDir@figure_dir
BatchCheck_dir <- SeuratResDir@BatchCheck_dir
DealPatch_dir <- SeuratResDir@DealPatch_dir
qc_dir <- SeuratResDir@qc_dir
Cellranger_dir <- SeuratResDir@Cellranger_dir
RNAContamination_dir <- SeuratResDir@RNAContamination_dir
doublet_dir <- SeuratResDir@doublet_dir
cluster_dir <- SeuratResDir@cluster_dir
UMAP_dir <- SeuratResDir@UMAP_dir
tsne_dir <- SeuratResDir@tsne_dir
cluster_marker_gene_dir <- SeuratResDir@cluster_marker_gene_dir 
DoHeatmap_dir <- SeuratResDir@DoHeatmap_dir
DotPlot_dir <- SeuratResDir@DotPlot_dir 
subset_cell_cluster <- SeuratResDir@subset_cell_cluster
annotation_dir <- SeuratResDir@annotation_dir
annotation_SinglR_dir <- SeuratResDir@annotation_SinglR_dir
annotation_CellID_dir <- SeuratResDir@annotation_CellID_dir
# manual_annotation_figure_dir <- SeuratResDir@manual_annotation_figure_dir
proportions_dir <- SeuratResDir@proportions_dir
marker_gene_output_dir <- SeuratResDir@marker_gene_output_dir
deg_figure_dir <-  SeuratResDir@deg_figure_dir
# ------------------------------------------------------------------------------
# 7. Pack Run Context
# ------------------------------------------------------------------------------
log_step(logger, 6, "Packing Run_Context")

info(logger,'  Create Run_Context for pipeline execution. ')

Run_Context <- list(
  # Global Configs
  project_name = project_name,
  Seuratname = Seuratname,
  origin_tax_ID = origin_tax_ID,
  homologene_id = homologene_id,
  scRNAref = scRNAref,
  organ = organ,
  species = species,
  scRNAAutofilted = scRNAAutofilted,
  nFeature_RNA_cutoff_1 = nFeature_RNA_cutoff_1,
  nFeature_RNA_cutoff_2 = nFeature_RNA_cutoff_2,
  percent.mt_cutoff = percent.mt_cutoff,
  PCs_cutoff = PCs_cutoff,
  threads = threads,
  annotation_reference = annotation_reference,
  reduceType = reduceType,
  intergetmethods = opt$intergetmethods,
  scvi_path = scvi_path_conda,
  
  # Sample Data
  list = list,
  infor = infor,
  cellRangerlist_dataframe = cellRangerlist_dataframe,
  
  # References (For large/dynamic objects, we might still rely on global or add them here)
  PanglaoDB_ref = PanglaoDB_ref,
  
  # Directories
  root_dir = root_dir,
  save_output_name = save_output_name,
  save_dir = save_dir,
  output_dir = output_dir,
  figure_dir = figure_dir,
  BatchCheck_dir = BatchCheck_dir,
  DealPatch_dir = DealPatch_dir,
  qc_dir = qc_dir,
  Cellranger_dir = Cellranger_dir,
  RNAContamination_dir = RNAContamination_dir,
  doublet_dir = doublet_dir,
  cluster_dir = cluster_dir,
  UMAP_dir = UMAP_dir,
  tsne_dir = tsne_dir,
  cluster_marker_gene_dir = cluster_marker_gene_dir,
  DoHeatmap_dir = DoHeatmap_dir,
  DotPlot_dir = DotPlot_dir,
  subset_cell_cluster = subset_cell_cluster,
  annotation_dir = annotation_dir,
  annotation_SinglR_dir = annotation_SinglR_dir,
  annotation_CellID_dir = annotation_CellID_dir,
  # manual_annotation_figure_dir = manual_annotation_figure_dir,
  proportions_dir = proportions_dir,
  marker_gene_output_dir = marker_gene_output_dir,
  deg_figure_dir = deg_figure_dir
)

debug(logger, ">>> Initialization Complete. Run_Context created.")
# ==============================================================================
# END 
# ==============================================================================