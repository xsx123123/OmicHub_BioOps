#!/usr/bin/env Rscript
# projectils_annotate.R
# scrna-tcell-projectils 技能的 CLI wrapper（OSDP §6.2 契约）
# 功能：对含 T 细胞的 Seurat RDS 对象运行 ProjecTILs.classifier 精细亚型注释
# 用法：
#   Rscript projectils_annotate.R --input <tcell.rds> --output <outdir> \
#       [--name Tcell] [--cores 20] [--ref <projectils_ref.rds>]
# 退出码：0 成功；1 失败（stderr 输出可读错误信息）

suppressMessages(library(optparse))

option_list <- list(
  make_option(c("--input"), type = "character", default = NULL,
              help = "必填。含 T 细胞的 Seurat RDS 对象路径（需已有 umap 降维）"),
  make_option(c("--output"), type = "character", default = NULL,
              help = "必填。输出目录（脚本自动创建）"),
  make_option(c("--name"), type = "character", default = "Tcell",
              help = "项目 ID，用于输出文件命名前缀 [default: %default]"),
  make_option(c("--cores"), type = "integer", default = 20L,
              help = "ProjecTILs.classifier 并行核数 [default: %default]"),
  make_option(c("--ref"), type = "character", default = NULL,
              help = paste("可选。ProjecTILs 参考对象 rds 路径。缺省时调用",
                           "ProjecTILs::load.reference.map() 在线加载（需要网络）"))
)

parser <- OptionParser(option_list = option_list,
                       usage = "Rscript %prog --input <tcell.rds> --output <outdir> [--name Tcell] [--cores 20] [--ref ref.rds]",
                       description = "T 细胞 ProjecTILs functional.cluster 精细亚型注释")
opt <- parse_args(parser)

fail <- function(msg) {
  cat(paste0("[ERROR] ", msg, "\n"), file = stderr())
  quit(status = 1L, save = "no")
}

# ---- 参数与输入校验 ----
if (is.null(opt$input))  fail("缺少必填参数 --input（含 T 细胞的 Seurat RDS 路径）")
if (is.null(opt$output)) fail("缺少必填参数 --output（输出目录）")
if (!file.exists(opt$input)) {
  fail(paste0("输入文件不存在: ", opt$input))
}
if (!is.null(opt$ref) && !file.exists(opt$ref)) {
  fail(paste0("--ref 指定的参考文件不存在: ", opt$ref))
}

# ---- 依赖检查 ----
if (!requireNamespace("Seurat", quietly = TRUE)) {
  fail("R 包 Seurat 未安装，请先配置环境（见 references/environment.md）")
}
if (!requireNamespace("ProjecTILs", quietly = TRUE)) {
  fail(paste0("R 包 ProjecTILs 未安装。请按 references/environment.md 安装",
              "（remotes::install_github('carmonalab/ProjecTILs')）"))
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  fail("R 包 jsonlite 未安装（summary.json 输出依赖）")
}

# ---- source 同目录函数库（脚本自身路径推导，不依赖 CWD） ----
args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args_all, value = TRUE)
if (length(file_arg) == 0L) fail("无法定位脚本自身路径（--file 参数缺失）")
script_dir <- dirname(normalizePath(sub("^--file=", "", file_arg[1L])))
source(file.path(script_dir, "ProjecTIL_Annotation.r"))

# ---- 读取并校验输入对象 ----
scData <- tryCatch(readRDS(opt$input), error = function(e) {
  fail(paste0("读取 RDS 失败: ", conditionMessage(e)))
})
if (!inherits(scData, "Seurat")) {
  fail(paste0("输入对象不是 Seurat 对象（class: ", paste(class(scData), collapse = ","), "）"))
}
reductions <- tryCatch(Seurat::Reductions(scData), error = function(e) character(0))
if (!("umap" %in% reductions)) {
  fail(paste0("输入对象缺少 umap 降维（现有降维: ",
              ifelse(length(reductions) == 0L, "无", paste(reductions, collapse = ",")),
              "）。请先完成 PCA/UMAP 降维后再运行本技能"))
}

# ---- 加载参考 ----
if (!is.null(opt$ref)) {
  ref <- tryCatch(readRDS(opt$ref), error = function(e) {
    fail(paste0("读取 --ref 参考文件失败: ", conditionMessage(e)))
  })
  ref_source <- opt$ref
} else {
  message("[INFO] --ref 未提供，调用 ProjecTILs::load.reference.map() 在线加载参考（需要网络）")
  ref <- tryCatch(ProjecTILs::load.reference.map(), error = function(e) {
    fail(paste0("在线加载 ProjecTILs 参考失败（可能无网络）: ", conditionMessage(e),
                "。可在有网络环境预下载后用 --ref 传入本地 rds"))
  })
  ref_source <- "ProjecTILs::load.reference.map() (online)"
}

# ---- 运行主流程 ----
dir.create(opt$output, recursive = TRUE, showWarnings = FALSE)
warnings_list <- character(0)
query.projected <- withCallingHandlers(
  tryCatch(
    ProjecTILs.classifier.pipeline(scData = scData, ref = ref, name = opt$name,
                                   reduction = "umap", cores = opt$cores,
                                   colors = NULL, save_dir = opt$output),
    error = function(e) {
      fail(paste0("ProjecTILs.classifier.pipeline 运行失败: ", conditionMessage(e)))
    }
  ),
  warning = function(w) {
    warnings_list <<- c(warnings_list, conditionMessage(w))
    invokeRestart("muffleWarning")
  }
)

# ---- 统计与 summary.json（OSDP §6.3） ----
n_cells <- ncol(query.projected)
if (!("functional.cluster" %in% colnames(query.projected@meta.data))) {
  fail("结果对象缺少 functional.cluster 注释列，注释流程异常")
}
fc <- query.projected@meta.data[["functional.cluster"]]
n_functional_clusters <- length(unique(fc))
cluster_counts <- sort(table(fc))
small_clusters <- names(cluster_counts[cluster_counts < 30])
if (length(small_clusters) > 0L) {
  warnings_list <- c(warnings_list, paste0(
    "以下 functional.cluster 细胞数 < 30，统计功效不足: ",
    paste(small_clusters, collapse = ",")))
}

prefix <- paste0("ProjecTILs.classifier-", opt$name)
outputs <- list(
  list(path = paste0(prefix, "-annotation.rds"),          type = "object"),
  list(path = paste0(prefix, "-annotation.png"),          type = "figure"),
  list(path = paste0(prefix, "-annotation.pdf"),          type = "figure"),
  list(path = paste0(prefix, "-annotation-Dotplot.png"),  type = "figure"),
  list(path = paste0(prefix, "-annotation-Dotplot.pdf"),  type = "figure"),
  list(path = "markrt_list.csv",                          type = "table")
)
summary <- list(
  tool     = "projectils_annotate",
  version  = "0.9.0",
  status   = "success",
  outputs  = outputs,
  stats    = list(
    n_cells               = n_cells,
    n_functional_clusters = n_functional_clusters,
    ref_source            = ref_source
  ),
  warnings = as.list(unique(warnings_list))
)
jsonlite::write_json(summary, file.path(opt$output, "summary.json"),
                     auto_unbox = TRUE, pretty = TRUE)
cat(paste0("[INFO] 注释完成: n_cells=", n_cells,
           ", n_functional_clusters=", n_functional_clusters,
           ", 结果见 ", opt$output, "/summary.json\n"))
quit(status = 0L, save = "no")
