export interface PendingWorkflow {
  id: string
  name: string
  version: string
  badge: string
  status: 'UNDER_REVIEW'
  description: string
  tags: string[]
  category: 'all'
}

/** 前端预研流程：后端流程配置完成审核后可移除对应项，由接口数据接管。 */
export const PENDING_WORKFLOWS: PendingWorkflow[] = [
  {
    id: 'scrna-seq',
    name: 'scRNA-seq 单细胞转录组分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 scRNAFlow 流程（CellRanger + Seurat + DoubletFinder）的标准 scRNA-seq 分析。提交后自动生成 scRNAFlow 所需 config.yaml、samples.csv、metadata.csv。',
    tags: ['scrnaseq', 'single-cell', 'CellRanger', 'Seurat', 'DoubletFinder', 'scRNAFlow'],
    category: 'all',
  },
  {
    id: 'cuttag',
    name: 'Cut&Tag 染色质图谱与修饰分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 CutTagFlow 流程（Bowtie2 + SEACR + deepTools）的标准 Cut&Tag 分析。提交后自动生成 CutTagFlow 所需 config.yaml、samples.csv、peaks.json。',
    tags: ['cuttag', 'chromatin-profiling', 'Bowtie2', 'SEACR', 'deepTools', 'CutTagFlow'],
    category: 'all',
  },
  {
    id: 'vdj',
    name: 'VDJ 免疫组库全长测序分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 VDJFlow 流程（MiXCR + TRUST4 + Immunarch）的标准 VDJ 免疫组库分析。提交后自动生成 VDJFlow 所需 config.yaml、samples.csv、clonotypes.csv。',
    tags: ['vdj', 'immune-repertoire', 'MiXCR', 'TRUST4', 'Immunarch', 'VDJFlow'],
    category: 'all',
  },
  {
    id: 'wes',
    name: 'WES 全外显子组测序突变分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 ExomeFlow 流程（BWA-MEM + GATK4 + Mutect2）的标准 WES 外显子组分析。提交后自动生成 ExomeFlow 所需 config.yaml、samples.csv、targets.bed。',
    tags: ['wes', 'exome-sequencing', 'BWA', 'GATK4', 'Mutect2', 'ExomeFlow'],
    category: 'all',
  },
  {
    id: 'wgs',
    name: 'WGS 全基因组重测序分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 WGSFlow 流程（BWA-MEM2 + GATK4 + Manta）的标准 WGS 全基因组分析。提交后自动生成 WGSFlow 所需 config.yaml、samples.csv、intervals.bed。',
    tags: ['wgs', 'whole-genome', 'BWA-MEM2', 'GATK4', 'Manta', 'WGSFlow'],
    category: 'all',
  },
  {
    id: 'gwas',
    name: 'GWAS 全基因组关联分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 GWASFlow 流程（PLINK + GEMMA + CMplot）的标准 GWAS 表型关联分析。提交后自动生成 GWASFlow 所需 config.yaml、phenotypes.csv、covariates.txt。',
    tags: ['gwas', 'association-study', 'PLINK', 'GEMMA', 'CMplot', 'GWASFlow'],
    category: 'all',
  },
  {
    id: 'bsa',
    name: 'BSA 混池分离与性状定位分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 BSAFlow 流程（BWA + GATK4 + QTLseqr）的标准 BSA 基因快速定位分析。提交后自动生成 BSAFlow 所需 config.yaml、pools.csv、chromosomes.txt。',
    tags: ['bsa', 'bulked-segregant', 'BWA', 'GATK4', 'QTLseqr', 'BSAFlow'],
    category: 'all',
  },
  {
    id: 'bsr-seq',
    name: 'BSR-seq 转录组混池定位分析',
    version: 'v0.1.0',
    badge: '专家审核中',
    status: 'UNDER_REVIEW',
    description: '基于已搭建好的 BSRFlow 流程（STAR + GATK4 + QTLseqr）的标准 BSR-seq 连锁分析。提交后自动生成 BSRFlow 所需 config.yaml、samples.csv、contrasts.csv。',
    tags: ['bsrseq', 'transcriptome-bsa', 'STAR', 'GATK4', 'QTLseqr', 'BSRFlow'],
    category: 'all',
  },
]
