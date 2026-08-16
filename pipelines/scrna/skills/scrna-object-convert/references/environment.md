# scrna-object-convert 环境依赖清单

两个脚本均为 R 脚本（getopt CLI），H5AD 读写经由 reticulate 调用 Python。上架前请对照沙盒运行时画像核对以下依赖。

## R 环境

- R ≥ 4.2（开发验证环境为 R 4.5.1）

### 必需 R 包（两个脚本共同）

| 包 | 用途 |
|---|---|
| Seurat (5.x) | 对象读写与操作；脚本对 v5 的 Assay5 自动降级为 Assay |
| getopt | CLI 参数解析 |
| log4r | 日志（RDS_convert 生成 RDS_convert-<时间戳>-<用户>.log） |
| yaml | 配置/信息输出 |
| stringr | 字符串处理 |
| crayon | 终端着色输出 |
| praise | 完成提示语 |

### 按需 R 包（依目标格式/操作加载）

| 包 | 何时需要 |
|---|---|
| sceasy | RDS ↔ SCE/AnnData 转换 |
| loomR | Loom 格式读写 |
| SeuratDisk | H5AD/H5Seurat 读写 |
| reticulate | 调用 Python（H5AD 转换必需） |

安装参考：

```r
install.packages(c("Seurat", "getopt", "log4r", "yaml", "stringr", "crayon", "praise", "reticulate"))
# sceasy / loomR / SeuratDisk 来自 GitHub：
# remotes::install_github("cellgeni/sceasy")
# remotes::install_github("mojaveazure/loomR", ref = "develop")
# remotes::install_github("mojaveazure/seurat-disk")
```

## Python 环境（经 reticulate）

| 包 | 用途 |
|---|---|
| scanpy | H5AD 读写入口 |
| anndata | AnnData 对象结构 |

环境注入方式：默认由 reticulate 自动探测当前 Python/conda 环境；RDS_convert 可用 `--conda-env <环境名>` 显式指定。环境缺失 scanpy/anndata 时 H5AD 转换会报错，需先在目标 Python 环境中安装：

```bash
pip install scanpy anndata
```

## 自查命令

```bash
Rscript scripts/RDS_convert --help
Rscript scripts/RDS_utility --help
Rscript -e 'invisible(parse("scripts/RDS_convert"))'   # 缺包时的语法兜底检查
```
