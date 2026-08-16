import type { DbType, ProgramType } from '@/types/blast'

export interface SequenceStats {
  length: number
  gcContent: number
  atContent: number
  nContent: number
  type: 'nucl' | 'prot' | 'unknown'
  recommendedProgram?: ProgramType
  recommendationReason: string
  header?: string
}

export function parseSequenceInput(input: string): { header?: string; sequence: string } {
  const lines = input.trim().split(/\r?\n/).map((line) => line.trim())
  const header = lines.find((line) => line.startsWith('>'))?.slice(1).trim()
  const sequence = lines
    .filter((line) => line && !line.startsWith('>'))
    .join('')
    .replace(/\s/g, '')
    .toUpperCase()
  return { header, sequence }
}

export function detectSequenceType(sequence: string): SequenceStats['type'] {
  const clean = sequence.replace(/[-.*]/g, '')
  if (clean.length < 20) return 'unknown'
  if (/^[ATCGUNRYMKSWHBVD]+$/.test(clean)) return 'nucl'
  if (/^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$/.test(clean)) return 'prot'
  return 'unknown'
}

export function recommendProgram(
  queryType: SequenceStats['type'],
  dbType?: DbType,
): { program?: ProgramType; reason: string } {
  if (!dbType) return { reason: '选择数据库后可生成算法推荐' }
  if (queryType === 'unknown') return { reason: '序列类型尚不明确，暂无法推荐算法' }
  if (queryType === 'nucl' && dbType === 'nucl') {
    return { program: 'blastn', reason: '核酸查询对核酸数据库，推荐 blastn' }
  }
  if (queryType === 'prot' && dbType === 'prot') {
    return { program: 'blastp', reason: '蛋白查询对蛋白数据库，推荐 blastp' }
  }
  if (queryType === 'nucl' && dbType === 'prot') {
    return { program: 'blastx', reason: '核酸查询需翻译后搜索蛋白数据库，推荐 blastx' }
  }
  return { program: 'tblastn', reason: '蛋白查询需搜索翻译后的核酸数据库，推荐 tblastn' }
}

export function analyzeSequence(input: string, dbType?: DbType): SequenceStats {
  const { header, sequence } = parseSequenceInput(input)
  const type = detectSequenceType(sequence)
  const nucleotideCharacters = sequence.match(/[ATCGU]/g) || []
  const nucleotideLength = nucleotideCharacters.length
  const gcCount = (sequence.match(/[GC]/g) || []).length
  const atCount = (sequence.match(/[ATU]/g) || []).length
  const nCount = (sequence.match(/N/g) || []).length
  const recommendation = recommendProgram(type, dbType)

  return {
    length: sequence.replace(/[-.*]/g, '').length,
    gcContent: nucleotideLength ? (gcCount / nucleotideLength) * 100 : 0,
    atContent: nucleotideLength ? (atCount / nucleotideLength) * 100 : 0,
    nContent: sequence.length ? (nCount / sequence.length) * 100 : 0,
    type,
    recommendedProgram: recommendation.program,
    recommendationReason: recommendation.reason,
    header,
  }
}
