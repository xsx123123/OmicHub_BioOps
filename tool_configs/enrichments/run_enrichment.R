#!/usr/bin/env Rscript

# CygnusX R Docker entrypoint for a single, already-filtered Gene ID list.
# GO uses local OBO + gene-to-GO annotations. KEGG uses a local gene-to-NCBI/KEGG
# mapping before clusterProfiler::enrichKEGG. Results and figures are written to
# the same directory as --output.

options(stringsAsFactors = FALSE, warn = 1)

suppressPackageStartupMessages({
  library(clusterProfiler)
  library(enrichplot)
  library(ggplot2)
  library(ontologyIndex)
  library(optparse)
})

result_columns <- c(
  "Source", "ID", "Description", "GeneRatio", "BgRatio", "pvalue",
  "p.adjust", "qvalue", "geneID", "Count"
)

normalize_gene_ids <- function(gene_ids) {
  unique(sub("(\\.[0-9]+)+$", "", trimws(as.character(gene_ids))))
}

empty_result <- function() {
  data.frame(
    Source = character(), ID = character(), Description = character(),
    GeneRatio = character(), BgRatio = character(), pvalue = numeric(),
    p.adjust = numeric(), qvalue = numeric(), geneID = character(),
    Count = integer(), check.names = FALSE
  )
}

read_gene_list <- function(path) {
  if (!file.exists(path)) stop("输入基因列表不存在: ", path)
  genes <- readLines(path, warn = FALSE, encoding = "UTF-8")
  genes <- genes[nzchar(trimws(genes))]
  normalize_gene_ids(genes)
}

load_go_annotation <- function(obo_path, annotation_path) {
  if (!file.exists(obo_path)) stop("GO OBO 文件不存在: ", obo_path)
  if (!file.exists(annotation_path)) stop("GO 注释文件不存在: ", annotation_path)

  message("Loading local GO OBO: ", obo_path)
  obo <- ontologyIndex::get_ontology(obo_path, propagate_relationships = "is_a")
  term2name <- data.frame(GOID = obo$id, Term = obo$name, check.names = FALSE)

  lines <- readLines(annotation_path, warn = FALSE, encoding = "UTF-8")
  lines <- lines[nzchar(trimws(lines)) & !startsWith(lines, "#")]
  parsed <- strsplit(lines, "\\t", fixed = FALSE)
  gene_ids <- vapply(parsed, function(parts) if (length(parts) >= 1) parts[[1]] else "", "")
  go_values <- vapply(parsed, function(parts) if (length(parts) >= 2) parts[[2]] else "", "")
  pairs <- Map(function(gene_id, value) {
    terms <- trimws(unlist(strsplit(value, ",", fixed = TRUE)))
    terms <- terms[startsWith(terms, "GO:")]
    if (!length(terms)) return(NULL)
    data.frame(GOID = terms, GeneID = normalize_gene_ids(gene_id), check.names = FALSE)
  }, gene_ids, go_values)
  term2gene <- do.call(rbind, Filter(Negate(is.null), pairs))
  if (is.null(term2gene) || !nrow(term2gene)) {
    stop("GO 注释文件中没有可用的 gene-to-GO 记录")
  }
  term2gene <- term2gene[term2gene$GOID %in% term2name$GOID, , drop = FALSE]
  list(term2gene = unique(term2gene), term2name = term2name)
}

to_standard_result <- function(result, source) {
  if (is.null(result) || !nrow(as.data.frame(result))) return(empty_result())
  raw <- as.data.frame(result)
  raw$Source <- source
  raw <- raw[, c("Source", setdiff(result_columns, "Source")), drop = FALSE]
  raw[, result_columns, drop = FALSE]
}

save_result_plots <- function(result, output_dir, prefix) {
  if (is.null(result) || !nrow(as.data.frame(result))) return(invisible(NULL))
  plot <- enrichplot::dotplot(result, showCategory = 10) +
    ggtitle(paste0(prefix, " enrichment")) +
    theme_minimal(base_size = 12)
  ggsave(file.path(output_dir, paste0(prefix, "_dotplot.png")), plot,
    width = 10, height = 7, dpi = 180
  )
  ggsave(file.path(output_dir, paste0(prefix, "_dotplot.pdf")), plot,
    width = 10, height = 7
  )
}

run_go_enrichment <- function(genes, obo_path, annotation_path, p_cutoff, q_cutoff, output_dir) {
  if (is.null(obo_path) || is.null(annotation_path)) return(list(data = empty_result(), result = NULL))
  annotation <- load_go_annotation(obo_path, annotation_path)
  matched <- intersect(genes, unique(annotation$term2gene$GeneID))
  message("GO input genes: ", length(genes), "; matched local annotation: ", length(matched))
  if (!length(matched)) return(list(data = empty_result(), result = NULL))

  result <- clusterProfiler::enricher(
    gene = matched,
    TERM2GENE = annotation$term2gene,
    TERM2NAME = annotation$term2name,
    pvalueCutoff = p_cutoff,
    qvalueCutoff = q_cutoff
  )
  save_result_plots(result, output_dir, "go")
  list(data = to_standard_result(result, "GO"), result = result)
}

run_kegg_enrichment <- function(genes, id_map_path, organism, key_type, p_cutoff, q_cutoff, output_dir) {
  if (is.null(id_map_path) || !nzchar(organism)) return(list(data = empty_result(), result = NULL))
  if (!file.exists(id_map_path)) stop("KEGG ID 映射文件不存在: ", id_map_path)

  id_map <- read.delim(id_map_path, header = FALSE, sep = "\t", quote = "", fill = TRUE,
    stringsAsFactors = FALSE, colClasses = "character"
  )
  if (ncol(id_map) < 2) stop("KEGG ID 映射文件至少需要两列: gene_id<TAB>ncbi_or_kegg_id")
  names(id_map)[1:2] <- c("symbol", "kegg_id")
  id_map$symbol <- normalize_gene_ids(id_map$symbol)
  mapped <- unique(id_map$kegg_id[id_map$symbol %in% genes])
  mapped <- mapped[nzchar(mapped)]
  message("KEGG input genes: ", length(genes), "; matched ID map: ", length(mapped))
  if (!length(mapped)) return(list(data = empty_result(), result = NULL))

  result <- clusterProfiler::enrichKEGG(
    gene = mapped,
    organism = organism,
    keyType = key_type,
    pvalueCutoff = p_cutoff,
    qvalueCutoff = q_cutoff
  )
  save_result_plots(result, output_dir, "kegg")
  list(data = to_standard_result(result, "KEGG"), result = result)
}

main <- function() {
  option_list <- list(
    make_option("--input", type = "character", help = "单列 Gene ID 文本文件"),
    make_option("--output", type = "character", help = "合并富集结果 CSV"),
    make_option("--go_obo", type = "character", default = NULL),
    make_option("--go_annotation", type = "character", default = NULL),
    make_option("--kegg_id_map", type = "character", default = NULL),
    make_option("--kegg_code", type = "character", default = ""),
    make_option("--kegg_key_type", type = "character", default = "kegg"),
    make_option("--id_type", type = "character", default = ""),
    make_option("--p_value_cutoff", type = "double", default = 0.05),
    make_option("--q_value_cutoff", type = "double", default = 0.1)
  )
  options <- parse_args(OptionParser(option_list = option_list))
  if (is.null(options$input) || is.null(options$output)) {
    stop("必须提供 --input 和 --output")
  }
  if (options$p_value_cutoff <= 0 || options$p_value_cutoff > 1) {
    stop("--p_value_cutoff 必须大于 0 且不超过 1")
  }
  if (options$q_value_cutoff <= 0 || options$q_value_cutoff > 1) {
    stop("--q_value_cutoff 必须大于 0 且不超过 1")
  }

  output_dir <- dirname(options$output)
  if (!dir.exists(output_dir)) dir.create(output_dir, recursive = TRUE)
  genes <- read_gene_list(options$input)
  if (!length(genes)) stop("输入基因列表为空")

  results <- list()
  errors <- character()
  successful_analyses <- 0L
  if (!is.null(options$go_obo) || !is.null(options$go_annotation)) {
    go <- tryCatch(
      {
        result <- run_go_enrichment(genes, options$go_obo, options$go_annotation,
          options$p_value_cutoff, options$q_value_cutoff, output_dir
        )
        successful_analyses <- successful_analyses + 1L
        result
      },
      error = function(error) {
        errors <<- c(errors, paste0("GO: ", error$message))
        list(data = empty_result(), result = NULL)
      }
    )
    results[["go"]] <- go$data
  }
  if (!is.null(options$kegg_id_map) && nzchar(options$kegg_code)) {
    kegg <- tryCatch(
      {
        result <- run_kegg_enrichment(genes, options$kegg_id_map, options$kegg_code,
          options$kegg_key_type, options$p_value_cutoff, options$q_value_cutoff, output_dir
        )
        successful_analyses <- successful_analyses + 1L
        result
      },
      error = function(error) {
        errors <<- c(errors, paste0("KEGG: ", error$message))
        list(data = empty_result(), result = NULL)
      }
    )
    results[["kegg"]] <- kegg$data
  }
  if (!length(results)) stop("该物种未配置 GO 注释或 KEGG ID 映射")
  if (!successful_analyses && length(errors)) stop(paste(errors, collapse = "; "))
  combined <- do.call(rbind, results)
  combined <- combined[order(combined$p.adjust, combined$pvalue), , drop = FALSE]
  write.csv(combined, options$output, row.names = FALSE, fileEncoding = "UTF-8")
  if (length(errors)) message("Partial enrichment warnings: ", paste(errors, collapse = "; "))
  message("Wrote enrichment CSV: ", options$output)
}

main()
