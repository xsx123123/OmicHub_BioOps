# DEG 差异表达分析工具

基于 DESeq2 / edgeR 双引擎的差异表达分析工具。用户上传 Raw Counts 矩阵、样本分组表与比较对文件，
平台异步运行 R 容器完成标准化、PCA、差异检验与火山图绘制，前端展示统计表、结果表与图像产物。

设计依据：`tool_configs/tools_design.md` §5.1.1（配置外置）、§5.1.2（BLAST 异步任务架构）、
`docs/26.7.27/DEG/README.md`（R 脚本口径与统计学说明）。

## 目录

```
tool_configs/deg/
├── deg_config.yaml      # 工具运行配置（镜像、队列、超时、默认参数、输入限制），mtime 热重载
├── scripts/
│   ├── run_deseq2.r     # DESeq2 引擎（有生物学重复）
│   └── run_edger.r      # edgeR 引擎（1v1 无重复：固定 BCV exactTest；有重复：QL F-test）
├── vendor/
│   └── GenomeInfoDbData # 纯 R 数据包（1.2.11），构建期 R CMD INSTALL 进镜像。
│                        # 原因：bioconda 的 bioconductor-genomeinfodbdata 是占位器，
│                        # 真数据靠 post-link 从 bioconductor.org 下载，构建网络不可达。
├── examples/            # 示例输入（counts/metadata/pairs/annotation），前端「试试示例数据」引用
└── README.md            # 本文件（含容器契约）
```

Dockerfile 位于 `deploy/docker/Dockerfile.deg`（规范要求工具 Dockerfile 统一放 deploy/），
构建上下文为本目录：`make docker-build-deg`（等价 `docker build -f deploy/docker/Dockerfile.deg tool_configs/deg`）。

## 引擎路由

| 场景 | 引擎 | 说明 |
|---|---|---|
| 所有比较组两组均 ≥2 样本 | DESeq2 | 经典口径，与旧流程一致 |
| 任一比较组为 1v1（无重复） | edgeR | 1v1 对比：`exactTest(dispersion = bcv²)`；同批有重复对比：`estimateDisp + glmQLFTest` |
| 用户强制指定 | deseq2 / edger | `method` 参数；强制 deseq2 跑 1v1 会在该对比失败 |

BCV 取值（edgeR 官方建议）：0.4 人/异质生物样本（默认）、0.1 遗传一致模式生物/建系细胞、0.01 技术重复。
1v1 的 P 值条件于 BCV 假设，结果属探索性——统计表会逐对比记录 Method 与 Dispersion_Assumption。

## 容器契约（R 镜像）

**调用**（worker 执行，`{task}` 为任务目录，输入已写入 `{task}/input/`）：

```bash
Rscript /opt/deg/run_deseq2.r -c {task}/input/counts.csv -m {task}/input/metadata.csv \
        -p {task}/input/pairs.csv [-a {task}/input/annotation.csv] \
        -o {task}/results --lfc <lfc> --pval <pval>

Rscript /opt/deg/run_edger.r  ... 同上 ... --bcv <bcv>
```

**输入约定**：

| 文件 | 必需 | 格式 |
|---|---|---|
| counts.csv | 是 | 首列 GeneID，其余列为样本，值为整数 Raw Counts；csv 或 tsv（按扩展名识别） |
| metadata.csv | 是 | 列 `Sample,Group`（兼容 `sample_name,group`） |
| pairs.csv | 是 | 列 `Treat,Control` |
| annotation.csv | 否 | 首列基因 ID（输出列名 ENSEMBL），可含 Symbol 等注释列 |

**输出约定**（写入 `-o` 目录）：

| 产物 | 说明 |
|---|---|
| `All_Contrast_DEG_Statistics.csv` | 汇总表；edgeR 版含 Method / Dispersion_Assumption / N_Control / N_Treat |
| `{Treat}_vs_{Control}_DEG.csv` | 每对比全量结果：ENSEMBL, log2FoldChange, (baseMean\|logCPM), pvalue, padj, Symbol(+注释) |
| `{Treat}_vs_{Control}_Volcano.pdf/png` | 无标签火山图 |
| `{Treat}_vs_{Control}_Volcano_add_gene_id.pdf/png` | Top 基因标注火山图 |
| `Global_PCA_Combined.pdf/png` | 全局 PCA |
| `deseq2.log` / `edger.log` | 运行日志 |

**退出码**：0 成功；非 0 失败（worker 读取日志尾部作为用户安全错误摘要）。
容器不访问数据库、网络与用户凭据；只读写挂载的任务目录。

## 依赖

R ≥ 4.4，Bioconductor：DESeq2、edgeR；CRAN：tidyverse、optparse、ggplot2、ggrepel、ggpubr、
patchwork、log4r、crayon、cowplot。镜像内均已安装（见 Dockerfile.deg）。
