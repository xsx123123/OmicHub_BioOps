import { describe, expect, it } from 'vitest'
import { findMotifs, findOrfs } from '../analysis/orfFinder'
import { calculateStats, reverseComplement, transcribe } from '../dna/dna'
import { cleanSequence, formatToFasta, parseFasta } from '../parser/fastaParser'
import { reverseTranslate, translateCodon, translateSequence } from '../protein/translator'

describe('Sequence Studio engine', () => {
  it('parses dirty multi-FASTA input', () => {
    const records = parseFasta('>a first\r\nATG 12 C\n\n>b\nMELP')
    expect(records).toHaveLength(2)
    expect(records[0]).toMatchObject({ id: 'a', sequence: 'ATGC', type: 'dna', length: 4 })
    expect(records[1]).toMatchObject({ id: 'b', sequence: 'MELP', type: 'protein' })
    expect(formatToFasta(records, 3)).toContain('ATG\nC')
  })

  it('cleans sequence by biological alphabet', () => {
    expect(cleanSequence('a t-g1cx', 'dna')).toBe('ATGC')
    expect(cleanSequence('AUG x', 'rna')).toBe('AUG')
  })

  it('supports IUPAC reverse complement and transcription', () => {
    expect(reverseComplement('AaRyk')).toBe('mrYtT')
    expect(transcribe('AtTg')).toBe('AuUg')
  })

  it('calculates GC using canonical bases only', () => {
    expect(calculateStats('GGCCATNN')).toMatchObject({ length: 8, gcContent: 66.67, atContent: 33.33, nContent: 25 })
  })

  it('translates standard and mitochondrial codons', () => {
    expect(translateCodon('TGA')).toBe('*')
    expect(translateCodon('TGA', '2')).toBe('W')
    expect(translateSequence('ATGGGGTAA', { codonTableId: '1', frame: '1', initMet: true })['1']).toBe('MG*')
    expect(reverseTranslate('MX')).toBe('ATGNNN')
  })

  it('finds ORFs and IUPAC motifs on both strands', () => {
    const sequence = `CCCATG${'GCT'.repeat(30)}TAAACCC`
    const orfs = findOrfs(sequence, 20)
    expect(orfs[0]).toMatchObject({ frame: 1, lengthAa: 31 })
    expect(findMotifs('ATGCGCAT', 'GCN').length).toBeGreaterThan(0)
  })
})
