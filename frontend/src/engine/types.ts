export type SequenceType = 'dna' | 'rna' | 'protein' | 'unknown'

/** IUPAC 核酸碱基与简并碱基代码。 */
export type IupacBase =
  | 'A' | 'T' | 'C' | 'G' | 'U'
  | 'R' | 'Y' | 'S' | 'W' | 'K' | 'M'
  | 'B' | 'D' | 'H' | 'V' | 'N'

/** 单条 FASTA 记录及其自动识别的基础元数据。 */
export interface FastaRecord {
  id: string
  header: string
  sequence: string
  type: SequenceType
  length: number
}

/** 可用于翻译与 ORF 识别的遗传密码子表。 */
export interface CodonTable {
  id: string
  name: string
  table: Record<string, string>
  startCodons: string[]
  stopCodons: string[]
}

export type ReadingFrame = 1 | 2 | 3 | -1 | -2 | -3

/** 六个读码框中的开放阅读框预测结果，坐标使用 1-based 闭区间。 */
export interface OrfMatch {
  id: string
  frame: ReadingFrame
  start: number
  end: number
  lengthNt: number
  lengthAa: number
  dnaSequence: string
  proteinSequence: string
}

/** Motif 或酶切位点在正负链上的匹配坐标。 */
export interface MotifMatch {
  name: string
  pattern: string
  start: number
  end: number
  strand: '+' | '-'
}

/** 序列组成、含量和近似分子量统计。 */
export interface SequenceStats {
  length: number
  gcContent: number
  atContent: number
  nContent: number
  baseCounts: Record<string, number>
  molecularWeight?: number
}

/** 核酸翻译时使用的密码子表、读码框和起始密码子策略。 */
export interface TranslationOptions {
  codonTableId: string
  frame: '1' | '2' | '3' | '-1' | '-2' | '-3' | 'all' | 'orf'
  initMet: boolean
}

/** 工作台结果查看器消费的统一序列结果模型。 */
export interface SequenceResultItem {
  id: string
  header: string
  sequence: string
  type: SequenceType
  metadata?: Record<string, string | number | boolean>
}
