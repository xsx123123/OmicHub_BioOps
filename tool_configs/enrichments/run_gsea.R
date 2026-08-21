#!/usr/bin/env Rscript

suppressPackageStartupMessages({ library(clusterProfiler); library(optparse) })

option_list <- list(
  make_option("--input", type = "character"),
  make_option("--output", type = "character"),
  make_option("--gene_set", type = "character"),
  make_option("--go_annotation", type = "character", default = ""),
  make_option("--p_value_cutoff", type = "double", default = 0.05),
  make_option("--q_value_cutoff", type = "double", default = 0.1)
)
opt <- parse_args(OptionParser(option_list = option_list))
ranking <- read.delim(opt$input, check.names = FALSE, stringsAsFactors = FALSE)
if (!all(c("gene_id", "score") %in% names(ranking))) stop("ranking input needs gene_id and score")
scores <- ranking$score; names(scores) <- ranking$gene_id
scores <- sort(scores, decreasing = TRUE)
if (!nzchar(opt$go_annotation) || !file.exists(opt$go_annotation)) {
  stop("GSEA needs a local GO annotation TERM2GENE file for the selected species")
}
annotation <- read.delim(opt$go_annotation, header = FALSE, stringsAsFactors = FALSE)
if (ncol(annotation) < 2) stop("GO annotation must contain gene_id and term columns")
term2gene <- data.frame(term = annotation[[2]], gene = annotation[[1]])
result <- GSEA(scores, TERM2GENE = term2gene, pvalueCutoff = opt$p_value_cutoff, pAdjustMethod = "BH", verbose = FALSE)
if (is.null(result) || nrow(as.data.frame(result)) == 0) {
  write.csv(data.frame(ID=character(), Description=character(), NES=numeric(), pvalue=numeric(), p.adjust=numeric(), qvalue=numeric(), setSize=integer(), leading_edge_count=integer()), opt$output, row.names = FALSE)
  quit(status = 0)
}
table <- as.data.frame(result)
leading <- vapply(strsplit(as.character(table$core_enrichment), "/", fixed = TRUE), length, integer(1))
output <- data.frame(ID=table$ID, Description=table$Description, NES=table$NES, pvalue=table$pvalue, p.adjust=table$p.adjust, qvalue=table$qvalues, setSize=table$setSize, leading_edge_count=leading, check.names = FALSE)
write.csv(output, opt$output, row.names = FALSE)
curve_path <- paste0(opt$output, ".running_scores.json")
running <- cumsum(ifelse(scores >= 0, abs(scores) / max(abs(scores)), -abs(scores) / max(abs(scores))))
jsonlite::write_json(data.frame(rank=seq_along(running), score=as.numeric(running)), curve_path, auto_unbox=TRUE)
