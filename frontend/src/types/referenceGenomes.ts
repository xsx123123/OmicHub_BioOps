/**
 * 参考基因组模块类型定义。
 *
 * 包含从 mock/referenceGenomes.ts 提取的领域类型（保持原名），
 * 以及后端 API /reference-genomes/* 的响应类型。
 */

/* ────── 领域类型（与 mock 保持一致） ────── */

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

export interface Chromosome {
  name: string
  length: number
  color: string
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

/* ────── API 响应类型 ────── */

/** 基因列表单条（GET /versions/{id}/genes → items[]） */
export interface ApiGene {
  geneId: string
  geneName: string
  annotation: string
  geneType: string
  chromosome: string
  start: number
  end: number
  strand: GeneStrand
  length: number
  exons: number
  hasGo: boolean
  hasKegg: boolean
  hasSequence: boolean
}

export interface GeneListResult {
  total: number
  page: number
  pageSize: number
  items: ApiGene[]
}

export interface Transcript {
  transcriptId: string
  geneId: string
  chromosome: string
  start: number
  end: number
  strand: GeneStrand
  biotype: string
  length: number
  exonCount: number
  exons: Array<{ start: number; end: number; rank: number }>
  cdsId?: string
  pepId?: string
  canonical: boolean
}

export interface GoAnnotation {
  goId: string
  term: string
  namespace: 'MF' | 'BP' | 'CC'
  evidenceCode: string
  source: string
}

export interface KeggKo {
  koId: string
  name: string
  geneCount: number
}

export interface KeggPathway {
  pathwayId: string
  name: string
  geneCount: number
}

export interface GeneDetailKegg {
  kos: KeggKo[]
  pathways: KeggPathway[]
}

export interface SequenceAvailability {
  genomic: boolean
  cds: boolean
  protein: boolean
}

/** GET /versions/{id}/genes/{geneId} */
export interface GeneDetail {
  gene: ApiGene
  transcripts: Transcript[]
  go: GoAnnotation[]
  kegg: GeneDetailKegg
  sequenceAvailable: SequenceAvailability
}

/** GET /versions/{id}/genes/{geneId}/sequence 或 /versions/{id}/sequence */
export interface SequenceResult {
  header: string
  sequence: string
  length: number
  seqType: string
  transcriptId?: string
  chromosome?: string
  start?: number
  end?: number
  strand?: string
}

/** GET /versions/{id}/go → items[] */
export interface GoTermItem {
  goId: string
  name: string
  aspect: string
  definition: string
  geneCount: number
}

export interface GoTermListResult {
  total: number
  items: GoTermItem[]
}

/** GET /versions/{id}/kegg/pathways → items[] */
export interface KeggPathwayItem {
  pathwayId: string
  name: string
  geneCount: number
}

export interface KeggPathwayListResult {
  total: number
  items: KeggPathwayItem[]
}

/** GET /versions/{id}/go/{goId}/genes 或 /versions/{id}/kegg/pathways/{pwId}/genes */
export interface AnnotationGenesResult {
  total: number
  items: ApiGene[]
  goId?: string
  pathwayId?: string
  name?: string
}

/** 搜索结果各分组 */
export interface SearchGeneHit {
  geneId: string
  geneName: string
  annotation: string
  chromosome: string
  versionId: string
  speciesId: string
}

export interface SearchGoHit {
  goId: string
  name: string
  aspect: string
  geneCount: number
  versionId: string
  speciesId: string
}

export interface SearchKeggHit {
  id: string
  kind: string
  name: string
  geneCount: number
  versionId: string
  speciesId: string
}

export interface SearchSpeciesHit {
  speciesId: string
  commonName: string
  match: string
}

export interface SearchResult {
  genes: SearchGeneHit[]
  goTerms: SearchGoHit[]
  kegg: SearchKeggHit[]
  species: SearchSpeciesHit[]
}

/** POST /versions/{id}/genes/batch */
export interface BatchGeneItem {
  geneId: string
  found: boolean
  geneName: string
  annotation: string
  goCount: number
  keggCount: number
}

export interface BatchAnnotateResult {
  total: number
  found: number
  items: BatchGeneItem[]
}

/** POST /versions/{id}/map-ids */
export interface MapIdItem {
  input: string
  output: string | null
  status: 'success' | 'fail' | 'not_found' | string
}

export interface MapIdsResult {
  results: MapIdItem[]
  successCount: number
  totalCount: number
}

/** GET /reference-genomes/species */
export interface SpeciesListResponse {
  species: SpeciesDatabase[]
}

/** GET /versions/{id} */
export interface VersionDetailResponse {
  speciesId: string
  versionId: string
  versionName: string
  assemblyName: string
  isDefault: boolean
  status: string
  releaseDate: string
  description: string
  tags: string[]
  stats: GenomeVersionStats
  chromosomes: Chromosome[]
  geneTypeStats: GeneTypeStat[]
  dataFiles: Partial<Record<DataFileType, DatabaseDataFile>>
  buildStatus: BuildStatus
  indexed: boolean
  builtAt?: string
  geneCount: number
  transcriptCount: number
}
