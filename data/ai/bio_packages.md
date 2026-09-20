# 生物信息软件包目录

> 本目录由 Agent YAML 的 `package_catalogs` 自动选择并注入提示词。它提供候选包与用途，不是已安装清单：每次安装前都必须用 `conda-meta-mcp` 查询当前可用的 conda 包名、channel 和版本，并以实际导入/CLI 输出为准。Studio 沙盒只允许通过 `micromamba install -y -n base ...` 安装；不得使用 `pip install`、`install.packages()` 或 GitHub 安装。

<!-- package-catalog: genomics -->
##### 1 基因组学 / 序列分析

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `biopython` | FASTA/FASTQ/GenBank 解析、BLAST 接口、翻译与 motif | `micromamba install -y -n base -c conda-forge biopython` |
| `pysam` | BAM/CRAM/SAM/VCF/BCF 读取与操作 | `micromamba install -y -n base -c bioconda pysam` |
| `pyfaidx` | 快速索引读取 FASTA | 查询可用 conda 包后安装 |
| `pybedtools` | BED/GTF/GFF 区间操作 | `micromamba install -y -n base -c bioconda pybedtools` |
| `pysamstats` | BAM 文件统计信息 | `micromamba install -y -n base -c bioconda pysamstats` |
| `cyvcf2` | 高性能 VCF/BCF 解析 | `micromamba install -y -n base -c bioconda cyvcf2` |
| `mappy` | minimap2 的 Python 接口，长读序列比对 | `micromamba install -y -n base -c bioconda mappy` |

<!-- package-catalog: rnaseq -->
##### 2 转录组学 / RNA-seq

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `pysam` | BAM 基础操作 | `micromamba install -y -n base -c bioconda pysam` |
| `HTSeq` | 计数矩阵生成 | `micromamba install -y -n base -c bioconda htseq` |
| `rpy2` | 在 Python 中调用 R/Bioconductor | `micromamba install -y -n base -c conda-forge rpy2` |
| `pydeseq2` | Python 差异表达分析 | 查询可用 conda 包后安装 |
| `gseapy` | GSEA / ORA 富集分析 | `micromamba install -y -n base -c bioconda gseapy` |

<!-- package-catalog: scrna -->
##### 3 单细胞分析

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `scanpy` | 单细胞分析主框架 | `micromamba install -y -n base -c conda-forge scanpy` |
| `anndata` | 单细胞数据格式 | `micromamba install -y -n base -c conda-forge anndata` |
| `mudata` / `muon` | CITE-seq、scATAC+RNA 等多模态分析 | 查询可用 conda 包后安装 |
| `scvi-tools` | scVI、totalVI、DestVI 等深度学习模型 | `micromamba install -y -n base -c conda-forge scvi-tools` |
| `scarches` / `celltypist` | 参考映射与细胞类型注释 | 查询可用 conda 包后安装 |
| `squidpy` | 空间转录组分析 | `micromamba install -y -n base -c conda-forge squidpy` |
| `decoupler` / `omnipath` | 通路活性与信号网络推断 | 查询可用 conda 包后安装 |
| `scikit-misc` | Scanpy 绘图等依赖 | `micromamba install -y -n base -c conda-forge scikit-misc` |

<!-- package-catalog: r-bio -->
##### R / Bioconductor 统计与单细胞

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `Seurat` / `SeuratObject` | R 单细胞分析与对象管理 | `micromamba install -y -n base -c conda-forge r-seurat` |
| `SingleCellExperiment` / `scater` / `scran` | Bioconductor 单细胞对象、QC 与归一化 | 查询可用 bioconda 包后安装 |
| `Harmony` / `SeuratDisk` | 批次整合、Seurat 与 H5AD 转换 | 查询可用 conda 包后安装 |
| `DESeq2` / `edgeR` / `limma` | 差异表达与 voom 分析 | 查询可用 bioconda 包后安装 |
| `clusterProfiler` / `org.Hs.eg.db` / `org.Mm.eg.db` | 富集分析与物种注释 | 查询可用 bioconda 包后安装 |
| `tximport` | 转录本定量汇总 | 查询可用 bioconda 包后安装 |
| `pheatmap` / `RColorBrewer` | R 可视化 | 查询可用 conda 包后安装 |

R 包安装后以 `Rscript -e "library(<Pkg>); packageVersion('<Pkg>')"` 验证。若目录或查询结果中没有可用 conda 包，不得绕过协议改用 CRAN/GitHub 安装。

<!-- package-catalog: epigenomics -->
##### 4 表观遗传学 / 染色质

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `pyBigWig` | BigWig/BigBed 文件读写 | `micromamba install -y -n base -c bioconda pybigwig` |
| `pybedtools` | BED 区间操作 | `micromamba install -y -n base -c bioconda pybedtools` |
| `episcanpy` | 单细胞表观遗传分析 | 查询可用 conda 包后安装 |
| `MACS3` | ChIP-seq/ATAC-seq peak calling | `micromamba install -y -n base -c bioconda macs3` |
| `deepTools` | 信号可视化与质控 | `micromamba install -y -n base -c bioconda deeptools` |
| `hicexplorer` / `cooler` | Hi-C 数据分析与 `.cool` 操作 | 查询可用 conda 包后安装 |

<!-- package-catalog: proteomics -->
##### 5 蛋白质组学 / 结构生物学

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `biopython` / `biotite` | PDB、序列、结构与进化分析 | 查询可用 conda 包后安装 |
| `mdanalysis` / `mdtraj` | 分子动力学轨迹分析 | `micromamba install -y -n base -c conda-forge mdanalysis mdtraj` |
| `openmm` / `pdbfixer` | 分子动力学模拟与结构修复 | 查询可用 conda 包后安装 |
| `prody` / `nglview` | 结构动力学与交互式分子可视化 | 查询可用 conda 包后安装 |
| `py3Dmol` | Jupyter/网页分子结构可视化 | 查询可用 conda 包后安装 |

<!-- package-catalog: microbiome -->
##### 6 微生物组学 / 宏基因组

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `qiime2` | 16S 与宏基因组分析平台 | 查询对应 QIIME2 channel 后安装 |
| `scikit-bio` | 微生物组统计与距离矩阵 | `micromamba install -y -n base -c conda-forge scikit-bio` |
| `biom-format` | BIOM 格式处理 | `micromamba install -y -n base -c bioconda biom-format` |
| `humann` / `metaphlan` | 宏基因组功能与物种注释 | 查询可用 bioconda 包后安装 |
| `kraken2` / `bracken` | 宏基因组分类 | 查询可用 bioconda 包后安装 |

<!-- package-catalog: variants -->
##### 7 变异分析与群体遗传

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `cyvcf2` | 高性能 VCF 解析 | `micromamba install -y -n base -c bioconda cyvcf2` |
| `scikit-allel` / `sgkit` | VCF、Zarr、PCA 与群体遗传分析 | 查询可用 conda 包后安装 |
| `tskit` / `msprime` / `stdpopsim` | 树序列和群体遗传模拟 | 查询可用 conda 包后安装 |

<!-- package-catalog: phylo -->
##### 8 系统发育 / 进化

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `ete3` | 系统发育树可视化与操作 | 查询可用 conda 包后安装 |
| `dendropy` / `biopython` | 树计算与 Newick/Nexus/PhyloXML 解析 | 查询可用 conda 包后安装 |
| `toytree` / `phyluce` | 树绘图与 UCE 分析 | 查询可用 conda 包后安装 |

<!-- package-catalog: enrichment -->
##### 9 通路富集与功能注释

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `gseapy` | GSEA / ORA 富集分析 | `micromamba install -y -n base -c bioconda gseapy` |
| `goatools` / `enrichr` | GO 与 Enrichr 接口 | 查询可用 conda 包后安装 |
| `reactome2py` / `keggutils` | Reactome、KEGG 接口 | 查询可用 conda 包后安装 |
| `clusterProfiler` | R/Bioconductor 富集分析 | 见 R / Bioconductor 分类，并先查询验证 |

<!-- package-catalog: io -->
##### 10 数据格式与 IO

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `anndata` | 单细胞 AnnData 格式 | `micromamba install -y -n base -c conda-forge anndata` |
| `zarr` / `xarray` | 大规模 N 维数组与带标签数据 | `micromamba install -y -n base -c conda-forge zarr xarray` |
| `h5py` / `pyarrow` | HDF5、Parquet 与 Arrow 数据读写 | `micromamba install -y -n base -c conda-forge h5py pyarrow` |
| `tiledb` | 基因组区间数据库 | 查询可用 conda 包后安装 |
| `pydantic` | API/配置数据模型验证 | `micromamba install -y -n base -c conda-forge pydantic` |
| `fsspec` / `s3fs` | 本地与对象存储文件系统接口 | 查询可用 conda 包后安装 |

<!-- package-catalog: visualization -->
##### 11 生信专用可视化

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `matplotlib` / `seaborn` / `plotly` | 静态与交互式统计图表 | 以当前运行时清单为准；缺失时先查询 |
| `bokeh` / `altair` | 交互式网页与声明式可视化 | 查询可用 conda 包后安装 |
| `pygenometracks` | 基因组浏览器式轨道图 | 查询可用 bioconda 包后安装 |
| `karyoploteR` / `circlize` | R 染色体核型图与 circos 圈图 | 查询可用 conda 包后安装 |
| `pyCircos` | Python circos 图 | 查询可用 conda 包后安装 |

<!-- package-catalog: machine-learning -->
##### 12 生信机器学习 / 深度学习

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `scvi-tools` / `scarches` / `celltypist` | 单细胞 VAE、参考映射与分类 | 查询可用 conda 包后安装 |
| `scikit-learn` | 经典机器学习 | 以当前运行时清单为准；缺失时先查询 |
| `xgboost` / `lightgbm` | 梯度提升分类与回归 | 查询可用 conda 包后安装 |
| `pytorch` | 深度学习框架 | 查询当前 CUDA/CPU 兼容包后安装 |
| `transformers` / `fair-esm` / `bio-embeddings` | 生物序列预训练模型与嵌入 | 查询可用 conda 包后安装 |

<!-- package-catalog: network -->
##### 13 网络与图分析

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `networkx` / `python-igraph` | 图与网络分析 | 查询可用 conda 包后安装 |
| `omnipath` | 信号通路与蛋白互作网络 | 查询可用 conda 包后安装 |
| `snap-stanford` | 大规模网络分析 | 查询可用 conda 包后安装 |

<!-- package-catalog: cheminformatics -->
##### 14 化学信息学（Cheminformatics）

| 包 | 用途 | 候选安装方式（均需先查询） |
|---|---|---|
| `rdkit` | 化学结构操作、分子描述符与 SMILES | `micromamba install -y -n base -c conda-forge rdkit` |
| `openbabel` | PDB、SDF、SMILES 等格式转换 | 查询可用 conda 包后安装 |
| `pubchempy` | PubChem 数据库接口 | 查询可用 conda 包后安装 |
| `chempy` | 化学平衡与动力学计算 | `micromamba install -y -n base -c conda-forge chempy` |
