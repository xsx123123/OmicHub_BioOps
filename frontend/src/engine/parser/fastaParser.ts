import type { FastaRecord, SequenceType } from '../types'

const DNA_ALPHABET = /^[ACGTRYSWKMBDHVN]+$/i
const RNA_ALPHABET = /^[ACGURYSWKMBDHVN]+$/i
const PROTEIN_ALPHABET = /^[ABCDEFGHIKLMNPQRSTVWXYZ*.-]+$/i

export function detectSequenceType(sequence: string): SequenceType {
  const normalized = sequence.replace(/[^A-Za-z*.-]/g, '').toUpperCase()
  if (!normalized) return 'unknown'
  if (normalized.includes('U') && !normalized.includes('T') && RNA_ALPHABET.test(normalized)) return 'rna'
  if (DNA_ALPHABET.test(normalized)) return 'dna'
  if (PROTEIN_ALPHABET.test(normalized)) return 'protein'
  return 'unknown'
}

export function cleanSequence(rawSeq: string, allowedType: 'dna' | 'rna' | 'protein'): string {
  const normalized = rawSeq.toUpperCase().replace(/[\s\d]/g, '')
  if (allowedType === 'dna') return normalized.replace(/[^ACGTRYSWKMBDHVN]/g, '')
  if (allowedType === 'rna') return normalized.replace(/[^ACGURYSWKMBDHVN]/g, '')
  return normalized.replace(/[^ABCDEFGHIKLMNPQRSTVWXYZ*.-]/g, '')
}

function createRecord(header: string, sequence: string, index: number): FastaRecord | null {
  const normalized = sequence.replace(/[\s\d]/g, '').toUpperCase()
  if (!normalized) return null
  const id = header.trim().split(/\s+/)[0] || `sequence_${index}`
  return {
    id,
    header: header.trim() || id,
    sequence: normalized,
    type: detectSequenceType(normalized),
    length: normalized.length,
  }
}

export function parseFasta(input: string): FastaRecord[] {
  const normalizedInput = input.replace(/\r\n?/g, '\n').trim()
  if (!normalizedInput) return []

  const lines = normalizedInput.split('\n')
  if (!lines.some((line) => line.trimStart().startsWith('>'))) {
    const record = createRecord('sequence_1', normalizedInput, 1)
    return record ? [record] : []
  }

  const records: FastaRecord[] = []
  let header = ''
  let chunks: string[] = []

  const flushRecord = () => {
    const record = createRecord(header, chunks.join(''), records.length + 1)
    if (record) records.push(record)
    chunks = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('>')) {
      if (header || chunks.length) flushRecord()
      header = trimmed.slice(1).trim() || `sequence_${records.length + 1}`
    } else if (trimmed) {
      chunks.push(trimmed)
    }
  }
  if (header || chunks.length) flushRecord()
  return records
}

export function formatToFasta(records: FastaRecord[], lineLength = 60): string {
  const width = Math.max(1, Math.floor(lineLength))
  return records.map((record) => {
    const lines: string[] = []
    for (let offset = 0; offset < record.sequence.length; offset += width) {
      lines.push(record.sequence.slice(offset, offset + width))
    }
    return `>${record.header || record.id}\n${lines.join('\n')}`
  }).join('\n')
}
