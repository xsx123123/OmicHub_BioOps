# 分析流程扩展

OmicHub 采用 **YAML 声明式 + 通用构建器** 的架构接入不同的 Snakemake 分析流程。新增流程通常只需在 `flows/` 目录下添加 YAML 配置文件。

## 流程加载方式

1. 服务启动后，首次访问 `/api/v1/flows` 时懒加载 `flows/` 下所有 `*.yaml` / `*.yml` 文件；
2. `FlowDomainService` 用 Pydantic 模型校验结构、参数唯一性、条件渲染引用等；
3. 校验通过的流程以 `meta.id` 为唯一键缓存在内存中；
4. 新增或修改 YAML 后，调用 `POST /api/v1/flows/reload` 热重载，无需重启服务。

## 核心设计

`TaskService` 不再针对每个流程写 `if-elif`，而是统一调用 `GenericFlowBuilder`，动态完成：

- 生成主配置文件（`config.yaml` / `analysis.yaml` 等，由 `execution.config_file_name` 指定）；
- 生成样本表 `samples.csv`；
- 生成差异比较组表 `contrasts.csv`（可选）；
- 注入动态计算字段（工作目录、样本表路径、比较组路径）。

## 新增流程步骤

以新增 `chip_seq` 为例：

### 1. 创建 YAML

文件 `flows/chip_seq.yaml`，至少包含：

- `meta`：流程元信息，`id` 必须全局唯一且符合 `^[a-z][a-z0-9_]*$`；
- `parameters`：前端动态表单参数定义；
- `execution`：Snakefile 路径、资源配置、主配置文件名；
- `sample_sheet`：样本表校验规则；
- `pipeline_mapping`：参数到底层流程输入文件的映射规则。

### 2. 编写 `pipeline_mapping`

```yaml
pipeline_mapping:
  config_fields:           # 直接写入主配置文件的字段
    - project_name
    - Genome_Version
    - species
    - raw_data_path
    - peak_calling.macs2_qvalue   # 支持点号生成嵌套字典
  computed_fields:         # 由构建器动态注入的字段
    workflow: "__work_dir__"
    sample_csv: "__samples_csv__"
    paired_csv: "__contrasts_csv__"
  list_fields:             # 强制转为字符串列表的字段
    - raw_data_path
  sample_sheet:
    output_name: "samples.csv"
    columns:
      sample: sample
      sample_name: sample_name
      group: group
  comparisons:
    output_name: "contrasts.csv"
    columns:
      Control: Control
      Treat: Treat
```

### 3. 放置 Snakefile

确保 `execution.snakefile` 指向的 Snakemake 文件存在，并能读取生成的配置文件。

### 4. 热重载

```bash
curl -X POST http://localhost:8000/api/v1/flows/reload \
     -H "Authorization: Bearer <token>"
```

或直接重启后端服务。

### 5. 前端使用

- 访问 `/api/v1/flows/chip_seq/schema` 获取参数 JSON Schema，前端据此渲染表单；
- 提交任务时 `/api/v1/tasks/submit` 的 `flow_id` 填 `chip_seq`。

## 已有流程参考

- `flows/rna_seq.yaml` — RNAFlow 流程，主配置文件 `config.yaml`
- `flows/atac_seq.yaml` — ATACFlow 流程，主配置文件 `analysis.yaml`

## 注意事项

- `meta.id` 一旦确定尽量不要修改，数据库中的任务记录会关联该 ID；
- `pipeline_mapping` 缺失的流程只会被展示和解析，**无法提交执行**；
- 若某字段需要嵌套结构（如 `peak_calling.use_pooled_peaks`），在 `config_fields` 中使用点号路径；
- 所有字段默认值、动态占位符、类型转换规则均可在 `pipeline_mapping` 中声明。
