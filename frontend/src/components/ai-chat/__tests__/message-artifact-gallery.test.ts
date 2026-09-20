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

    // 文件列表收进产物窗口:先打开窗口再操作下载
    const openButton = [...host.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent?.includes('打开产物窗口'))
    openButton?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    const buttons = [...document.body.querySelectorAll<HTMLButtonElement>('button')]
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

    // 预览按钮在产物窗口内:先打开窗口
    const openButton = [...host.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent?.includes('打开产物窗口'))
    openButton?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    const buttons = [...document.body.querySelectorAll<HTMLButtonElement>('button')]
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

  it('图片缩略图点击后打开放大弹窗，含缩放与下载/打印操作', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['png'], { type: 'image/png' }) })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(MessageArtifactGallery, {
      sessionId: 'chat-session-id',
      tools: [{
        id: 'tool-1',
        name: 'chat_sandbox_execute',
        arguments: {},
        status: 'success',
        result: { artifacts: ['plot.png'] },
        uiPayload: {
          artifacts: [{
            path: 'plot.png',
            url: '/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download?path=plot.png',
          }],
        },
      }],
    })
    app.mount(host)
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    const trigger = host.querySelector<HTMLButtonElement>('.message-artifacts__thumb')
    expect(trigger).toBeTruthy()
    trigger?.click()
    await nextTick()

    const modalImage = document.body.querySelector<HTMLImageElement>('.artifact-media__image')
    expect(modalImage?.getAttribute('src')).toBe('blob:artifact')
    const toolbarText = document.body.querySelector('.artifact-media__toolbar')?.textContent || ''
    expect(toolbarText).toContain('100%')
    expect(toolbarText).toContain('打印')
    expect(toolbarText).toContain('下载')
    expect(document.body.querySelector('[aria-label="放大"]')).toBeTruthy()
    expect(document.body.querySelector('[aria-label="缩小"]')).toBeTruthy()
    app.unmount()
  })

  it('PDF 产物卡片内嵌只读预览（iframe 不可交互），点击仍打开带自定义工具条的弹窗', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['pdf'], { type: 'application/pdf' }) })
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(MessageArtifactGallery, {
      sessionId: 'chat-session-id',
      tools: [{
        id: 'tool-1',
        name: 'chat_sandbox_execute',
        arguments: {},
        status: 'success',
        result: { artifacts: ['tree.pdf'] },
        uiPayload: {
          artifacts: [{
            path: 'tree.pdf',
            url: '/api/v1/chat/sandbox-sessions/sandbox-1/artifacts/download?path=tree.pdf',
          }],
        },
      }],
    })
    app.mount(host)
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    // PDF 卡片收进产物窗口:先打开窗口再校验内嵌只读预览
    const openButton = [...host.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent?.includes('打开产物窗口'))
    openButton?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    // 卡片内嵌只读预览：iframe 存在、不可交互（pointer-events 关闭），点击穿透到放大按钮
    const inlineFrame = document.body.querySelector<HTMLIFrameElement>('.message-artifacts__pdf-inline')
    expect(inlineFrame).toBeTruthy()
    expect(inlineFrame?.getAttribute('src')).toBe('blob:artifact#toolbar=0&navpanes=0&view=FitH&page=1')
    const trigger = document.body.querySelector<HTMLButtonElement>('.message-artifacts__pdf-trigger')
    expect(trigger).toBeTruthy()
    trigger?.click()
    await nextTick()

    const modalFrame = document.body.querySelector<HTMLIFrameElement>('.artifact-media__pdf')
    expect(modalFrame?.getAttribute('src')).toBe('blob:artifact#toolbar=0&navpanes=0')
    const toolbarText = document.body.querySelector('.artifact-media__toolbar')?.textContent || ''
    expect(toolbarText).toContain('打印')
    expect(toolbarText).toContain('下载')
    app.unmount()
  })
})
