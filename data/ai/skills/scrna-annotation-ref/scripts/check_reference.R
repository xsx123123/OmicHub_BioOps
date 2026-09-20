#!/usr/bin/env Rscript
# ==============================================================================
# Script: check_reference.R
# Description: Check completeness of the annotation reference directory
#              (Celldex/) required by the scRNAseqMulticommand pipeline:
#                - 4 ScType marker database files (bundled with the repo)
#                - SingleR reference .rds files per species (NOT bundled,
#                  must be downloaded from Bioconductor celldex/ExperimentHub)
# Exit code: 0 = all required files present; 1 = one or more missing
#            (missing list + acquisition guide printed to stderr).
# ==============================================================================

suppressPackageStartupMessages(library(optparse))

option_list <- list(
  make_option(c("--ref-dir"), type = "character", default = NULL,
              help = "Path to the Celldex reference directory [required]",
              metavar = "DIR"),
  make_option(c("--taxid"), type = "integer", default = 9606,
              help = "Species taxonomy ID: 9606 (human) or 10090 (mouse) [default: %default]",
              metavar = "N")
)

opt_parser <- OptionParser(option_list = option_list,
                           description = "Check scRNA-seq annotation reference files (ScType DB + SingleR rds).")
opt <- parse_args(opt_parser)

if (is.null(opt$`ref-dir`)) {
  print_help(opt_parser)
  stop("--ref-dir is required.", call. = FALSE)
}

ref_dir <- opt$`ref-dir`
taxid   <- opt$taxid

if (!dir.exists(ref_dir)) {
  cat(sprintf("ERROR: reference directory not found: %s\n", ref_dir), file = stderr())
  quit(save = "no", status = 1)
}

# ------------------------------------------------------------------------------
# Required file lists
# ScType marker DB files: bundled with the repository under Celldex/.
# SingleR rds filenames: as declared in scRNAseqMulticommand.yaml
# (section `singeler_reference`); 7 rds are NOT shipped with the repo.
# ------------------------------------------------------------------------------
sctype_files <- c(
  "Cell_marker_Human.txt",
  "Cell_marker_Mouse.txt",
  "PanglaoDB_markers_27_Mar_2020.tsv",
  "ScTypeDB_full.xlsx"
)

human_rds <- c(
  "HumanPrimaryCellAtla.rds",       # default for taxID 9606
  "HumanBlueprintEncode.rds",
  "HumanDICEImmuneCell.rds",
  "HumanMonacoImmune.rds",
  "HumanNovershternHematopoietic.rds"
)
mouse_rds <- c(
  "MouseRNA.rds",                   # default for taxID 10090
  "MouseImmGen.rds"
)

rds_files <- character(0)
if (taxid == 9606) {
  rds_files <- human_rds
} else if (taxid == 10090) {
  rds_files <- mouse_rds
} else {
  cat(sprintf("NOTE: taxID %s is not human(9606)/mouse(10090); checking ScType files only (SingleR references are not used by the pipeline for this species).\n",
              taxid))
}

required <- c(sctype_files, rds_files)

# ------------------------------------------------------------------------------
# Check each file
# ------------------------------------------------------------------------------
rows <- lapply(required, function(f) {
  p <- file.path(ref_dir, f)
  if (file.exists(p)) {
    sz <- file.info(p)$size
    data.frame(file = f, status = "present",
               size = ifelse(is.na(sz), "-", format(sz, big.mark = ",", scientific = FALSE)),
               stringsAsFactors = FALSE)
  } else {
    data.frame(file = f, status = "MISSING", size = "-", stringsAsFactors = FALSE)
  }
})
res <- do.call(rbind, rows)

cat(sprintf("Reference directory : %s\n", normalizePath(ref_dir)))
cat(sprintf("Species taxID       : %s\n\n", taxid))
print(res, row.names = FALSE, right = FALSE)

missing_files <- res$file[res$status == "MISSING"]
n_present <- sum(res$status == "present")

cat(sprintf("\nSummary: %d/%d required files present.\n", n_present, nrow(res)))

if (length(missing_files) > 0) {
  cat("\n", file = stderr())
  cat("MISSING reference files:\n", file = stderr())
  for (f in missing_files) cat(sprintf("  - %s\n", f), file = stderr())
  cat("\nHow to obtain them:\n", file = stderr())
  if (any(missing_files %in% sctype_files)) {
    cat("  * ScType marker DB files (Cell_marker_*.txt / PanglaoDB_markers_*.tsv / ScTypeDB_full.xlsx)\n", file = stderr())
    cat("    must be provisioned by the platform administrator into the shared reference\n", file = stderr())
    cat("    volume (sandbox path ref/Celldex/) per references/provisioning.md.\n", file = stderr())
    cat("    Please report this to the admin -- do NOT try to fetch them at runtime.\n", file = stderr())
  }
  if (any(missing_files %in% c(human_rds, mouse_rds))) {
    cat("  * SingleR .rds references must also be provisioned by the platform administrator.\n", file = stderr())
    cat("    Admin: download from Bioconductor celldex (ExperimentHub) and save with the exact filenames above:\n", file = stderr())
    cat("      library(celldex)\n", file = stderr())
    cat("      saveRDS(HumanPrimaryCellAtlasData(),          \"Celldex/HumanPrimaryCellAtla.rds\")\n", file = stderr())
    cat("      saveRDS(BlueprintEncodeData(),                \"Celldex/HumanBlueprintEncode.rds\")\n", file = stderr())
    cat("      saveRDS(DatabaseImmuneCellExpressionData(),   \"Celldex/HumanDICEImmuneCell.rds\")\n", file = stderr())
    cat("      saveRDS(MonacoImmuneData(),                   \"Celldex/HumanMonacoImmune.rds\")\n", file = stderr())
    cat("      saveRDS(NovershternHematopoieticData(),       \"Celldex/HumanNovershternHematopoietic.rds\")\n", file = stderr())
    cat("      saveRDS(MouseRNAseqData(),                    \"Celldex/MouseRNA.rds\")\n", file = stderr())
    cat("      saveRDS(ImmGenData(),                         \"Celldex/MouseImmGen.rds\")\n", file = stderr())
  }
  quit(save = "no", status = 1)
}

cat("All required reference files present.\n")
quit(save = "no", status = 0)
