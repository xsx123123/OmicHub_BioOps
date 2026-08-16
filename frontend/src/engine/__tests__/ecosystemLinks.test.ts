// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { consumeSequenceHandoff, storeSequenceHandoff } from '../ecosystemLinks'
import type { FastaRecord } from '../types'

const record: FastaRecord = {
  id: 'ACTB',
  header: 'ACTB demo',
  sequence: 'ATGCGT',
  type: 'dna',
  length: 6,
}

describe('Sequence Studio ecosystem handoff', () => {
  beforeEach(() => sessionStorage.clear())

  it('stores and consumes a sequence exactly once', () => {
    storeSequenceHandoff('blast', record)
    expect(consumeSequenceHandoff('blast')?.record).toEqual(record)
    expect(consumeSequenceHandoff('blast')).toBeNull()
  })
})
