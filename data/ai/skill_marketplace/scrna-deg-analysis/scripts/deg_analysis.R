#!/usr/bin/env Rscript
# author : zhang jian
# date : 2026-08-03
# skill : scrna-deg-analysis (OmicHub OSDP v1.0)
# description : CLI wrapper for FindMarkers_Celltype_group.r
#   按 "细胞类型 x 分组" 批量差异表达分析 (FindMarkers) + 基因注释 + 火山图,
#   并在 <output>/summary.json 写出结构化摘要 (OSDP 6.3)。
# 退出码: 0 成功; 1 输入/参数校验失败; 2 分析或汇总阶段失败。

suppressPackageStartupMessages({
  library(optparse)
  library(jsonlite)
  library(Seurat)  # readRDS 的 S4 对象类定义与 FindMarkers 均依赖
})

option_list <- list(
  make_option('--input', type = 'character', default = NULL,
              help = 'Seurat 对象 RDS 文件路径 [必填]'),
  make_option('--output', type = 'character', default = NULL,
              help = '产物输出目录 (脚本负责创建) [必填]'),
  make_option('--celltype-col', type = 'character', default = 'celltype',
              help = 'meta.data 中细胞类型列名 [默认 %default]'),
  make_option('--pair-col', type = 'character', default = 'group',
              help = 'meta.data 中分组列名 (须含 --treat/--control 两个水平) [默认 %default]'),
  make_option('--treat', type = 'character', default = NULL,
              help = '处理组水平名 (ident.1) [必填]'),
  make_option('--control', type = 'character', default = NULL,
              help = '对照组水平名 (ident.2) [必填]'),
  make_option('--taxid', type = 'integer', default = 9606,
              help = '物种 taxid: 9606 人 / 10090 鼠 [默认 %default]'),
  make_option('--test', type = 'character', default = 'wilcox',
              help = 'FindMarkers 检验方法 [默认 %default]'),
  make_option('--pval-cutoff', type = 'double', default = 0.05,
              help = 'DEG 筛选 p_val_adj 阈值 [默认 %default]'),
  make_option('--lfc-cutoff', type = 'double', default = 1,
              help = 'DEG 筛选 |avg_log2FC| 阈值 [默认 %default]'),
  make_option('--pct-1', type = 'double', default = 0.25,
              help = 'pct.1 过滤阈值 [默认 %default]'),
  make_option('--top-gene', type = 'integer', default = 15,
              help = '火山图上下调各标注 top N 基因 [默认 %default]')
)
opt <- parse_args(OptionParser(option_list = option_list,
                               usage = 'Rscript deg_analysis.R --input <seurat.rds> --output <dir> --treat <T> --control <C> [选项]'))

fail <- function(msg, code = 1) {
  cat(paste0('[ERROR] ', msg, '\n'), file = stderr())
  quit(status = code)
}

# ---------- 1. 输入校验 ----------
if (is.null(opt$input) || is.null(opt$output) || is.null(opt$treat) || is.null(opt$control)) {
  fail('缺少必填参数: --input/--output/--treat/--control 均不可为空 (用 --help 查看用法)')
}
if (!file.exists(opt$input)) fail(paste0('输入文件不存在: ', opt$input))
if (!(opt$taxid %in% c(9606, 10090))) fail(paste0('--taxid 仅支持 9606 (人) / 10090 (鼠), 收到: ', opt$taxid))

seurat_obj <- tryCatch(readRDS(opt$input), error = function(e) {
  fail(paste0('读取 RDS 失败: ', conditionMessage(e)))
})
meta <- seurat_obj@meta.data

if (!(opt$`celltype-col` %in% colnames(meta))) {
  fail(paste0("meta.data 中不存在细胞类型列 '", opt$`celltype-col`,
              "'。可用列: ", paste(colnames(meta), collapse = ', '),
              '。请用 --celltype-col 指定实际列名'))
}
if (!(opt$`pair-col` %in% colnames(meta))) {
  fail(paste0("meta.data 中不存在分组列 '", opt$`pair-col`,
              "'。可用列: ", paste(colnames(meta), collapse = ', '),
              '。请用 --pair-col 指定实际列名'))
}
pair_levels <- levels(factor(meta[[opt$`pair-col`]]))
missing_groups <- setdiff(c(opt$treat, opt$control), pair_levels)
if (length(missing_groups) > 0) {
  fail(paste0("分组列 '", opt$`pair-col`, "' 中不存在水平: ", paste(missing_groups, collapse = ', '),
              '。实际可用水平: ', paste(pair_levels, collapse = ', ')))
}

dir.create(opt$output, showWarnings = FALSE, recursive = TRUE)

# 预检 gene_info 注释参考 (与函数库默认参数同一套环境变量逻辑, 失败即退出,
# 避免函数库内 tryCatch 吞掉报错后以"成功"收场)
ref_dir <- Sys.getenv('SCRNA_DEG_REF_DIR', unset = 'DEG_Annotation_reference')
ref_file <- file.path(ref_dir, if (opt$taxid == 10090) 'mm10_Mus_musculus.gene_info' else 'hg19_Homo_sapiens.gene_info')
if (!file.exists(ref_file)) {
  fail(paste0('DEG 注释参考文件缺失 (taxid=', opt$taxid, '): ', ref_file,
              '。请设置环境变量 SCRNA_DEG_REF_DIR 指向 gene_info 目录, ',
              '例如仓库内参考: tools/DEG/DEG_Annotation_reference/'))
}

# ---------- 2. 小样本预警 (细胞数 < 30, 不跳过, 仅 warning) ----------
warnings_list <- character(0)
celltypes <- levels(factor(meta[[opt$`celltype-col`]]))
for (ct in celltypes) {
  n_treat <- sum(meta[[opt$`celltype-col`]] == ct & meta[[opt$`pair-col`]] == opt$treat, na.rm = TRUE)
  n_ctrl  <- sum(meta[[opt$`celltype-col`]] == ct & meta[[opt$`pair-col`]] == opt$control, na.rm = TRUE)
  if (n_treat < 30 || n_ctrl < 30) {
    warnings_list <- c(warnings_list, paste0(
      ct, ': ', opt$treat, '=', n_treat, ' / ', opt$control, '=', n_ctrl,
      ' 个细胞 (<30), 统计功效不足, 该细胞类型的 DEG 结果请谨慎解读'))
  }
}

# ---------- 3. source 函数库并执行 ----------
script_args <- commandArgs(trailingOnly = FALSE)
script_path <- sub('^--file=', '', grep('^--file=', script_args, value = TRUE)[1])
lib_path <- file.path(dirname(normalizePath(script_path)), 'FindMarkers_Celltype_group.r')
source(lib_path)

run_err <- tryCatch({
  FindMarkers_Celltype_group(
    Seurat = seurat_obj,
    Celltype = opt$`celltype-col`,
    Pair = opt$`pair-col`,
    Treat = opt$treat,
    Control = opt$control,
    test = opt$test,
    pvalCutoff = opt$`pval-cutoff`,
    LFCCutoff = opt$`lfc-cutoff`,
    pct_1 = opt$`pct-1`,
    taxid = opt$taxid,
    save_dir = opt$output,
    top_gene = opt$`top-gene`)
  NULL
}, error = function(e) conditionMessage(e))
if (!is.null(run_err)) fail(paste0('DEG 分析失败: ', run_err), code = 2)

# ---------- 4. 扫描产物, 写 summary.json (OSDP 6.3) ----------
result_dirs <- list.dirs(opt$output, full.names = TRUE, recursive = FALSE)
result_dirs <- result_dirs[grepl(paste0('^', opt$treat, '_vs_', opt$control, '-'), basename(result_dirs))]

outputs <- list()
n_deg_total <- 0L
n_up <- 0L
n_down <- 0L
for (d in result_dirs) {
  rel_dir <- sub(paste0('^', normalizePath(opt$output), '/?'), '', normalizePath(d))
  csvs <- list.files(d, pattern = '\\.csv$', full.names = TRUE)
  pngs <- list.files(d, pattern = '\\.png$', full.names = TRUE)
  for (f in csvs) {
    outputs[[length(outputs) + 1]] <- list(path = file.path(rel_dir, basename(f)), type = 'table')
    if (grepl('-DEG\\.csv$', f)) {
      n_deg_total <- n_deg_total + max(nrow(read.csv(f, check.names = FALSE)), 0L)
    }
    if (grepl('-DEG-infor\\.csv$', f)) {
      infor <- tryCatch(read.csv(f, check.names = FALSE), error = function(e) NULL)
      if (!is.null(infor)) {
        n_up <- n_up + sum(infor$UP, na.rm = TRUE)
        n_down <- n_down + sum(infor$DOWN, na.rm = TRUE)
      }
    }
  }
  for (f in pngs) {
    outputs[[length(outputs) + 1]] <- list(path = file.path(rel_dir, basename(f)), type = 'figure')
  }
}
if (length(result_dirs) == 0) {
  warnings_list <- c(warnings_list, '未检测到任何细胞类型的输出目录, 可能所有 FindMarkers 调用均被跳过或失败, 请检查 stderr 日志')
}

summary <- list(
  tool = 'FindMarkers_Celltype_group',
  version = '1.2.1',
  status = 'success',
  outputs = outputs,
  stats = list(
    n_celltypes = length(result_dirs),
    n_deg_total = n_deg_total,
    n_up = n_up,
    n_down = n_down),
  warnings = as.list(warnings_list)
)
write_json(summary, file.path(opt$output, 'summary.json'), auto_unbox = TRUE, pretty = TRUE)
cat(paste0('[INFO] 分析完成, 摘要已写入: ', file.path(opt$output, 'summary.json'), '\n'))
