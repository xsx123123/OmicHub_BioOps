// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as XLSX from 'xlsx'

import MessageArtifactGallery from '../MessageArtifactGallery.vue'
import type { ToolCall } from '../types'

const { apiGet, studioFetch } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  studioFetch: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: { get: apiGet },
}))

vi.mock('@/api/studio', () => ({
  studioApi: {
    fetchArtifactBlob: studioFetch,
  },
}))

describe('MessageArtifactGallery', () => {
  beforeEach(() => {
    apiGet.mockReset()
    studioFetch.mockReset()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:artifact'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('保留聊天沙盒产物 URL，不被仅含路径的 LLM 结果覆盖', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['xlsx']) })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(MessageArtifactGallery, {
      sessionId: 'chat-session-id',
      tools: [{
        id: 'tool-1',
        name: 'chat_sandbox_execute',
        arguments: {},
        status: 'success',
        result: { artifacts: ['carcinogenic_pathways.xlsx'] },
        uiPayload: {
          artifacts: [{
            path: 'carcinogenic_pathways.xlsx',
            url: '/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download?path=carcinogenic_pathways.xlsx',
          }],
        },
      }],
    })
    app.mount(host)

    const buttons = [...host.querySelectorAll<HTMLButtonElement>('button')]
    buttons.find((button) => button.textContent?.trim() === '下载')?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(apiGet).toHaveBeenCalledWith(
      '/chat/sandbox-sessions/sandbox-1/artifacts/download?path=carcinogenic_pathways.xlsx',
      { responseType: 'blob' },
    )
    expect(studioFetch).not.toHaveBeenCalled()
    app.unmount()
  })

  it('通过聊天沙盒 URL 加载并预览 Excel', async () => {
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(
      workbook,
      XLSX.utils.aoa_to_sheet([['gene', 'pathway'], ['TP53', 'p53 signaling']]),
      'results',
    )
    const bytes = XLSX.write(workbook, { type: 'array', bookType: 'xlsx' })
    apiGet.mockResolvedValue({ data: new Blob([bytes]) })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(MessageArtifactGallery, {
      sessionId: 'chat-session-id',
      tools: [{
        id: 'tool-1',
        name: 'chat_sandbox_execute',
        arguments: {},
        status: 'success',
        result: { artifacts: ['carcinogenic_pathways.xlsx'] },
        uiPayload: {
          artifacts: [{
            path: 'carcinogenic_pathways.xlsx',
            url: '/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download?path=carcinogenic_pathways.xlsx',
          }],
        },
      }],
    })
    app.mount(host)

    const buttons = [...host.querySelectorAll<HTMLButtonElement>('button')]
    buttons.find((button) => button.textContent?.trim() === '预览')?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 50))
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith(
      '/chat/sandbox-sessions/sandbox-1/artifacts/download?path=carcinogenic_pathways.xlsx',
      { responseType: 'blob' },
    )
    expect(studioFetch).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('results')
    expect(document.body.textContent).toContain('TP53')
    expect(document.body.textContent).not.toContain('预览加载失败')
    app.unmount()
  })

  it('产物 URL 在流式结果中补齐后重新加载图片预览', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['png'], { type: 'image/png' }) })
    const tools = ref<ToolCall[]>([{
      id: 'tool-1',
      name: 'chat_sandbox_execute',
      arguments: {},
      status: 'success' as const,
      result: { artifacts: ['plot.png'] },
      uiPayload: { artifacts: [{ path: 'plot.png' }] },
    }])
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp({
      setup: () => () => h(MessageArtifactGallery, {
        sessionId: 'chat-session-id',
        tools: tools.value,
      }),
    })
    app.mount(host)
    await nextTick()
    expect(studioFetch).toHaveBeenCalledWith('chat-session-id', 'plot.png')

    studioFetch.mockReset()
    tools.value = [{
      ...tools.value[0],
      uiPayload: {
        artifacts: [{
          path: 'plot.png',
          url: '/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download?path=plot.png',
        }],
      },
    }]
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(apiGet).toHaveBeenCalledWith(
      '/chat/sandbox-sessions/sandbox-1/artifacts/download?path=plot.png',
      { responseType: 'blob' },
    )
    app.unmount()
  })
})
