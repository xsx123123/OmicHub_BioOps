/**
 * 格式轻量转换器核心算法（纯函数，无 Vue 依赖）。
 *
 * 三类能力：
 * 1. GFF3 / GTF / BED 互转（统一经 GffRecord 中间表示）
 * 2. FASTA 序列按 ID 提取（支持精确 / 部分匹配）
 * 3. ID 映射表（两列 TSV/CSV ↔ JSON/TSV）
 *
 * 坐标约定：GFF/GTF 为 1-based closed，BED 为 0-based half-open，互转时自动换算。
 */

export interface GffRecord {
  chrom: string
  source: string
  feature: string
  start: number // 1-based
  end: number
  score: string
  strand: string
  phase: string
  attributes: Record<string, string>
}

export interface BedRecord {
  chrom: string
  start: number // 0-based
  end: number
  name: string
  score: string
  strand: string
}

export interface FastaRecord {
  id: string
  header: string
  seq: string
}

export type SourceFormat = 'gff3' | 'gtf' | 'bed'
export type TargetFormat = 'gff3' | 'gtf' | 'bed3' | 'bed6' | 'bed12'

/** 解析 GFF3 属性列：key=value;key=value。 */
function parseGffAttrs(attrs: string): Record<string, string> {
  const result: Record<string, string> = {}
  attrs.split(';').forEach((pair) => {
    const idx = pair.indexOf('=')
    if (idx > 0) {
      const k = pair.slice(0, idx).trim()
      const v = pair.slice(idx + 1).trim()
      if (k) result[k] = v
    }
  })
  return result
}

/** 解析 GTF 属性列：key "value"; key "value";。 */
function parseGtfAttrs(attrs: string): Record<string, string> {
  const result: Record<string, string> = {}
  const regex = /(\w+)\s+"([^"]*)"/g
  let m: RegExpExecArray | null
  while ((m = regex.exec(attrs)) !== null) {
    result[m[1]] = m[2]
  }
  return result
}

/** 把通用属性字典序列化回 GFF3 属性列。 */
function toGffAttrs(attrs: Record<string, string>): string {
  return Object.entries(attrs)
    .map(([k, v]) => `${k}=${v}`)
    .join(';')
}

/** 把通用属性字典序列化回 GTF 属性列。 */
function toGtfAttrs(attrs: Record<string, string>): string {
  return Object.entries(attrs)
    .map(([k, v]) => `${k} "${v}";`)
    .join(' ')
}

/** 从属性里取展示名。 */
function attrToName(attrs: Record<string, string>): string {
  return attrs.Name || attrs.ID || attrs.gene_name || attrs.gene_id || attrs.transcript_id || 'unknown'
}

export function parseGff(text: string): GffRecord[] {
  return text
    .split('\n')
    .filter((line) => line.trim() && !line.startsWith('#'))
    .map((line) => {
      const cols = line.split('\t')
      if (cols.length < 8) return null
      return {
        chrom: cols[0],
        source: cols[1],
        feature: cols[2],
        start: +cols[3],
        end: +cols[4],
        score: cols[5],
        strand: cols[6],
        phase: cols[7],
        attributes: parseGffAttrs(cols[8] || ''),
      } as GffRecord
    })
    .filter(Boolean) as GffRecord[]
}

export function parseGtf(text: string): GffRecord[] {
  return text
    .split('\n')
    .filter((line) => line.trim() && !line.startsWith('#'))
    .map((line) => {
      const cols = line.split('\t')
      if (cols.length < 8) return null
      return {
        chrom: cols[0],
        source: cols[1],
        feature: cols[2],
        start: +cols[3],
        end: +cols[4],
        score: cols[5],
        strand: cols[6],
        phase: cols[7],
        attributes: parseGtfAttrs(cols[8] || ''),
      } as GffRecord
    })
    .filter(Boolean) as GffRecord[]
}

export function parseBed(text: string): BedRecord[] {
  return text
    .split('\n')
    .filter((line) => line.trim() && !line.startsWith('#') && !line.startsWith('track') && !line.startsWith('browser'))
    .map((line) => {
      const cols = line.split('\t')
      if (cols.length < 3) return null
      return {
        chrom: cols[0],
        start: +cols[1],
        end: +cols[2],
        name: cols[3] || '',
        score: cols[4] || '0',
        strand: cols[5] || '.',
      } as BedRecord
    })
    .filter(Boolean) as BedRecord[]
}

/** BED → GffRecord（0-based 转 1-based）。 */
function bedToGffRecord(b: BedRecord): GffRecord {
  return {
    chrom: b.chrom,
    source: 'bed_import',
    feature: 'region',
    start: b.start + 1,
    end: b.end,
    score: b.score,
    strand: b.strand,
    phase: '.',
    attributes: { ID: b.name || 'region', Name: b.name || 'region' },
  }
}

/** 按源格式解析为统一的 GffRecord 列表。 */
export function parseRecords(source: SourceFormat, text: string): GffRecord[] {
  if (source === 'gff3') return parseGff(text)
  if (source === 'gtf') return parseGtf(text)
  return parseBed(text).map(bedToGffRecord)
}

/** 按目标格式输出文本，可按 feature 类型过滤。 */
export function emitRecords(target: TargetFormat, records: GffRecord[], featureType?: string): string {
  const filtered = featureType ? records.filter((r) => r.feature === featureType) : records
  if (target === 'gff3') {
    return filtered
      .map((r) => [r.chrom, r.source, r.feature, r.start, r.end, r.score, r.strand, r.phase, toGffAttrs(r.attributes)].join('\t'))
      .join('\n')
  }
  if (target === 'gtf') {
    return filtered
      .map((r) => [r.chrom, r.source, r.feature, r.start, r.end, r.score, r.strand, r.phase, toGtfAttrs(r.attributes)].join('\t'))
      .join('\n')
  }
  // BED 系列：1-based 转 0-based
  return filtered
    .map((r) => {
      const name = attrToName(r.attributes)
      const score = r.score === '.' ? '0' : r.score
      if (target === 'bed3') return [r.chrom, r.start - 1, r.end].join('\t')
      if (target === 'bed6') return [r.chrom, r.start - 1, r.end, name, score, r.strand].join('\t')
      // bed12：thickStart/thickEnd/itemRgb/blockCount/blockSizes/blockStarts 用默认值
      return [r.chrom, r.start - 1, r.end, name, score, r.strand, r.start - 1, r.end, '0', '1', r.end - r.start + 1, '0'].join('\t')
    })
    .join('\n')
}

/** 解析 FASTA 文本为记录列表。 */
export function parseFastaRecords(text: string): FastaRecord[] {
  const records: FastaRecord[] = []
  let current: FastaRecord | null = null
  for (const line of text.split('\n')) {
    if (line.startsWith('>')) {
      if (current) records.push(current)
      const header = line.slice(1).trim()
      const id = header.split(/\s/)[0]
      current = { id, header, seq: '' }
    } else if (current) {
      current.seq += line.trim()
    }
  }
  if (current) records.push(current)
  return records
}

/** 按 ID 列表提取 FASTA 记录，partialMatch 时双向包含匹配。 */
export function extractFastaByIds(
  text: string,
  idListText: string,
  partialMatch: boolean,
): FastaRecord[] {
  const ids = idListText.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!ids.length) return []
  const records = parseFastaRecords(text)
  return records.filter((r) =>
    ids.some((id) => (partialMatch ? r.id.includes(id) || id.includes(r.id) : r.id === id)),
  )
}

/** 格式化 FASTA 输出（每行 60 字符）。 */
export function formatFasta(records: FastaRecord[], lineLength = 60): string {
  return records
    .map((r) => {
      const lines = [`>${r.header || r.id}`]
      for (let i = 0; i < r.seq.length; i += lineLength) {
        lines.push(r.seq.slice(i, i + lineLength))
      }
      return lines.join('\n')
    })
    .join('\n')
}

/** 解析两列 TSV/CSV 为映射字典。 */
export function parseIdMap(text: string, delimiter: 'tab' | 'comma' = 'tab'): Record<string, string> {
  const map: Record<string, string> = {}
  text
    .split('\n')
    .filter((l) => l.trim())
    .forEach((line) => {
      const cols = delimiter === 'tab' ? line.split('\t') : line.split(',')
      if (cols.length >= 2) map[cols[0].trim()] = cols[1].trim()
    })
  return map
}

/** 格式化映射字典为 JSON 或 TSV。 */
export function formatIdMap(map: Record<string, string>, format: 'json' | 'tsv'): string {
  if (format === 'json') return JSON.stringify(map, null, 2)
  return Object.entries(map)
    .map(([k, v]) => `${k}\t${v}`)
    .join('\n')
}

/** 内置 GFF3 示例。 */
export function genSampleGff(): string {
  return `##gff-version 3
chr1\texample\tgene\t1000\t3000\t.\t+\t.\tID=gene01;Name=ACT1
chr1\texample\tmRNA\t1000\t3000\t.\t+\t.\tID=mRNA01;Parent=gene01;Name=ACT1.1
chr1\texample\texon\t1000\t1500\t.\t+\t.\tID=exon01;Parent=mRNA01
chr1\texample\tCDS\t1100\t1500\t.\t+\t0\tID=cds01;Parent=mRNA01
chr1\texample\texon\t2000\t3000\t.\t+\t.\tID=exon02;Parent=mRNA01
chr1\texample\tCDS\t2000\t2900\t.\t+\t0\tID=cds02;Parent=mRNA01`
}

/** 内置 FASTA 示例。 */
export function genSampleFasta(): string {
  return `>gene01 chr1 description
ATGGCAGACGCAGATGAGATCAAGGCCAAGGCGGCGGCGTAA
>gene02 chr2 description
ATGCGATCGATCGATCGATCGATCGATCGATCGAATAA
>gene03 chr3 description
ATGAGAGAGAGAGAGAGAGAGAGAGAGAGAGAGATGA`
}
