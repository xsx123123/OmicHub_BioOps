/**
 * 数据库模块 mock 数据。
 *
 * 当前仍是前端静态数据，结构按 PRD 升级为 Species -> GenomeVersion -> DataFiles，
 * 后续可直接替换为 /api/database 或扩展后的 JBrowse 配置接口。
 */

export type DatabaseCategory = 'plant' | 'animal' | 'microbe'
export type GenomeVersionStatus = 'active' | 'archived'
export type BuildStatus = 'ready' | 'building' | 'missing' | 'error'
export type DataFileType = 'fasta' | 'gff' | 'go' | 'kegg'
export type GeneStrand = '+' | '-'
export type GeneStatus = 'REVIEWED' | 'VALIDATED' | 'PROVISIONAL' | 'PREDICTED' | 'MODEL'
export type GeneType = 'protein_coding' | 'lncRNA' | 'pseudogene' | 'transposable_element' | 'other'

export interface DatabaseDataFile {
  type: DataFileType
  label: string
  path: string
  indexPath?: string
  dbPath?: string
  format: string
  size: string
  buildRequired: boolean
  buildTool?: string
  buildStatus: BuildStatus
}

export interface GenomeVersionStats {
  chromosomes: number
  totalGenes: number
  proteinCoding: number
  genomeSize: string
  n50: string
}

export interface GenomeVersion {
  versionId: string
  versionName: string
  assemblyName: string
  isDefault: boolean
  status: GenomeVersionStatus
  releaseDate: string
  description: string
  tags: string[]
  stats: GenomeVersionStats
  dataFiles: Partial<Record<DataFileType, DatabaseDataFile>>
}

export interface VersionMapping {
  source: string
  target: string
  mappingTool: string
  mappingFile: string
  buildStatus: BuildStatus
  mappedGenes: number
  averageQuality: number
}

export interface SpeciesDatabase {
  id: string
  scientificName: string
  commonName: string
  taxonomyId: string
  description: string
  icon: string
  category: DatabaseCategory
  gradient: string
  genomeVersions: GenomeVersion[]
  versionMappings: VersionMapping[]
}

/** 兼容旧页面命名：一个 Genome 表示某物种的某个基因组版本。 */
export interface Genome {
  id: string
  speciesId: string
  speciesEmoji: string
  commonName: string
  latinName: string
  taxonomyId: string
  version: string
  versionFull: string
  tags: string[]
  chromosomes: number
  totalGenes: number
  proteinCoding: number
  genomeSize: string
  n50: string
  releaseDate: string
  status: GenomeVersionStatus
  isDefault: boolean
  description: string
  category: DatabaseCategory
  gradient: string
  dataFiles: Partial<Record<DataFileType, DatabaseDataFile>>
}

export interface Chromosome {
  name: string
  length: number
  color: string
}

export interface GeneTranscript {
  transcriptId: string
  biotype: GeneType
  length: number
  cdsStart: number
  cdsEnd: number
  lengthAa: number
  exons: Array<{ start: number; end: number; rank: number }>
  canonical?: boolean
}

export interface GOAnnotation {
  goId: string
  term: string
  namespace: 'BP' | 'MF' | 'CC'
  evidenceCode: string
  source: string
}

export interface KEGGAnnotation {
  pathwayId: string
  pathwayName: string
  category: string
  koId?: string
  ecNumber?: string
  genesInPathway: number
}

export interface GeneSequence {
  genomic: string
  cds: string
  protein: string
}

export interface GeneVersionMapping {
  targetVersionId: string
  targetGeneId: string
  sourceLocation: string
  targetLocation: string
  mappingQuality: number
  mappingTool: string
}

export interface Gene {
  geneId: string
  geneSymbol: string
  geneName: string
  geneType: GeneType
  status: GeneStatus
  description: string
  speciesId: string
  genomeVersionId: string
  chromosome: string
  start: number
  end: number
  strand: GeneStrand
  aliases: string[]
  transcripts: GeneTranscript[]
  goAnnotations: GOAnnotation[]
  keggAnnotations: KEGGAnnotation[]
  sequence: GeneSequence
  versionMappings: GeneVersionMapping[]
}

export interface GeneTypeStat {
  name: string
  value: number
  color: string
}

export interface DatabaseSummary {
  totalSpecies: number
  totalVersions: number
  totalGenes: number
  readyFiles: number
  totalFiles: number
}

const DATA_ROOT = '/data/omichub/omichub_data/db'

function dataFile(
  type: DataFileType,
  versionPath: string,
  filename: string,
  options: Partial<Omit<DatabaseDataFile, 'type' | 'path' | 'label'>> = {},
): DatabaseDataFile {
  const labelMap: Record<DataFileType, string> = {
    fasta: 'FASTA 序列',
    gff: 'GFF 注释',
    go: 'GO 注释',
    kegg: 'KEGG 通路',
  }
  return {
    type,
    label: labelMap[type],
    path: `${DATA_ROOT}/${versionPath}/${filename}`,
    format: options.format ?? (type === 'fasta' ? 'fasta' : type === 'gff' ? 'gff3' : 'tsv'),
    size: options.size ?? '-',
    buildRequired: options.buildRequired ?? true,
    buildTool: options.buildTool,
    buildStatus: options.buildStatus ?? 'ready',
    indexPath: options.indexPath,
    dbPath: options.dbPath,
  }
}

export const DATABASE_SPECIES: SpeciesDatabase[] = [
  {
    id: 'Lsat',
    scientificName: 'Lactuca sativa',
    commonName: '生菜',
    taxonomyId: '4236',
    description: '生菜多版本参考基因组与功能注释库',
    icon: '🥬',
    category: 'plant',
    gradient: 'linear-gradient(90deg, #165DFF, #722ED1)',
    genomeVersions: [
      {
        versionId: 'Lsat_v11',
        versionName: 'v11',
        assemblyName: 'Lsat.1.v11',
        isDefault: true,
        status: 'active',
        releaseDate: '2023-05',
        description: '最新版染色体级组装，包含 FA/GFF/GO/KEGG 完整注释',
        tags: ['最新版', '染色体级', '完整注释'],
        stats: {
          chromosomes: 9,
          totalGenes: 38678,
          proteinCoding: 34210,
          genomeSize: '2.69 Gb',
          n50: '120 Mb',
        },
        dataFiles: {
          fasta: dataFile('fasta', 'Lsat/v11', 'Lsat.1.v11.fa', {
            size: '2.1 Gb',
            indexPath: `${DATA_ROOT}/Lsat/v11/Lsat.1.v11.fa.fai`,
            buildTool: 'samtools faidx',
          }),
          gff: dataFile('gff', 'Lsat/v11', 'Lsat.1.v11.gff3', {
            size: '156 Mb',
            dbPath: `${DATA_ROOT}/Lsat/v11/annotation.db`,
            buildTool: 'gffutils',
          }),
          go: dataFile('go', 'Lsat/v11', 'go_annotations.tsv', {
            size: '18 Mb',
            dbPath: `${DATA_ROOT}/Lsat/v11/go.db`,
            buildTool: 'custom',
          }),
          kegg: dataFile('kegg', 'Lsat/v11', 'kegg_annotations.tsv', {
            size: '12 Mb',
            dbPath: `${DATA_ROOT}/Lsat/v11/kegg.db`,
            buildTool: 'custom',
          }),
        },
      },
      {
        versionId: 'Lsat_v8',
        versionName: 'v8',
        assemblyName: 'Lsat.1.v8',
        isDefault: false,
        status: 'active',
        releaseDate: '2020-11',
        description: '稳定版染色体级组装，适合历史项目复现',
        tags: ['稳定版', '染色体级'],
        stats: {
          chromosomes: 9,
          totalGenes: 35241,
          proteinCoding: 31100,
          genomeSize: '2.65 Gb',
          n50: '95 Mb',
        },
        dataFiles: {
          fasta: dataFile('fasta', 'Lsat/v8', 'Lsat.1.v8.fa', {
            size: '2.0 Gb',
            indexPath: `${DATA_ROOT}/Lsat/v8/Lsat.1.v8.fa.fai`,
            buildTool: 'samtools faidx',
          }),
          gff: dataFile('gff', 'Lsat/v8', 'Lsat.1.v8.gff3', {
            size: '141 Mb',
            dbPath: `${DATA_ROOT}/Lsat/v8/annotation.db`,
            buildTool: 'gffutils',
          }),
          go: dataFile('go', 'Lsat/v8', 'go_annotations.tsv', {
            size: '14 Mb',
            dbPath: `${DATA_ROOT}/Lsat/v8/go.db`,
            buildStatus: 'ready',
          }),
          kegg: dataFile('kegg', 'Lsat/v8', 'kegg_annotations.tsv', {
            size: '-',
            buildStatus: 'missing',
          }),
        },
      },
    ],
    versionMappings: [
      {
        source: 'Lsat_v8',
        target: 'Lsat_v11',
        mappingTool: 'liftoff',
        mappingFile: `${DATA_ROOT}/Lsat/mappings/v8_to_v11_mapping.tsv`,
        buildStatus: 'ready',
        mappedGenes: 34412,
        averageQuality: 0.96,
      },
    ],
  },
  {
    id: 'Ath',
    scientificName: 'Arabidopsis thaliana',
    commonName: '拟南芥',
    taxonomyId: '3702',
    description: '模式植物拟南芥 TAIR10 注释库',
    icon: '🌱',
    category: 'plant',
    gradient: 'linear-gradient(90deg, #0FC6C2, #165DFF)',
    genomeVersions: [
      {
        versionId: 'Ath_TAIR10',
        versionName: 'TAIR10',
        assemblyName: 'TAIR10',
        isDefault: true,
        status: 'active',
        releaseDate: '2010-12',
        description: '经典模式植物参考版本，GO/KEGG 注释完整',
        tags: ['模式植物', '稳定版'],
        stats: {
          chromosomes: 5,
          totalGenes: 27655,
          proteinCoding: 27416,
          genomeSize: '135 Mb',
          n50: '30.4 Mb',
        },
        dataFiles: {
          fasta: dataFile('fasta', 'Ath/TAIR10', 'TAIR10.fa', { size: '119 Mb' }),
          gff: dataFile('gff', 'Ath/TAIR10', 'TAIR10.gff3', { size: '82 Mb', dbPath: `${DATA_ROOT}/Ath/TAIR10/annotation.db` }),
          go: dataFile('go', 'Ath/TAIR10', 'go_annotations.tsv', { size: '24 Mb', dbPath: `${DATA_ROOT}/Ath/TAIR10/go.db` }),
          kegg: dataFile('kegg', 'Ath/TAIR10', 'kegg_annotations.tsv', { size: '9 Mb', dbPath: `${DATA_ROOT}/Ath/TAIR10/kegg.db` }),
        },
      },
    ],
    versionMappings: [],
  },
  {
    id: 'Osat',
    scientificName: 'Oryza sativa',
    commonName: '水稻',
    taxonomyId: '4530',
    description: '水稻 Nipponbare 参考基因组与注释库',
    icon: '🌾',
    category: 'plant',
    gradient: 'linear-gradient(90deg, #F77234, #F7BA1E)',
    genomeVersions: [
      {
        versionId: 'Osat_IRGSP1',
        versionName: 'IRGSP-1.0',
        assemblyName: 'IRGSP-1.0',
        isDefault: true,
        status: 'active',
        releaseDate: '2023-11',
        description: '水稻主流参考版本，适合表达与变异分析',
        tags: ['主流版本', '染色体级'],
        stats: {
          chromosomes: 12,
          totalGenes: 30600,
          proteinCoding: 30012,
          genomeSize: '373 Mb',
          n50: '31.1 Mb',
        },
        dataFiles: {
          fasta: dataFile('fasta', 'Osat/IRGSP1', 'IRGSP-1.0.fa', { size: '352 Mb' }),
          gff: dataFile('gff', 'Osat/IRGSP1', 'IRGSP-1.0.gff3', { size: '96 Mb', dbPath: `${DATA_ROOT}/Osat/IRGSP1/annotation.db` }),
          go: dataFile('go', 'Osat/IRGSP1', 'go_annotations.tsv', { size: '16 Mb' }),
          kegg: dataFile('kegg', 'Osat/IRGSP1', 'kegg_annotations.tsv', { size: '10 Mb' }),
        },
      },
    ],
    versionMappings: [],
  },
  {
    id: 'Slyc',
    scientificName: 'Solanum lycopersicum',
    commonName: '番茄',
    taxonomyId: '4081',
    description: '番茄 SL4.0 草案数据库，功能注释建设中',
    icon: '🍅',
    category: 'plant',
    gradient: 'linear-gradient(90deg, #F53F3F, #F77234)',
    genomeVersions: [
      {
        versionId: 'Slyc_SL40',
        versionName: 'SL4.0',
        assemblyName: 'SL4.0',
        isDefault: true,
        status: 'active',
        releaseDate: '2024-03',
        description: '番茄参考版本，GO/KEGG 注释待构建',
        tags: ['建设中'],
        stats: {
          chromosomes: 12,
          totalGenes: 34120,
          proteinCoding: 32200,
          genomeSize: '828 Mb',
          n50: '67 Mb',
        },
        dataFiles: {
          fasta: dataFile('fasta', 'Slyc/SL40', 'SL4.0.fa', { size: '756 Mb' }),
          gff: dataFile('gff', 'Slyc/SL40', 'SL4.0.gff3', { size: '128 Mb', buildStatus: 'building' }),
          go: dataFile('go', 'Slyc/SL40', 'go_annotations.tsv', { size: '-', buildStatus: 'missing' }),
          kegg: dataFile('kegg', 'Slyc/SL40', 'kegg_annotations.tsv', { size: '-', buildStatus: 'missing' }),
        },
      },
    ],
    versionMappings: [],
  },
]

export const MOCK_CHROMOSOMES: Chromosome[] = [
  { name: 'Chr1', length: 425000000, color: '#165DFF' },
  { name: 'Chr2', length: 380000000, color: '#0FC6C2' },
  { name: 'Chr3', length: 350000000, color: '#722ED1' },
  { name: 'Chr4', length: 310000000, color: '#86909C' },
  { name: 'Chr5', length: 290000000, color: '#F77234' },
  { name: 'Chr6', length: 270000000, color: '#14C9C9' },
  { name: 'Chr7', length: 250000000, color: '#4E5969' },
  { name: 'Chr8', length: 230000000, color: '#00B42A' },
  { name: 'Chr9', length: 195000000, color: '#F7BA1E' },
]

export const MOCK_GENE_TYPES: GeneTypeStat[] = [
  { name: 'protein_coding', value: 34210, color: '#165DFF' },
  { name: 'lncRNA', value: 4218, color: '#0FC6C2' },
  { name: 'pseudogene', value: 1856, color: '#F77234' },
  { name: 'other', value: 500, color: '#86909C' },
]

function transcript(geneId: string, start: number, exons: number): GeneTranscript {
  return {
    transcriptId: `${geneId}.t1`,
    biotype: 'protein_coding',
    length: 1200 + exons * 150,
    cdsStart: start + 120,
    cdsEnd: start + 980 + exons * 110,
    lengthAa: 260 + exons * 18,
    canonical: true,
    exons: Array.from({ length: exons }, (_, i) => ({
      start: start + i * 260,
      end: start + i * 260 + 120,
      rank: i + 1,
    })),
  }
}

const COMMON_GO: GOAnnotation[] = [
  { goId: 'GO:0005524', term: 'ATP binding', namespace: 'MF', evidenceCode: 'IEA', source: 'InterPro' },
  { goId: 'GO:0006355', term: 'regulation of transcription', namespace: 'BP', evidenceCode: 'ISS', source: 'UniProt' },
  { goId: 'GO:0005634', term: 'nucleus', namespace: 'CC', evidenceCode: 'IEA', source: 'EnsemblPlants' },
]

const COMMON_KEGG: KEGGAnnotation[] = [
  { pathwayId: 'Lsa04075', pathwayName: 'Plant hormone signal transduction', category: 'Environmental Information Processing', koId: 'K14486', genesInPathway: 89 },
  { pathwayId: 'Lsa00940', pathwayName: 'Phenylpropanoid biosynthesis', category: 'Metabolism', koId: 'K00430', ecNumber: '1.14.14.-', genesInPathway: 45 },
]

const SEQ: GeneSequence = {
  genomic: 'ATGCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGA',
  cds: 'ATGGCTACTGCTGCTGATCGTTACCGATGCTGCTGAGGACTGA',
  protein: 'MA TAADRYRCC*'.replace(/ /g, ''),
}

const GENE_BASE: Gene[] = [
  {
    geneId: 'LsG0001.1',
    geneSymbol: 'LsMYB1',
    geneName: 'MYB transcription factor 1',
    geneType: 'protein_coding',
    status: 'REVIEWED',
    description: 'MYB transcription factor family protein involved in anthocyanin regulation',
    speciesId: 'Lsat',
    genomeVersionId: 'Lsat_v11',
    chromosome: 'Chr1',
    start: 1234567,
    end: 1235890,
    strand: '+',
    aliases: ['Lsat_1_v11_gn_001', 'LOC123456'],
    transcripts: [transcript('LsG0001.1', 1234567, 5)],
    goAnnotations: COMMON_GO,
    keggAnnotations: COMMON_KEGG,
    sequence: SEQ,
    versionMappings: [{ targetVersionId: 'Lsat_v8', targetGeneId: 'Lsat_v8_0001', sourceLocation: 'Chr1:1,234,567-1,235,890', targetLocation: 'Chr1:1,198,234-1,199,557', mappingQuality: 0.98, mappingTool: 'liftoff' }],
  },
  {
    geneId: 'LsG0002.1',
    geneSymbol: 'LsWRKY1',
    geneName: 'WRKY transcription factor 45',
    geneType: 'protein_coding',
    status: 'VALIDATED',
    description: 'WRKY transcription factor associated with stress response',
    speciesId: 'Lsat',
    genomeVersionId: 'Lsat_v11',
    chromosome: 'Chr2',
    start: 2345678,
    end: 2347890,
    strand: '-',
    aliases: ['Lsat_2_v11_gn_002'],
    transcripts: [transcript('LsG0002.1', 2345678, 4)],
    goAnnotations: COMMON_GO.slice(0, 2),
    keggAnnotations: COMMON_KEGG.slice(0, 1),
    sequence: SEQ,
    versionMappings: [{ targetVersionId: 'Lsat_v8', targetGeneId: 'Lsat_v8_0002', sourceLocation: 'Chr2:2,345,678-2,347,890', targetLocation: 'Chr2:2,300,111-2,302,330', mappingQuality: 0.95, mappingTool: 'liftoff' }],
  },
  {
    geneId: 'LsG0003.1',
    geneSymbol: 'LsbHLH1',
    geneName: 'bHLH transcription factor 1',
    geneType: 'protein_coding',
    status: 'REVIEWED',
    description: 'bHLH transcription factor involved in leaf development',
    speciesId: 'Lsat',
    genomeVersionId: 'Lsat_v11',
    chromosome: 'Chr1',
    start: 3456789,
    end: 3458123,
    strand: '+',
    aliases: ['Lsat_1_v11_gn_003'],
    transcripts: [transcript('LsG0003.1', 3456789, 3)],
    goAnnotations: COMMON_GO,
    keggAnnotations: [],
    sequence: SEQ,
    versionMappings: [{ targetVersionId: 'Lsat_v8', targetGeneId: 'Lsat_v8_0003', sourceLocation: 'Chr1:3,456,789-3,458,123', targetLocation: 'Chr1:3,412,000-3,413,410', mappingQuality: 0.92, mappingTool: 'liftoff' }],
  },
  {
    geneId: 'AT1G01010',
    geneSymbol: 'NAC001',
    geneName: 'NAC domain containing protein 1',
    geneType: 'protein_coding',
    status: 'REVIEWED',
    description: 'NAC domain protein involved in developmental process',
    speciesId: 'Ath',
    genomeVersionId: 'Ath_TAIR10',
    chromosome: 'Chr1',
    start: 3760,
    end: 5630,
    strand: '+',
    aliases: ['NAC001'],
    transcripts: [transcript('AT1G01010', 3760, 6)],
    goAnnotations: COMMON_GO,
    keggAnnotations: COMMON_KEGG.slice(0, 1),
    sequence: SEQ,
    versionMappings: [],
  },
]

function buildGenes(): Gene[] {
  const annotations = [
    'Hypothetical protein',
    'Protein kinase family protein',
    'Leucine-rich repeat protein',
    'F-box protein',
    'MADS-box transcription factor',
    'AP2/ERF transcription factor',
    'NAC transcription factor',
  ]
  const result = [...GENE_BASE]
  for (let i = 4; i <= 30; i++) {
    const chr = `Chr${((i - 1) % 9) + 1}`
    const start = 1000000 + i * 234567
    const end = start + 600 + i * 73
    const geneId = `LsG${String(i).padStart(4, '0')}.1`
    result.push({
      geneId,
      geneSymbol: `LsGene${i}`,
      geneName: annotations[(i - 4) % annotations.length],
      geneType: i % 9 === 0 ? 'lncRNA' : i % 11 === 0 ? 'pseudogene' : 'protein_coding',
      status: i % 5 === 0 ? 'PREDICTED' : i % 4 === 0 ? 'PROVISIONAL' : 'VALIDATED',
      description: annotations[(i - 4) % annotations.length],
      speciesId: 'Lsat',
      genomeVersionId: 'Lsat_v11',
      chromosome: chr,
      start,
      end,
      strand: i % 2 === 0 ? '-' : '+',
      aliases: [`Lsat_${chr}_v11_gn_${i}`],
      transcripts: [transcript(geneId, start, (i % 5) + 1)],
      goAnnotations: i % 3 === 0 ? COMMON_GO.slice(0, 1) : COMMON_GO,
      keggAnnotations: i % 4 === 0 ? [] : COMMON_KEGG.slice(0, 1),
      sequence: SEQ,
      versionMappings: i <= 10
        ? [{
            targetVersionId: 'Lsat_v8',
            targetGeneId: `Lsat_v8_${String(i).padStart(4, '0')}`,
            sourceLocation: `${chr}:${start.toLocaleString()}-${end.toLocaleString()}`,
            targetLocation: `${chr}:${(start - 42000).toLocaleString()}-${(end - 42000).toLocaleString()}`,
            mappingQuality: 0.88 + (i % 7) * 0.015,
            mappingTool: 'liftoff',
          }]
        : [],
    })
  }
  return result
}

export const MOCK_GENES: Gene[] = buildGenes()

export const MOCK_ID_MAP: Record<string, string> = Object.fromEntries(
  MOCK_GENES
    .filter((g) => g.speciesId === 'Lsat' && g.versionMappings.length > 0)
    .map((g) => [g.versionMappings[0].targetGeneId, g.geneId]),
)

export const MOCK_ID_MAP_REVERSE: Record<string, string> = Object.fromEntries(
  Object.entries(MOCK_ID_MAP).map(([v8, v11]) => [v11, v8]),
)

export function getDefaultGenomeVersion(species: SpeciesDatabase): GenomeVersion {
  return species.genomeVersions.find((version) => version.isDefault) ?? species.genomeVersions[0]
}

export function flattenGenomeVersions(speciesList: SpeciesDatabase[] = DATABASE_SPECIES): Genome[] {
  return speciesList.flatMap((species) => species.genomeVersions.map((version) => ({
    id: version.versionId,
    speciesId: species.id,
    speciesEmoji: species.icon,
    commonName: species.commonName,
    latinName: species.scientificName,
    taxonomyId: species.taxonomyId,
    version: version.versionName,
    versionFull: version.assemblyName,
    tags: version.tags,
    chromosomes: version.stats.chromosomes,
    totalGenes: version.stats.totalGenes,
    proteinCoding: version.stats.proteinCoding,
    genomeSize: version.stats.genomeSize,
    n50: version.stats.n50,
    releaseDate: version.releaseDate,
    status: version.status,
    isDefault: version.isDefault,
    description: version.description,
    category: species.category,
    gradient: species.gradient,
    dataFiles: version.dataFiles,
  })))
}

export const MOCK_GENOMES: Genome[] = flattenGenomeVersions()

export function getGenomeById(id: string): Genome | undefined {
  return MOCK_GENOMES.find((g) => g.id === id)
}

export function getSpeciesById(id: string): SpeciesDatabase | undefined {
  return DATABASE_SPECIES.find((species) => species.id === id)
}

export function getSpeciesByVersionId(versionId: string): SpeciesDatabase | undefined {
  return DATABASE_SPECIES.find((species) => species.genomeVersions.some((version) => version.versionId === versionId))
}

export function getGenomeVersionById(versionId: string): GenomeVersion | undefined {
  return getSpeciesByVersionId(versionId)?.genomeVersions.find((version) => version.versionId === versionId)
}

export function getDataFileEntries(version: GenomeVersion | Genome): DatabaseDataFile[] {
  return (['fasta', 'gff', 'go', 'kegg'] as DataFileType[])
    .map((key) => version.dataFiles[key])
    .filter((file): file is DatabaseDataFile => Boolean(file))
}

export function getDatabaseSummary(speciesList: SpeciesDatabase[] = DATABASE_SPECIES): DatabaseSummary {
  const versions = flattenGenomeVersions(speciesList)
  const files = versions.flatMap(getDataFileEntries)
  return {
    totalSpecies: speciesList.length,
    totalVersions: versions.length,
    totalGenes: versions.reduce((sum, version) => sum + version.totalGenes, 0),
    readyFiles: files.filter((file) => file.buildStatus === 'ready').length,
    totalFiles: files.length,
  }
}

export function getSpeciesBuildStatus(species: SpeciesDatabase): BuildStatus {
  const files = species.genomeVersions.flatMap(getDataFileEntries)
  if (files.some((file) => file.buildStatus === 'error')) return 'error'
  if (files.some((file) => file.buildStatus === 'building')) return 'building'
  if (files.some((file) => file.buildStatus === 'missing')) return 'missing'
  return 'ready'
}

export function getGenesForVersion(versionId: string): Gene[] {
  return MOCK_GENES.filter((gene) => gene.genomeVersionId === versionId)
}

export function searchGenesForVersion(
  versionId: string,
  query: string,
  field: 'all' | 'geneId' | 'geneSymbol' | 'description',
  chromosome?: string,
): Gene[] {
  const q = query.trim().toLowerCase()
  return getGenesForVersion(versionId).filter((gene) => {
    if (chromosome && gene.chromosome !== chromosome) return false
    if (!q) return true
    if (field === 'geneId') return gene.geneId.toLowerCase().includes(q)
    if (field === 'geneSymbol') return gene.geneSymbol.toLowerCase().includes(q)
    if (field === 'description') return gene.description.toLowerCase().includes(q)
    return [gene.geneId, gene.geneSymbol, gene.geneName, gene.description, ...gene.aliases]
      .some((value) => value.toLowerCase().includes(q))
  })
}

export function getGeneById(geneId: string, versionId?: string): Gene | undefined {
  return MOCK_GENES.find((gene) => gene.geneId === geneId && (!versionId || gene.genomeVersionId === versionId))
}

export function formatLocation(gene: Pick<Gene, 'chromosome' | 'start' | 'end' | 'strand'>): string {
  return `${gene.chromosome}:${gene.start.toLocaleString()}-${gene.end.toLocaleString()} (${gene.strand})`
}
