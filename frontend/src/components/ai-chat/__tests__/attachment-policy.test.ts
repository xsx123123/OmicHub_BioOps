import { describe, expect, it } from 'vitest'
import { requiresDataManagementUpload } from '../attachmentPolicy'

describe('requiresDataManagementUpload', () => {
  it.each(['sample.bam', 'alignment.CRAM', 'cells.h5ad', 'object.Rds', 'integration_harmony.qs', 'bundle.zip'])(
    'routes %s through file management',
    (filename) => {
      expect(requiresDataManagementUpload(filename)).toBe(true)
    },
  )

  it.each(['plot.png', 'metadata.csv', 'markers.tsv', 'report.pdf', 'genes.fasta'])(
    'keeps %s in the chat attachment flow',
    (filename) => {
      expect(requiresDataManagementUpload(filename)).toBe(false)
    },
  )
})
