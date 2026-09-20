/**
 * 参考基因组 API —— /api/v1/reference-genomes/*
 *
 * apiClient baseURL 已是 /api/v1，路径写 /reference-genomes/...。
 * 响应字段全部 camelCase，无 {data} 信封。
 */
import apiClient from './client'
import type {
  AnnotationGenesResult,
  BatchAnnotateResult,
  GeneDetail,
  GeneListResult,
  GoTermListResult,
  KeggPathwayListResult,
  MapIdsResult,
  SearchResult,
  SequenceResult,
  SpeciesListResponse,
  VersionDetailResponse,
} from '@/types/referenceGenomes'

/** GET /reference-genomes/species */
export function fetchSpecies(): Promise<SpeciesListResponse> {
  return apiClient.get('/reference-genomes/species').then((r) => r.data)
}

/** GET /reference-genomes/versions/{id} */
export function fetchVersionDetail(versionId: string): Promise<VersionDetailResponse> {
  return apiClient.get(`/reference-genomes/versions/${versionId}`).then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/genes */
export function searchGenes(
  versionId: string,
  params: {
    field?: 'gene_id' | 'gene_name' | 'annotation' | 'go' | 'kegg' | 'all'
    q?: string
    chromosome?: string
    page?: number
    page_size?: number
  },
): Promise<GeneListResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/genes`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/genes/{geneId} */
export function fetchGeneDetail(versionId: string, geneId: string): Promise<GeneDetail> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/genes/${encodeURIComponent(geneId)}`)
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/genes/{geneId}/sequence */
export function fetchGeneSequence(
  versionId: string,
  geneId: string,
  params: { type: 'genomic' | 'cds' | 'protein' | 'promoter'; format?: 'json' | 'fasta'; upstream?: number },
): Promise<SequenceResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/genes/${encodeURIComponent(geneId)}/sequence`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/sequence（区域序列） */
export function fetchRegionSequence(
  versionId: string,
  params: { chrom: string; start: number; end: number; strand?: string; format?: 'json' | 'fasta' },
): Promise<SequenceResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/sequence`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/go */
export function fetchGoTerms(
  versionId: string,
  params?: { q?: string; aspect?: string; page?: number },
): Promise<GoTermListResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/go`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/kegg/pathways */
export function fetchKeggPathways(
  versionId: string,
  params?: { q?: string },
): Promise<KeggPathwayListResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/kegg/pathways`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/go/{goId}/genes */
export function fetchGoGenes(
  versionId: string,
  goId: string,
  params?: { page?: number },
): Promise<AnnotationGenesResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/go/${encodeURIComponent(goId)}/genes`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/kegg/pathways/{pwId}/genes */
export function fetchPathwayGenes(
  versionId: string,
  pathwayId: string,
): Promise<AnnotationGenesResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/kegg/pathways/${encodeURIComponent(pathwayId)}/genes`)
    .then((r) => r.data)
}

/** GET /reference-genomes/versions/{id}/search */
export function searchInVersion(
  versionId: string,
  params: { q: string; limit?: number },
): Promise<SearchResult> {
  return apiClient
    .get(`/reference-genomes/versions/${versionId}/search`, { params })
    .then((r) => r.data)
}

/** GET /reference-genomes/search */
export function globalSearch(
  params: { q: string; limit?: number },
): Promise<SearchResult> {
  return apiClient
    .get('/reference-genomes/search', { params })
    .then((r) => r.data)
}

/** POST /reference-genomes/versions/{id}/genes/batch */
export function batchAnnotate(
  versionId: string,
  geneIds: string[],
): Promise<BatchAnnotateResult> {
  return apiClient
    .post(`/reference-genomes/versions/${versionId}/genes/batch`, { geneIds })
    .then((r) => r.data)
}

/** POST /reference-genomes/versions/{id}/map-ids */
export function mapIds(
  versionId: string,
  body: { targetVersionId: string; ids: string[] },
): Promise<MapIdsResult> {
  return apiClient
    .post(`/reference-genomes/versions/${versionId}/map-ids`, body)
    .then((r) => r.data)
}

/** POST /reference-genomes/reload（管理员） */
export function reloadConfig(): Promise<void> {
  return apiClient.post('/reference-genomes/reload').then((r) => r.data)
}
