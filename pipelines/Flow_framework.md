# Flow 家族框架规范（Flow Framework Spec）

> 本文档基于 `RNAFlow`（v0.1.9）与 `ATACFlow`（v0.0.6）两个 Snakemake 分析流程梳理而成，作为扩展 Flow 家族（如 WGSFlow / ChIPFlow / MethylationFlow 等）的统一骨架规范。
>
> **核心思想**：骨架（入口、配置、utils 工具层、规则编号约定、交付/报告收尾、周边 envs/src/report/mcp/skills）在所有 Flow 间同构复用；只有 **"06 之后的分析规则 + `datadeliver.py` 模块函数 + `reference.yaml` 索引类型"** 按数据类型定制。
>
> **扩展新 Flow = 复制骨架 + 替换分析逻辑层。**

---

## 目录

- [一、顶层目录结构对照](#一顶层目录结构对照)
- [二、入口 snakefile：6 段式骨架](#二入口-snakefile6-段式骨架)
- [三、配置四件套 + Schema](#三配置四件套--schema)
- [四、rules/utils/ 七大模块（★ 框架核心）](#四rulesutils-七大模块框架核心)
- [五、rule smk 标准写法 + 编号约定](#五rule-smk-标准写法--编号约定)
- [六、数据流：raw_data → deliver → report](#六数据流raw_data--deliver--report)
- [七、周边系统（envs/src/report/mcp/skills）](#七周边系统envssrcreportmcpskills)
- [八、ATACFlow 相对 RNAFlow 的框架演进](#八atacflow-相对-rnaflow-的框架演进)
- [九、扩展新 Flow 完整 Checklist](#九扩展新-flow-完整-checklist)
- [十、命名约定与最佳实践](#十命名约定与最佳实践)

---

## 一、顶层目录结构对照

```
XxxFlow/
├── snakefile                 # 入口：6 段式骨架（所有 Flow 一致）
├── config/                   # 配置四件套
│   ├── config.yaml           #   全局开关 + software 路径 + 输出命名 + pipeline_version
│   ├── reference.yaml        #   reference_path + can_use_genome_version + 各基因组索引
│   ├── run_parameter.yaml    #   parameter.threads + 各工具参数 + 脚本路径
│   └── cluster_config.yaml   #   cluster_config.resource_profiles（low/med/high/very_high）
├── schema/config.schema.yaml # JSON Schema 校验（enum 锁 Genome_Version + 模块开关）
├── rules/                    # 编号规则（01.common → 最后.Report）
│   ├── utils/                # ★ 框架核心，与分析逻辑解耦
│   └── NN.xxx.smk
├── envs/                     # 一工具一 conda yaml
├── src/                      # 辅助脚本（Python/R），git submodule
├── data/                     # adapter fasta + fastq_screen 模板
├── report/                   # BioReport（Quarto+Docker+AI），git submodule
├── mcp/                      # MCP server（uv + SQLite）
├── skills/                   # AI Skills（Claude Code/Codex 安装脚本）
└── doc(s)/ README.md
```

**两仓库差异**：ATACFlow 额外有 `container_env/`（构建流程容器镜像）和 `rules/subrules/`（子规则拆分）；RNAFlow 用 `doc/`，ATACFlow 用 `docs/`。新 Flow 按需采纳。

---

## 二、入口 snakefile：6 段式骨架

所有 Flow 的入口文件逐段对齐，只有第 4 段（流程特有预处理）和 `include` 列表不同。

### 段落划分

| 段 | 作用 | 说明 |
|----|------|------|
| 0 | 锁版本 + 导入 utils 模块 | `min_version("9.9.0")`；导入 `id_convert / validate / reference_update / resource_manager` |
| 1 | Config Loading | 4 个 `configfile:` 顺序加载，再 `load_user_config` 让 CLI yaml **最高优先级覆盖** |
| 2 | Processing & Validation | `resolve_reference_paths` → `validate(schema)` → `check_reference_paths` → `validate_genome_version` |
| 3 | Workspaces & Samples | `workdir: config["workflow"]` 重定向；`load_samples` + `load_contrasts` |
| 4 | 流程特有预处理 | RNAFlow：`only_qc` 跳过 contrast；ATACFlow：pooled/merge_group 预计算注入 `config` |
| 5 | Rules Import + `rule all` | `include:` 各 `.smk`；`rule all` 的 input = `DataDeliver(...)` 动态生成 |

### 模板（新 Flow 直接套用）

```python
#!/usr/bin/env python3
# *---utf-8---*
# Version: XxxFlow v0.0.1
# Author : JZHANG

import sys
import os
from snakemake.utils import min_version, validate

# ------- Import Custom Modules ------- #
from rules.utils.id_convert import load_samples, load_contrasts, parse_groups
from rules.utils.validate import (
    check_reference_paths, load_user_config,
    validate_genome_version, validate_species,
)
from rules.utils.reference_update import resolve_reference_paths
from rules.utils.resource_manager import rule_resource

# Lock Snakemake Version
min_version("9.9.0")

# --------- 1. Config Loading --------- #
configfile: "config/config.yaml"
configfile: "config/reference.yaml"
configfile: "config/run_parameter.yaml"
configfile: "config/cluster_config.yaml"

# Load CLI argument config (Highest Priority)
load_user_config(config, cmd_arg_name='analysisyaml')

# --------- 2. Processing & Validation --------- #
resolve_reference_paths(
    config,
    config.get('can_use_genome_version', []),
    base_path=config.get('reference_path'),
)
validate(config, "schema/config.schema.yaml")
check_reference_paths(config.get("<Aligner>_index", {}))   # ★ 换成你的比对器索引

from snakemake_logger_plugin_rich_loguru import get_analysis_logger
logger = get_analysis_logger()
validate_genome_version(config=config, logger=logger)
validate_species(config=config, logger=logger)             # 可选

# --------- 3. Workspaces & Samples --------- #
workdir: config["workflow"]
merge_group, samples = load_samples(
    config["sample_csv"],
    required_cols=["sample", "sample_name", "group"],
    logger=logger,
)
groups = parse_groups(samples)
ALL_CONTRASTS, CONTRAST_MAP = load_contrasts(config["paired_csv"], samples)

# --------- 4. 流程特有预处理（按需）--------- #
# 例：ATACFlow 的 pooled 分析预计算
# run_pooled = config['peak_calling']['use_pooled_peaks'] and merge_group
# config['_merge_group'] = merge_group
# config['_run_pooled'] = run_pooled

# --------- 5. Rules Import --------- #
include: 'rules/01.common.smk'
include: 'rules/02.file_convert_md5.smk'
include: 'rules/03.short_read_qc.smk'
include: 'rules/04.Contamination_check.smk'
include: 'rules/05.short_read_clean.smk'
include: 'rules/06.mapping.smk'
# ... 07~ 分析规则（按数据类型定制）...
include: 'rules/NN.deliver.smk'
include: 'rules/NN.Report.smk'

# --------- 6. Target Rule --------- #
rule all:
    input:
        DataDeliver(config=config, samples=samples,
                    merge_group=merge_group, groups=groups),
# --------------- END -------------- #
```

**关键设计**：`rule all` 不手写 target 列表，而是调用 `DataDeliver()` 动态生成——这是整个框架"配置驱动模块开关"的枢纽。

---

## 三、配置四件套 + Schema

### 3.1 `config/config.yaml` — 全局开关

```yaml
# Software Paths（自定义编译的可执行文件 + Python 脚本）
software:
  json_md5_verifier: ../src/src/md5/Compile_release/.../json_md5_verifier
  seq_preprocessor:  ../src/src/md5/Compile_release/.../seq_preprocessor
  check_libtype:     ../src/src/library_type/check_libtype.py

# Raw Data
raw_data:
  md5: 'md5.txt'

# Pipeline Control Flags（全局布尔开关）
print_target: false
print_sample: false
log_level: INFO
bam_remove: true
only_qc: false          # true = 只跑 QC，跳过所有下游

# Output Naming
convert_md5: 'link_dir'
r1_suffix: _R1.fq.gz
r2_suffix: _R2.fq.gz
md5: MD5.txt
pipeline_version: "XxxFlow v0.0.1"

# ★ 流程特有配置块（如 ATACFlow 的 peak_calling）
```

### 3.2 `config/reference.yaml` — 参考基因组

```yaml
reference_path : /home/zj/reference/XxxFlow_reference   # 迁移时改这一行
fastq_screen_db_path: /data/.../fastq_screen_database

can_use_genome_version:          # 支持的基因组版本列表
  - hg38
  - GRCm39
  - ...

mcp_genome_version:              # MCP server 用的基因组描述
  hg38:
    name: hg38
    description: Human reference genome (GRCh38/hg38)

<Aligner>_index:                 # ★ 索引类型按流程换（STAR_index / Bowtie2_index / BWA_index...）
  hg38:
    index: HG38/...              # 相对 reference_path 的路径，会被 resolve_reference_paths 拼成绝对路径
    genome_fa: HG38/...
    genome_gtf: HG38/...
    genome_gff: HG38/...
    bed12: HG38/...
    go_annotation: HG38/...
    ref_all: HG38/...
    # 流程特有字段（如 rsem_index / blacklists / ploidy）

deg_enrich_wrapper:              # 富集分析的基因 ID 列名（按基因组）
  hg38:
    gene_col: 'ENSEMBL'

ploidy_setting:                  # 倍性（variant calling 用）
  hg38:
    ploidy: 2
```

### 3.3 `config/run_parameter.yaml` — 工具运行参数

```yaml
parameter:
  threads:                       # ★ 每个工具的线程数（rule 里通过 config['parameter']['threads']['xxx'] 取）
    json_md5_verifier: 40
    fastqc: 1
    fastp: 6
    multiqc: 1
    fastq_screen: 10
    <ALIGNER>: 15
    samtools: 10
    ...

  fastq_screen:
    path: ../src/src/fastq_screen/fastq_screen
    dir:  ../src/src/fastq_screen/
    conf: ../src/src/fastq_screen/fastq_screen.conf
    subset: 100000
    aligner: Bowtie2

  trim:
    length_required: 75
    quality_threshold: 25
    adapter_fasta: "../data/Universal_Adapter.fa"

  # ★ 流程特有工具参数（STAR / MACS2 / DEG / ...）

  RNAFlow_Deliver_Tool:         # 交付工具配置
    config_path: "../src/src/data-deliver/.../full_delivery_config.yaml"
    config_path_report: "../src/src/data-deliver/.../report.yaml"

  Report:
    docker_version: bioreportxxx:v0.0.1   # ★ 报告镜像版本
```

### 3.4 `config/cluster_config.yaml` — 集群资源档位

```yaml
cluster_config:
  resource_profiles:
    low_resource:
      threads: 2
      mem_mb: 18000
      runtime: 60            # minutes
      queue_type: "default_queue"
    medium_resource:
      threads: 10
      mem_mb: 86000
      runtime: 120
      queue_type: "default_queue"
    high_resource:
      threads: 18
      mem_mb: 100000
      runtime: 240
      queue_type: "high_mem_queue"
    very_high_resource:
      threads: 32
      mem_mb: 64000
      runtime: 360
      queue_type: "high_mem_queue"
```

rule 里通过 `resources: **rule_resource(config, 'low_resource', ...)` 引用档位名。

### 3.5 `schema/config.schema.yaml` — JSON Schema 校验

```yaml
$schema: "http://json-schema.org/draft-07/schema#"
title: "XxxFlow Main Configuration Schema"
type: "object"
properties:
  project_name:   { type: "string", minLength: 1 }
  Genome_Version:                       # ★ enum 锁定支持的基因组版本
    type: "string"
    enum: ["hg38", "GRCm39", ...]
  species:        { type: "string", minLength: 1 }
  client:         { type: "string", minLength: 1 }
  raw_data_path:  { type: "array", items: { type: "string" }, minItems: 1 }
  sample_csv:     { type: "string", minLength: 1 }
  paired_csv:     { type: "string" }
  workflow:       { type: "string", minLength: 1 }
  data_deliver:   { type: "string", minLength: 1 }
  execution_mode: { type: "string", enum: ["local", "cluster"], default: "local" }
  queue_id:       { type: "string" }
  Library_Types:  { type: "string", enum: ["fr-unstranded", "fr-firststrand", "fr-secondstrand"] }
  # ★ 流程特有模块开关
  only_qc:        { type: "boolean", default: false }
  deg:            { type: "boolean", default: true }
  report:         { type: "boolean", default: true }
  ...
additionalProperties: true
```

---

## 四、rules/utils/ 七大模块（★ 框架核心）

这是真正"与具体分析无关"的骨架，新 Flow **几乎原样拷贝**。只有 `common.py` 的模块表和 `datadeliver.py` 需要按流程替换。

| 文件 | 职责 | 复用度 |
|------|------|--------|
| `common.py` | `DataDeliver()` 总调度 + `ReportData()` + 路径/索引校验辅助函数 | 骨架复用，**模块表需替换** |
| `datadeliver.py` | 每个分析模块一个函数，用 `expand` 拼 target 路径 | **全替换**（分析逻辑的产出声明）|
| `id_convert.py` | `load_samples` + `load_contrasts` (+ `parse_groups`) | 原样复用 |
| `validate.py` | `check_reference_paths` + `load_user_config` + `validate_genome_version` (+ `validate_species`) | 原样复用 |
| `reference_update.py` | `resolve_reference_paths`（相对→绝对）| 原样复用 |
| `resource_manager.py` | `rule_resource`（按 profile 取资源，local/cluster 智能切换）| 原样复用 |
| `tools.py`（可选）| 流程专用小工具函数 | ATACFlow 新增，按需 |
| `__init__.py` | 空，让 `rules.utils` 可被 import | 原样复用 |

### 4.1 `common.py` — 总调度

**核心是 `DataDeliver()`**：根据 `config` 里的模块开关，决定哪些分析模块产出文件，把它们的 target 路径收集进 `data_deliver` 列表返回。`rule all` 拿这个列表当 input。

**需要替换的三张表**（在 `DataDeliver` 内）：

```python
# [A] 基础模块：无论如何必须运行（除非显式 False）
basic_modules = ["qc_clean", "mapping", "peak_calling", "motif_analysis", ...]

# [B] 深度质控标记：mapping 内部参数，默认开启
deep_qc_flags = ["bamCoverage"]

# [C] 下游分析模块：only_qc=True 时跳过
downstream_modules = ["diff_peaks"]

# 模块依赖（下游开启时自动连带开启上游）—— ATACFlow 演进点
MODULE_DEPENDENCIES = {
    "peak_calling": ["mapping"],
    "motif_analysis": ["peak_calling"],
    "diff_peaks": ["consensus_peaks"],
    ...
}

# 模块函数映射（用 partial 统一签名为 func(samples, data_deliver)）—— ATACFlow 演进点
module_functions = {
    "qc_clean": qc_clean,
    "mapping": partial(mapping, config=config),
    "peak_calling": peak_calling,
    "diff_peaks": partial(diff_peaks, run_pooled=run_pooled),
    ...
}
```

**其他辅助函数**（原样复用）：
- `ReportData(config)`：返回报告生成所需的文件清单
- `get_sample_data_dir(sample_id, config)`：按 sample_id 查找 fastq 所在目录（支持 `SampleID/xxx.fq` 和 `SampleID.R1.fq` 两种布局）
- `get_all_input_dirs(sample_keys, config)`：聚合所有样本的输入目录（去重）
- `judge_bwa_index(config)` / `judge_star_index(config, version)`：校验索引完整性
- `check_gene_version(config, logger)`：校验基因组版本在白名单内

### 4.2 `datadeliver.py` — 模块产出声明（★ 全替换）

每个分析模块一个函数，签名统一为 `func(samples, data_deliver, ...) -> List[str]`，用 `snakemake.io.expand` 拼目标文件路径并 `extend` 进 `data_deliver`。

```python
from snakemake.io import expand

def mapping(samples=None, data_deliver=None, config=None):
    """声明 mapping 模块的产出文件。"""
    if samples is None: samples = {}
    if data_deliver is None: data_deliver = []
    if config is None: config = {}

    # 核心产出（无论开关如何都生成）
    data_deliver.extend(expand("02.mapping/<aligner>/sort_index/{sample}.sort.bam", sample=samples.keys()))
    data_deliver.extend(expand("02.mapping/samtools_flagstat/{sample}_bam_flagstat.tsv", sample=samples.keys()))
    data_deliver.append("02.mapping/mapping_report/multiqc_mapping_report.html")

    # 条件产出（受 deep_qc_flags 控制）
    if config.get('bamCoverage'):
        for sample in samples.keys():
            data_deliver.append(f"02.mapping/bamCoverage/{sample}.bw")

    return data_deliver


def some_downstream(samples=None, data_deliver=None, all_contrasts=None):
    """声明下游分析产出（可能依赖 contrasts）。"""
    ...
    if all_contrasts:
        data_deliver.extend(expand("06.xxx/{contrast}/summary.txt", contrast=all_contrasts))
    return data_deliver
```

> **重要**：`datadeliver.py` 里**只声明路径字符串**，不检查文件是否存在。路径必须与对应 `.smk` rule 的 `output` **完全一致**——这是框架最容易出错的地方，改 output 必须同步改这里。

### 4.3 `id_convert.py` — 样本/对比表解析（原样复用）

- `load_samples(csv_path, required_cols, index_col="sample")`：读 CSV（`dtype=str`，`comment='#'`），校验必填列 + ID 唯一性，**自动生成固定 BAM 路径**（`02.mapping/.../{sample}.sort.bam`，不检查存在性），返回 `{sample_id: {sample, sample_name, group, bam, ...}}`。ATACFlow 版本额外返回 `merge_group` 布尔。
- `load_contrasts(csv_path, samples_dict)`：读 `Control,Treat` 两列表，按 group 匹配 BAM，返回 `(all_contrasts: List[str], contrast_map: Dict)`，`contrast_map[c_name] = {"b1": ctrl_bams, "b2": treat_bams}`。
- `parse_groups(samples)`（ATACFlow 新增）：从 samples 解析分组信息。

### 4.4 `validate.py` — 配置校验（原样复用）

- `check_reference_paths(ref_dict)`：用 rich 表格列出缺失的参考文件并 `sys.exit(1)`。
- `load_user_config(config, cmd_arg_name='analysisyaml')`：读取 CLI 传入的 yaml，用 `snakemake.utils.update_config` **递归合并**覆盖默认 config。
- `validate_genome_version(config, logger)`：校验 `Genome_Version` 在 `can_use_genome_version` 内。
- `validate_species(config, logger)`（ATACFlow 新增）：校验物种与基因组匹配。

### 4.5 `reference_update.py` — 路径解析（原样复用）

`resolve_reference_paths(config, targets, base_path)`：把 `reference.yaml` 里 `<Aligner>_index` 下各基因组版本的相对路径，拼上 `reference_path` 前缀变成绝对路径。已是绝对路径的跳过。

### 4.6 `resource_manager.py` — 资源档位（原样复用）

`rule_resource(config, profile_name, skip_queue_on_local=False, logger=None)`：
1. 从 `config['cluster_config']['resource_profiles']` 取出 `profile_name` 对应的 `{threads, mem_mb, runtime, queue_type, ...}`
2. **local 模式智能剥离 queue**：`execution_mode=='local'` 或 `queue_id=='default'` 且 `skip_queue_on_local=True` 时，移除 `queue/queue_type`，避免本地提交带队列参数报错
3. cluster 模式：优先用 `config['queue_id']`，否则按 `queue_type` 映射到具体队列名

rule 里用法：`resources: **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger)`

### 4.7 `tools.py` — 流程专用小工具（ATACFlow 新增，按需）

放流程特有的辅助函数，避免堆进 `common.py`。例：
- `get_java_opts(config, input, resources)`：按 `resources.mem_mb` 算 Java 堆内存
- `get_blacklist_path(config)`：按基因组版本取 blacklist 路径
- `get_organelle_names(config)`：取线粒体/叶绿体序列名（用于去除）

---

## 五、rule smk 标准写法 + 编号约定

### 5.1 rule 7 要素模板

**每条 rule 都齐备以下要素**（写新规则时的模板）：

```python
rule xxx:
    """
    Docstring：说明本规则做什么、产出什么、受哪些开关控制。
    """
    input:
        md5_check = "01.qc/md5_check.tsv",                          # 通常依赖 MD5 校验
        fastq     = os.path.join("00.raw_data", config['convert_md5'],
                                 "{sample}/{sample}_R1.fq.gz"),
    output:
        html = "01.qc/xxx/{sample}_xxx.html",
        zip  = "01.qc/xxx/{sample}_xxx.zip",
    resources:
        **rule_resource(config, 'low_resource',                      # ★ 资源档位
                        skip_queue_on_local=True, logger=logger),
    conda:
        workflow.source_path("../envs/fastqc.yaml"),                 # ★ 一工具一环境
    log:
        "logs/NN.xxx/{sample}.log",
    message:
        "Running XxxTool on {wildcards.sample}",                     # 进度提示
    benchmark:
        "benchmarks/{sample}_xxx.txt",                               # 资源消耗留痕
    params:
        out_dir = "01.qc/xxx/",
        extra   = config['parameter']['xxx']['extra'],
    threads:
        config['parameter']['threads']['fastqc'],                    # ★ 线程走 config
    shell:
        """
        xxx {input.fastq} -o {params.out_dir} --threads {threads} &> {log}
        """
```

**要点**：
- `conda` 用 `workflow.source_path("../envs/xxx.yaml")` 保证从任意 workdir 调用都能定位
- `input` 通常以 `01.qc/md5_check.tsv` 为依赖，确保数据完整性先校验
- `threads` 一律走 `config['parameter']['threads']['xxx']`，不硬编码
- `log` / `benchmark` 路径与 rule 同级编号，便于排障
- 跨样本聚合的 rule 用 `expand("...{sample}...", sample=samples.keys())` 做 input

### 5.2 编号约定（所有 Flow 沿用）

```
01.common.smk              # 公共函数导入（无 rule，只 import + 初始化 logger）
02.file_convert_md5.smk    # 数据入口：seq_preprocessor 建软链+MD5 → check_md5 校验
03.short_read_qc.smk       # FastQC + MultiQC（R1/R2 分开）
04.Contamination_check.smk # fastq_screen 污染检查
05.short_read_clean.smk    # fastp 接头/质量过滤
06.mapping.smk             # 比对 ★ 分水岭（RNA=STAR，ATAC=bowtie2/bwa2/chromap）
07~倒数第三                 # 流程特有分析（见各 Flow 的章节）
倒数第二.deliver.smk        # 交付：rnaflow-cli deliver（manifest.json + md5 + log）
最后.Report.smk            # 报告：generate_docker_json + docker run 生成 Quarto HTML
```

**三级目录约定**：
- 工作区：`00.raw_data / 01.qc / 02.mapping / 03.count / 04.variant / ...` + `logs/` + `benchmarks/`
- 交付区 `data_deliver/`：`report_data/`（报告数据）+ `Analysis_Report/`（最终 HTML）+ `delivery_manifest.json/md5` + `delivery_details.log`

---

## 六、数据流：raw_data → deliver → report

```
raw_data_path (只读)
    │
    │  02.file_convert_md5.smk
    ▼
00.raw_data/link_dir/{sample}/{sample}_R1.fq.gz  (+ raw_data_md5.json)
    │
    │  check_md5 → 01.qc/md5_check.tsv
    ▼
01.qc/  (FastQC / fastq_screen / fastp / MultiQC)
    │
    │  06.mapping.smk
    ▼
02.mapping/  (BAM + flagstat + stats + qualimap + BigWig + CRAM)
    │
    │  07+ 分析规则
    ▼
03.count / 04.variant / 05.assembly / 06.DEG / 07.AS / ...
    │
    │  DataDeliver() 收集所有 target（动态，按模块开关）
    ▼
NN.deliver.smk  →  data_deliver/
                      ├── delivery_manifest.json / .md5
                      ├── delivery_details.log
                      └── report_data/  (rnaflow-cli deliver --config report.yaml)
                                            │
                                            ▼
NN.Report.smk
  ├── generate_docker_json  →  report_data/project_summary.json
  └── Report (docker run)   →  data_deliver/Analysis_Report/index.html
```

**两条交付路径**（`deliver.smk` 里有两个 rule）：
1. `delivery`：全量交付，manifest 落到 `data_deliver/`
2. `delivery_report`：仅交付报告所需文件，manifest 落到 `data_deliver/report_data/`

**报告生成两步**（`Report.smk`）：
1. `generate_docker_json`：用 `run:` 块（Python）生成 `project_summary.json`（project_meta + stats + input_files，路径用容器内 `/data` 前缀）
2. `Report`：`docker run --rm -v ...:/data -v ...:/workspace -v json:/app/project_summary.json <image>` 生成 `Analysis_Report/index.html`

---

## 七、周边系统（envs/src/report/mcp/skills）

### 7.1 `envs/` — 一工具一 conda 环境
每个工具一个 yaml（如 `fastqc.yaml` / `star.yaml` / `macs2.yaml`），rule 里 `conda: workflow.source_path("../envs/xxx.yaml")` 引用。运行时 `--use-conda --conda-frontend mamba` 自动创建。

### 7.2 `src/` — 辅助脚本（git submodule）
放 Python/R 脚本：`DEG/`（DESeq2）、`Enrichments/`（GO/KEGG）、`gene_matrix/`（RSEM 合并）、`md5/`（编译好的 Rust 二进制）、`data-deliver/`（rnaflow-cli 配置）、`library_type/` 等。独立 git 仓库，`git submodule add` 引入。

### 7.3 `report/` — BioReport 系统（git submodule）
"Copy-Inject-Render" 模式：把分析结果注入 Quarto 模板渲染成 HTML。集成 AI 引擎（豆包/通义，支持 fallback + Token 统计）。docker 镜像 `bioreportxxx:vX`。目录：`bioreport/`（核心逻辑）+ `templates/`（Quarto 模板）+ `ai/`（AI 引擎）。

### 7.4 `mcp/` — MCP server（uv 管理）
基于 Model Context Protocol，用 `uv` 管理依赖。功能：
- 基因组查询（读 `reference.yaml` 的 `mcp_genome_version`）
- 配置生成（自动生成 `config.yaml` / `samples.csv` / `contrasts.csv`）
- 系统资源监控（CPU/内存/磁盘，提交任务前预警）
- run 管理（SQLite 记录每次运行，支持查询统计）
- 项目冲突检测（启动前查重）
- 异步执行（后台启动 Snakemake，不阻塞 AI）

### 7.5 `skills/` — AI Skills
让 Claude Code / Codex 通过自然语言驱动流程。包含：
- `SKILL.md`：技能定义（完整使用说明 + workflow）
- `path_config.yaml`：路径配置（`XXXFLOW_ROOT` 等，安装前需改）
- `start_xxxflow.sh`：增强启动脚本（conda 自检 + snakemake 可用性 + 用户确认）
- `install_skills.sh` / `install_codex_skills.sh`：自动安装到对应 AI 助手
- `examples/`：配置模板示例

---

## 八、ATACFlow 相对 RNAFlow 的框架演进

ATACFlow 是后写的，在框架层做了 5 处关键改进，**新 Flow 强烈建议采纳 ATACFlow 的写法**：

### 8.1 `DataDeliver` 用局部 `run_modules` 字典，不污染全局 config
- **RNAFlow**：直接 `config[module] = True`，有副作用，影响后续 rule 对 config 的读取
- **ATACFlow**：用局部 `run_modules = {}` 跟踪开关，全局 `config` 不变

### 8.2 `MODULE_DEPENDENCIES` 依赖自动补全
```python
MODULE_DEPENDENCIES = {
    "peak_calling": ["mapping"],
    "motif_analysis": ["peak_calling"],
    "consensus_peaks": ["peak_calling"],
    "diff_peaks": ["consensus_peaks"],
    "atac_qc": ["mapping"],
}
for module, deps in MODULE_DEPENDENCIES.items():
    if run_modules.get(module):
        for dep in deps:
            if not run_modules.get(dep):
                logger.warning(f"Module '{module}' requires '{dep}' but disabled. Auto-enabling.")
                run_modules[dep] = True
```
避免"开了下游却忘了开上游"导致 rule 找不到 input。

### 8.3 `functools.partial` 统一模块函数签名
- **RNAFlow**：`module_functions` 里各函数签名不一，循环里要 `if module=='rmats'` / `elif module=='mapping'` 特判
- **ATACFlow**：`partial(mapping, config=config)` / `partial(diff_peaks, run_pooled=run_pooled)` 预绑参数，调用统一为 `func(samples, data_deliver)`，循环干净

### 8.4 snakefile 第 4 段"预处理注入"
ATACFlow 在 `include` 之前算好 `merge_group/run_pooled`，塞进 `config['_merge_group']` / `config['_run_pooled']`，下游 rule 透明读取。新 Flow 若有类似的"需要从 samples/config 预计算的派生状态"，采用这种模式。

### 8.5 `tools.py` 单独成文件
流程专用小工具函数（`get_java_opts` / `get_blacklist_path` / `get_organelle_names`）放 `rules/utils/tools.py`，不堆进 `common.py`，保持 `common.py` 只放通用框架逻辑。

---

## 九、扩展新 Flow 完整 Checklist

### 9.1 不变（直接拷贝）
- [ ] snakefile 6 段骨架（改 Version / `<Aligner>_index` / include 列表 / `rule all` 的 `DataDeliver` 参数）
- [ ] `rules/utils/` 七大模块（`id_convert / validate / reference_update / resource_manager / __init__` 原样拷贝；`common.py` 改模块表；`datadeliver.py` 全替换；`tools.py` 按需）
- [ ] config 四件套结构（`config.yaml / reference.yaml / run_parameter.yaml / cluster_config.yaml`）+ `schema/config.schema.yaml`
- [ ] rule 7 要素写法
- [ ] 编号约定 + 三级目录
- [ ] `02.file_convert_md5.smk` / `03.short_read_qc.smk` / `04.Contamination_check.smk` / `05.short_read_clean.smk`（前 5 步所有 Flow 几乎一致，可复用）
- [ ] `NN.deliver.smk` / `NN.Report.smk`（收尾两步，换 `rnaflow-cli` 配置路径和 docker 镜像版本即可）
- [ ] `envs/` 共享环境（fastqc / fastp / multiqc / fastq_screen / samtools / picard / qualimap / bcftools / gatk / deeptools / mosdepth / py3.12 等可直接复用）
- [ ] `data/`（adapter fasta + fastq_screen 模板）
- [ ] `report/` / `mcp/` / `skills/` 周边结构（作为 submodule 引入，改 `start_xxxflow.sh` / `path_config.yaml` / docker 镜像名）

### 9.2 要改（按分析内容定制）

| 改动点 | 具体做什么 |
|--------|-----------|
| `rules/utils/datadeliver.py` | 替换模块函数为该 Flow 的分析产出（`qc_clean / mapping / <分析模块>...`）|
| `rules/utils/common.py` 的 `DataDeliver` | 改 `basic_modules / downstream_modules / MODULE_DEPENDENCIES / module_functions` 四张表（采纳 ATACFlow 的 partial + 局部字典 + 依赖补全写法）|
| `06` 之后的 `.smk` | 写真正的分析规则（**这是你重点编写的部分**）|
| `config/reference.yaml` | 换索引类型（`STAR_index` → `Bowtie2_index` / `BWA_index` / `Chromap_index` / ...）+ 流程特有字段 |
| `config/run_parameter.yaml` | 换 `parameter.threads` 和工具参数 + 流程特有工具参数块 |
| `config/config.yaml` | 换 `pipeline_version` + 流程特有配置块（如 `peak_calling` / `mapping_tools`）|
| `schema/config.schema.yaml` | 改 `Genome_Version` enum + 模块开关字段 + 索引结构定义 |
| `config/cluster_config.yaml` | 按流程工具资源需求调整四档 profile（通常不用大改）|
| `report/` docker 镜像 | `bioreportxxx:vX`（新建对应报告镜像）|
| `envs/` | 新增流程特有工具的环境（如 `macs2.yaml` / `tobias.yaml`）|
| `rules/utils/tools.py`（可选）| 流程专用小工具函数 |

### 9.3 从零创建 NewFlow 的步骤

```bash
# 1. 复制骨架（以 ATACFlow 为模板，因为它框架更新）
cp -r ATACFlow/ NewFlow/
cd NewFlow/

# 2. 全局改名
find . -type f -name "*.smk" -o -name "*.yaml" -o -name "*.py" -o -name "*.md" -o -name "*.sh" \
  | xargs sed -i 's/ATACFlow/NewFlow/g; s/atacflow/newflow/g; s/ATAC/New/g'

# 3. 清理分析逻辑层
rm rules/0[7-9]*.smk rules/1[0-1]*.smk   # 删除 ATAC 特有分析规则
# 重写 rules/utils/datadeliver.py（按 NewFlow 的模块）
# 改 rules/utils/common.py 的 DataDeliver 四张表
# 改 rules/01.common.smk 的 import（按新 datadeliver 函数名）

# 4. 改配置
# config/reference.yaml：换索引类型 + 基因组版本
# config/run_parameter.yaml：换 threads + 工具参数
# config/config.yaml：换 pipeline_version + 流程特有块
# schema/config.schema.yaml：换 enum + 开关字段

# 5. 写分析规则（重点）
# rules/07.xxx.smk ~ rules/NN.xxx.smk

# 6. 收尾
# rules/NN.deliver.smk：换 rnaflow-cli 配置路径
# rules/NN.Report.smk：换 docker 镜像版本
# report/ 子模块：换报告镜像
# skills/start_newflow.sh + path_config.yaml

# 7. 冒烟测试
snakemake -n --config analysisyaml=test_config.yaml   # dry run
snakemake --cores 1 --use-conda --config analysisyaml=test_config.yaml  # 单样本跑通
```

---

## 十、命名约定与最佳实践

### 10.1 命名约定
- **Flow 名**：`<DataType>Flow`（RNAFlow / ATACFlow / WGSFlow / ChIPFlow），PascalCase
- **配置项**：统一 `snake_case`（RNAFlow v0.1.9+ 已迁移，如 `noval_Transcripts` → `detect_novel_transcripts`）
- **规则文件**：`NN.<module>.smk`，两位数字编号，模块名小写
- **目录**：`NN.<module>/`（`00.raw_data / 01.qc / 02.mapping / ...`），与规则编号对应
- **conda 环境**：`<tool>.yaml`（小写，工具名）
- **基因组版本**：与 UCSC / Ensembl 官方一致（`hg38` / `GRCm39` / `ITAG4.1`）

### 10.2 最佳实践
1. **`datadeliver.py` 的路径必须与 rule `output` 完全一致**——这是框架最易错点，改 output 必同步改 datadeliver
2. **`load_samples` 只生成路径不检查存在性**——IO 检查留给 snakemake 的依赖解析
3. **资源走 `rule_resource`，不硬编码**——local/cluster 自动适配
4. **conda 环境一工具一个**——避免依赖冲突，`--use-conda` 自动管理
5. **`only_qc` 开关统一处理**——`DataDeliver` 里集中跳过下游模块
6. **依赖自动补全**——用 `MODULE_DEPENDENCIES` 避免"开下游忘开上游"
7. **交付与报告分离**——`deliver.smk` 两个 rule（全量 + 报告专用），`Report.smk` 两步（json + docker）
8. **改完 utils 必须 runtime 冒烟**——`py_compile` 不够，snakemake 的 import 时机和普通 Python 不同，改构造签名后必须实际跑一次 `snakemake -n` 或单样本执行
9. **Celery/worker 类组件改完要 restart**——若 Flow 接入 OmicHub 调度，worker 不热重载，改 task 代码后必须 `docker restart omichub-worker`

### 10.3 版本管理
- 每个 Flow 独立版本号（`pipeline_version`），写在 `config.yaml` 和 snakefile 头部
- `src/` / `report/` 用 git submodule，独立版本
- `envs/` 环境锁定版本，保证可复现

---

**维护者**：JZHANG  
**基于版本**：RNAFlow v0.1.9 / ATACFlow v0.0.6  
**最后更新**：2026-07-07
