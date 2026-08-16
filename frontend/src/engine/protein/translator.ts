import { reverseComplement } from '../dna/dna'
import type { CodonTable, ReadingFrame, TranslationOptions } from '../types'

const STANDARD_CODE: Record<string, string> = {
  TTT: 'F', TTC: 'F', TTA: 'L', TTG: 'L', TCT: 'S', TCC: 'S', TCA: 'S', TCG: 'S',
  TAT: 'Y', TAC: 'Y', TAA: '*', TAG: '*', TGT: 'C', TGC: 'C', TGA: '*', TGG: 'W',
  CTT: 'L', CTC: 'L', CTA: 'L', CTG: 'L', CCT: 'P', CCC: 'P', CCA: 'P', CCG: 'P',
  CAT: 'H', CAC: 'H', CAA: 'Q', CAG: 'Q', CGT: 'R', CGC: 'R', CGA: 'R', CGG: 'R',
  ATT: 'I', ATC: 'I', ATA: 'I', ATG: 'M', ACT: 'T', ACC: 'T', ACA: 'T', ACG: 'T',
  AAT: 'N', AAC: 'N', AAA: 'K', AAG: 'K', AGT: 'S', AGC: 'S', AGA: 'R', AGG: 'R',
  GTT: 'V', GTC: 'V', GTA: 'V', GTG: 'V', GCT: 'A', GCC: 'A', GCA: 'A', GCG: 'A',
  GAT: 'D', GAC: 'D', GAA: 'E', GAG: 'E', GGT: 'G', GGC: 'G', GGA: 'G', GGG: 'G',
}

const VERTEBRATE_MITOCHONDRIAL = { ...STANDARD_CODE, ATA: 'M', TGA: 'W', AGA: '*', AGG: '*' }

export const CODON_TABLES: CodonTable[] = [
  { id: '1', name: '标准遗传密码表', table: STANDARD_CODE, startCodons: ['ATG'], stopCodons: ['TAA', 'TAG', 'TGA'] },
  { id: '2', name: '脊椎动物线粒体', table: VERTEBRATE_MITOCHONDRIAL, startCodons: ['ATT', 'ATC', 'ATA', 'ATG', 'GTG'], stopCodons: ['TAA', 'TAG', 'AGA', 'AGG'] },
  { id: '11', name: '细菌 / 古菌 / 植物质体', table: STANDARD_CODE, startCodons: ['TTG', 'CTG', 'ATT', 'ATC', 'ATA', 'ATG', 'GTG'], stopCodons: ['TAA', 'TAG', 'TGA'] },
]

export function getCodonTable(tableId = '1'): CodonTable {
  return CODON_TABLES.find((item) => item.id === tableId) || CODON_TABLES[0]
}

export function translateCodon(codon: string, tableId = '1'): string {
  const normalized = codon.toUpperCase().replace(/U/g, 'T')
  if (normalized.length !== 3) return '-'
  if (/[^ACGT]/.test(normalized)) return 'X'
  return getCodonTable(tableId).table[normalized] || 'X'
}

export function translateFrame(sequence: string, frame: ReadingFrame, tableId = '1', initMet = false): string {
  const normalized = sequence.toUpperCase().replace(/U/g, 'T').replace(/[^ACGTRYSWKMBDHVN]/g, '')
  const template = frame < 0 ? reverseComplement(normalized) : normalized
  const offset = Math.abs(frame) - 1
  let protein = ''
  for (let index = offset; index + 2 < template.length; index += 3) {
    const codon = template.slice(index, index + 3)
    const aminoAcid = initMet && index === offset && getCodonTable(tableId).startCodons.includes(codon)
      ? 'M'
      : translateCodon(codon, tableId)
    protein += aminoAcid
  }
  return protein
}

export function translateSequence(dnaSeq: string, options: TranslationOptions): Record<string, string> {
  const frames: ReadingFrame[] = options.frame === 'all' || options.frame === 'orf'
    ? [1, 2, 3, -1, -2, -3]
    : [Number(options.frame) as ReadingFrame]
  return Object.fromEntries(frames.map((frame) => [String(frame), translateFrame(dnaSeq, frame, options.codonTableId, options.initMet)]))
}

const PREFERRED_CODONS: Record<string, string> = Object.entries(STANDARD_CODE).reduce<Record<string, string>>((mapping, [codon, aminoAcid]) => {
  if (aminoAcid !== '*' && !mapping[aminoAcid]) mapping[aminoAcid] = codon
  return mapping
}, {})

export function reverseTranslate(proteinSequence: string): string {
  return proteinSequence.toUpperCase().replace(/[^A-Z*]/g, '').split('').map((aminoAcid) => {
    if (aminoAcid === '*') return 'TAA'
    return PREFERRED_CODONS[aminoAcid] || 'NNN'
  }).join('')
}
