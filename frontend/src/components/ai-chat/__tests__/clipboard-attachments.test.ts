import { describe, expect, it } from 'vitest'
import { clipboardAttachmentFiles } from '../clipboardAttachments'

function clipboardWith(items: DataTransferItem[]): DataTransfer {
  return { items } as unknown as DataTransfer
}

function clipboardFilesOnly(files: File[]): DataTransfer {
  return { items: [], files } as unknown as DataTransfer
}

function imageItem(file: File): DataTransferItem {
  return {
    kind: 'file',
    type: file.type,
    getAsFile: () => file,
  } as DataTransferItem
}

describe('clipboardAttachmentFiles', () => {
  it('extracts clipboard images and gives unnamed clipboard images a stable filename', () => {
    const image = new File(['image'], 'image.png', { type: 'image/png' })

    const files = clipboardAttachmentFiles(clipboardWith([imageItem(image)]), Date.UTC(2026, 7, 10, 12, 34, 56))

    expect(files).toHaveLength(1)
    expect(files[0]).toMatchObject({
      name: 'clipboard-image-20260810-123456.png',
      type: 'image/png',
      size: image.size,
    })
  })

  it('keeps copied files such as treefile and PDF attachments', () => {
    const treeFile = new File(['(A,B);'], 'sample.treefile', { type: 'application/octet-stream' })
    const pdfFile = new File(['pdf'], 'paper.pdf', { type: 'application/pdf' })

    const files = clipboardAttachmentFiles(clipboardWith([imageItem(treeFile), imageItem(pdfFile)]))

    expect(files.map((file) => file.name)).toEqual(['sample.treefile', 'paper.pdf'])
  })

  it('falls back to clipboardData.files when the browser exposes no file items', () => {
    const treeFile = new File(['(A,B);'], 'fallback.treefile', { type: 'application/octet-stream' })

    expect(clipboardAttachmentFiles(clipboardFilesOnly([treeFile]))).toEqual([treeFile])
  })

  it('ignores clipboard text when no real file is present', () => {
    const textItem = { kind: 'string', type: 'text/plain', getAsFile: () => null } as DataTransferItem

    expect(clipboardAttachmentFiles(clipboardWith([textItem]))).toEqual([])
  })
})
