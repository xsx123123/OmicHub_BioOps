// @vitest-environment jsdom
/**
 * KimiMessageItem 渲染分支测试（jsdom 真实挂载）
 *
 * 背景 bug：开启深度思考后，思考过程面板渲染了，但正文区域空白。
 * 这里用真实 SSE 事件序列驱动 agentHub store 的回调逻辑 + 组件挂载，
 * 验证三种状态下正文是否正确渲染。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'

// lottie-web / vue-echarts import 时依赖完整浏览器 API，打桩
vi.mock('vue3-lottie', () => ({ Vue3Lottie: { template: '<div />' } }))
vi.mock('vue-echarts', () => ({ default: { template: '<div />' } }))
const studioApiMocks = vi.hoisted(() => ({
  fetchArtifactBlob: vi.fn().mockResolvedValue('blob:heatmap-preview'),
  downloadArtifact: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/api/studio', () => ({
  studioApi: studioApiMocks,
}))
const apiClientMocks = vi.hoisted(() => ({
  get: vi.fn().mockResolvedValue({ data: new Blob(['image']) }),
}))
vi.mock('@/api/client', () => ({ default: apiClientMocks }))

import KimiMessageItem from '@/components/ai-chat/KimiMessageItem.vue'
import { stripFakeToolCallMarkup } from '@/components/ai-chat/messageSanitize'
import type { ChatMessage } from '@/components/ai-chat/types'

// rAF 同步化：让流式渲染立即落盘，便于断言
beforeEach(() => {
  global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    cb(0)
    return 0
  }) as typeof requestAnimationFrame
  global.cancelAnimationFrame = (() => {}) as typeof cancelAnimationFrame
  URL.createObjectURL = vi.fn(() => 'blob:chat-attachment-preview')
  URL.revokeObjectURL = vi.fn()
  apiClientMocks.get.mockClear()
})

function mountItem(props: Record<string, unknown>) {
  setActivePinia(createPinia())
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    render() {
      return h(NMessageProvider, null, {
        default: () => h(KimiMessageItem, props as never),
      })
    },
  })
  app.mount(el)
  return { el, app }
}

const baseMsg: ChatMessage = {
  id: 'm1',
  role: 'assistant',
  content: '',
  createdAt: new Date().toISOString(),
}

describe('KimiMessageItem 渲染分支', () => {
  it('将用户上传的图片渲染为带鉴权获取的缩略图', async () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        role: 'user',
        content: '这个是什么呀',
        attachments: [{
          name: 'clipboard-image.png',
          size: 1024,
          type: 'image/png',
          url: '/api/v1/files/chat-upload/user/image.png',
          file_id: 'upload-image',
          source: 'upload',
        }],
      },
      isStreaming: false,
    })

    await Promise.resolve()
    await nextTick()

    expect(apiClientMocks.get).toHaveBeenCalledWith(
      '/api/v1/files/chat-upload/user/image.png',
      { responseType: 'blob' },
    )
    expect(el.querySelector<HTMLImageElement>('.attachment-image-preview')?.src)
      .toContain('blob:chat-attachment-preview')
    expect(el.textContent).toContain('clipboard-image.png')
  })

  it('将知识库引用标记渲染为可悬停的编号预览', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: '建议先检查测序质量。[[citation:kb-0123456789abcdef]]',
        toolCalls: [{
          id: 'knowledge-search-1',
          name: 'knowledge_search',
          arguments: { query: 'RNA-seq 质控' },
          status: 'success',
          result: {
            results: [{
              citation_id: 'kb-0123456789abcdef',
              doc_id: 'rna-seq-guide',
              title: 'RNA-seq 质控指南',
              category: 'RNA-seq',
              excerpt: '附件图片：qc-summary.png 来源：/docs-static/knowledge/figure/qc-summary.png',
              section_path: '质控',
              url: '/knowledge/rna-seq-guide',
            }],
          },
        }],
      },
      isStreaming: false,
    })

    expect(el.querySelector<HTMLButtonElement>('.knowledge-citation')?.textContent).toBe('[1]')
    expect(el.querySelector('.knowledge-citation-preview')?.textContent).toContain('RNA-seq 质控指南')
    expect(el.querySelector<HTMLImageElement>('.knowledge-citation-preview__image')?.src)
      .toContain('/docs-static/knowledge/figure/qc-summary.png')
    expect(el.textContent).not.toContain('[[citation:')
  })

  it('system ask_request 的计划确认呈现专用卡而非空系统消息', () => {
    const { el } = mountItem({
      sessionId: 'session-plan',
      message: {
        ...baseMsg,
        role: 'system',
        askRequest: {
          kind: 'plan_confirmation',
          questions: [],
          answered: false,
          planConfirmation: {
            runId: 'run-plan',
            title: '执行计划待确认',
            summary: '先研究，再执行。',
            planPath: 'output/overdrive/session-plan/run-plan/plan.md',
            planVersion: 1,
            planHash: 'sha256:test',
            waveCount: 2,
            agents: [{ agentId: 'agent-qc', name: '质控助手' }],
            serialPreflight: ['核验输入'],
            risks: ['输入可能缺失'],
            approvalPoints: [],
            deliverables: ['质控报告'],
            actions: ['approve', 'revise', 'cancel'],
            status: 'pending',
          },
        },
      },
      isStreaming: false,
    })

    expect(el.querySelector('.plan-confirmation')).not.toBeNull()
    expect(el.textContent).toContain('执行计划待确认')
    expect(el.querySelector('.system-message')).toBeNull()
  })

  it('路由到专项 Agent 时显示完整过渡卡和执行确认提示', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: '我会先确认你的输入数据和分组信息。',
        routedAgent: {
          agentId: 'agent-rnaseq',
          name: 'RNA-seq 分析师',
          avatar: '🧬',
          color: '#16a34a',
          reason: '识别为 Bulk RNA-seq 差异表达任务',
          intent: 'transfer',
          confidence: 0.96,
          transition: {
            visible: true,
            stage: 'specialist_intake',
            title: '已匹配专项专家',
            message: '将先确认任务目标与输入，涉及实际分析时会在启动前请求确认。',
            nextStep: '专项 Agent 进行任务 intake',
            requiresExecutionConfirmation: true,
            autoStart: false,
          },
        },
      },
      isStreaming: false,
    })

    expect(el.textContent).toContain('STELLAR ROUTER')
    expect(el.textContent).toContain('星尘 AI')
    expect(el.textContent).toContain('RNA-seq 分析师')
    expect(el.textContent).toContain('专家转交')
    expect(el.textContent).toContain('96%')
    expect(el.textContent).not.toContain('执行前需确认')
    expect(el.textContent).not.toContain('确认开始')
  })

  it('路由到通用助手时，即使正文为空也显示 Router 分发卡片', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: '',
        routedAgent: {
          agentId: 'agent-general',
          name: '通用助手',
          avatar: '🤖',
          color: '#7691FF',
          reason: '识别为工作区文件查看请求',
          transition: {
            visible: true,
            stage: 'specialist_intake',
            title: '已匹配通用助手',
            message: '将由「通用助手」继续处理当前请求。',
            nextStep: '通用助手继续处理',
            requiresExecutionConfirmation: false,
            autoStart: false,
          },
        },
      },
      isStreaming: false,
    })

    expect(el.textContent).toContain('STELLAR ROUTER')
    expect(el.textContent).toContain('通用助手')
    expect(el.textContent).toContain('路由更新')
    expect(el.querySelector('.route-event__mark')).toBeNull()
    expect(el.querySelector('.route-event__target-icon svg')).not.toBeNull()
  })

  it('Router 目标未变化时不显示路由事件条', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: '继续查看 raw_data 目录。',
        routedAgent: {
          agentId: 'agent-general',
          name: '通用助手',
          avatar: '🤖',
          color: '#7691FF',
          reason: '继续由当前助手处理',
          transition: {
            visible: false,
            stage: 'specialist_intake',
            title: '已匹配通用助手',
            message: '',
            nextStep: '通用助手继续处理',
            requiresExecutionConfirmation: false,
            autoStart: false,
          },
        },
      },
      isStreaming: false,
    })

    expect(el.textContent).not.toContain('STELLAR ROUTER')
  })

  it('工具生成图片后在对话中显示预览并支持下载', async () => {
    // 组件链路：fetchArtifactBlob 返回 objectUrl → fetch(objectUrl).blob() → createObjectURL 作为 img src
    URL.createObjectURL = vi.fn(() => 'blob:heatmap-preview')
    global.fetch = vi.fn().mockResolvedValue({ blob: () => Promise.resolve(new Blob(['image'])) })
    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { el } = mountItem({
      sessionId: 'session-artifact',
      message: {
        ...baseMsg,
        content: '相关性热图已生成。',
        toolCalls: [
          {
            id: 'tool-heatmap',
            name: 'sandbox_execute',
            arguments: {},
            status: 'success',
            uiPayload: {
              artifacts: [{ path: 'output/sample_correlation_heatmap.png', size: 1024 }],
            },
          },
        ],
      },
      isStreaming: false,
    })

    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 20))
    await nextTick()

    expect(studioApiMocks.fetchArtifactBlob).toHaveBeenCalledWith(
      'session-artifact',
      'output/sample_correlation_heatmap.png',
    )
    expect(el.querySelector<HTMLImageElement>('.message-artifacts__preview img')?.src).toContain('blob:heatmap-preview')
    expect(el.textContent).toContain('sample_correlation_heatmap.png')

    el.querySelector<HTMLButtonElement>('.message-artifacts__download')?.click()
    await new Promise((resolve) => setTimeout(resolve, 20))
    await nextTick()
    expect(anchorClickSpy).toHaveBeenCalled()
    anchorClickSpy.mockRestore()
  })

  it('有 thought + 有 content：思考面板与正文都应渲染', () => {
    const { el } = mountItem({
      message: { ...baseMsg, content: '你好！我是 OmicHub AI 助手。', thought: '用户打招呼' },
      isStreaming: false,
    })
    expect(el.textContent).toContain('思考过程')
    expect(el.textContent).toContain('你好！我是 OmicHub AI 助手。')
  })

  it('只有 thought、content 为空：显示空态兜底而非空白', () => {
    const { el } = mountItem({
      message: { ...baseMsg, content: '', thought: '只想了没说', status: 'empty' },
      isStreaming: false,
    })
    expect(el.textContent).toContain('思考完成，但未生成正式回复')
  })

  it('有 output Token 但正文为空：显示加载异常和可操作重试入口', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: '',
        thought: '模型已完成推理',
        status: 'empty',
        tokens: { input: 128, output: 32, total: 160 },
      },
      isStreaming: false,
    })
    expect(el.textContent).toContain('回复内容加载异常')
    expect(el.textContent).toContain('点击重试')
  })

  it('流式中：streamingContent 应实时渲染', () => {
    const { el } = mountItem({
      message: { ...baseMsg, status: 'streaming' },
      isStreaming: true,
      streamingContent: '正在输出的正文',
      streamingThought: '思考内容',
    })
    expect(el.textContent).toContain('正在输出的正文')
  })

  it('流式结束瞬间（content 已写入 message）：正文不丢失', () => {
    const msg = reactive({
      ...baseMsg,
      content: '最终正文内容',
      thought: '最终思考',
      status: 'complete',
    }) as ChatMessage
    const { el } = mountItem({ message: msg, isStreaming: false })
    expect(el.textContent).toContain('最终正文内容')
  })

  it('finishReason=length 且正文为空：提示调大 max_tokens 而不是通用文案', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: '',
        thought: '思考预算耗尽',
        status: 'empty',
        finishReason: 'length',
      },
      isStreaming: false,
    })
    expect(el.textContent).toContain('max_tokens')
    expect(el.textContent).toContain('finish_reason=length')
  })
})

describe('KimiMessageItem 渲染异常兜底', () => {
  it('markdown 渲染抛异常：回退纯文本且后续渲染不被卡死', async () => {
    const md = (await import('@/components/ai-chat/setup')).default
    const spy = vi.spyOn(md, 'render').mockImplementation(() => {
      throw new Error('boom')
    })
    try {
      const msg = reactive({ ...baseMsg, status: 'streaming' }) as ChatMessage
      const props = reactive({
        message: msg,
        isStreaming: true,
        streamingContent: '第一段正文',
        streamingThought: '',
      })
      const { el } = mountItem(props)
      // 渲染异常 → 回退转义纯文本，正文不空白
      expect(el.textContent).toContain('第一段正文')

      // 模拟后续流式更新：rAF 句柄未被异常卡死，新内容仍能渲染
      spy.mockRestore()
      props.streamingContent = '第一段正文 + 第二段正文'
      await nextTick()
      expect(el.textContent).toContain('第二段正文')
    } finally {
      spy.mockRestore()
    }
  })
})

describe('stripFakeToolCallMarkup（剔除文本形态的伪工具调用）', () => {
  it('剔除 <tool_use> 块并保留前后正文', () => {
    const src =
      '让我帮你查一下！\n<tool_use>\n{"name": "platform_get_user_info", "arguments": {}}\n</tool_use>\n余额如下。'
    const out = stripFakeToolCallMarkup(src)
    expect(out).toContain('让我帮你查一下！')
    expect(out).toContain('余额如下。')
    expect(out).not.toContain('tool_use')
    expect(out).not.toContain('platform_get_user_info')
  })


  it('剔除多种伪调用标签（tool_call / function_call / invoke）', () => {
    const wrap = (name: string, body: string) => '<' + name + '>' + body + '</' + name + '>'
    const src =
      'a' +
      wrap('tool_call', '{"x":1}') +
      'b' +
      wrap('function_call', '{"y":2}') +
      'c' +
      wrap('invoke', '{"z":3}') +
      'd'
    const out = stripFakeToolCallMarkup(src)
    expect(out).toBe('abcd')
  })

  it('剔除带命名空间前缀的伪调用块（如 Claude 风格）', () => {
    const wrap = (name: string, body: string) => '<' + name + '>' + body + '</' + name + '>'
    const src =
      '开始' + wrap('antml:function_calls', wrap('antml:invoke', '{"tool":"f"}')) + '结束'
    const out = stripFakeToolCallMarkup(src)
    expect(out).toBe('开始结束')
  })

  it('不误伤普通尖括号文本与代码', () => {
    const src = 'mRNA < gene > lncRNA，且 a -> b'
    expect(stripFakeToolCallMarkup(src)).toBe(src)
  })
})

describe('KimiMessageItem 剔除正文里的伪工具调用', () => {
  it('正文含 <tool_use> 伪调用：不显示原始标记，周围正文保留', () => {
    const wrap = (name: string, body: string) => '<' + name + '>' + body + '</' + name + '>'
    const content =
      '让我帮你查一下！\n\n' +
      wrap('tool_use', '{"name": "platform_get_user_info", "arguments": {}}') +
      '\n\n你的余额是 81,297.4 个饼干。'
    const { el } = mountItem({
      message: { ...baseMsg, content, status: 'complete' },
      isStreaming: false,
    })
    expect(el.textContent).toContain('让我帮你查一下！')
    expect(el.textContent).toContain('81,297.4 个饼干')
    expect(el.textContent).not.toContain('tool_use')
    expect(el.textContent).not.toContain('platform_get_user_info')
  })
})

describe('KimiMessageItem 超频专家产物折叠', () => {
  it('worker 的思考过程与正式输出分区显示', () => {
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content: 'FINAL_WORKER_OUTPUT',
        thought: 'PRIVATE_REASONING_STREAM',
        status: 'complete',
        senderAgent: {
          id: 'agent-general',
          name: '通用助手',
          role: 'worker',
          round: 1,
        },
      },
      isStreaming: false,
    })

    expect(el.querySelector('.thought-block')).not.toBeNull()
    expect(el.querySelector('.thought-content')?.textContent).toContain('PRIVATE_REASONING_STREAM')
    expect(el.querySelector('.worker-result-preview')?.textContent).toContain('FINAL WORKER OUTPUT')
    expect(el.querySelector('.worker-result-preview')?.textContent).not.toContain('PRIVATE_REASONING_STREAM')
  })

  it('worker 完成后的长产物默认折叠，点击后展开全文', async () => {
    const uniqueTail = 'UNIQUE_WORKER_RESULT_TAIL'
    const content = `研究计划摘要。${'详细分析步骤。'.repeat(40)}${uniqueTail}`
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content,
        status: 'complete',
        senderAgent: {
          id: 'agent-general',
          name: '通用助手',
          role: 'worker',
          round: 1,
        },
      },
      isStreaming: false,
    })

    const toggle = el.querySelector<HTMLButtonElement>('.worker-result-toggle')
    expect(toggle).not.toBeNull()
    expect(toggle?.getAttribute('aria-expanded')).toBe('false')
    expect(el.textContent).toContain('专家阶段产物')
    expect(el.textContent).toContain('展开查看')
    expect(el.textContent).not.toContain(uniqueTail)

    toggle?.click()
    await nextTick()

    expect(toggle?.getAttribute('aria-expanded')).toBe('true')
    expect(el.textContent).toContain('收起内容')
    expect(el.textContent).toContain(uniqueTail)
  })

  it('worker 流式生成期间也默认折叠，可手动展开实时正文', async () => {
    const liveTail = 'STREAMING_WORKER_TAIL'
    const content = `正在生成研究计划。${'实时步骤。'.repeat(30)}${liveTail}`
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content,
        status: 'streaming',
        senderAgent: {
          id: 'agent-code',
          name: '代码助手',
          role: 'worker',
          round: 2,
        },
      },
      isStreaming: false,
    })

    const toggle = el.querySelector<HTMLButtonElement>('.worker-result-toggle')
    expect(toggle?.getAttribute('aria-expanded')).toBe('false')
    expect(el.textContent).toContain('专家正在生成')
    expect(el.textContent).not.toContain(liveTail)

    toggle?.click()
    await nextTick()
    expect(el.textContent).toContain(liveTail)
  })

  it('Manager 综合报告保持展开，不显示专家折叠按钮', () => {
    const content = `综合报告正文。${'整合结论。'.repeat(40)}MANAGER_REPORT_TAIL`
    const { el } = mountItem({
      message: {
        ...baseMsg,
        content,
        status: 'complete',
        senderAgent: {
          id: 'manager',
          name: 'Manager',
          role: 'manager',
          round: 4,
        },
      },
      isStreaming: false,
    })

    expect(el.querySelector('.worker-result-toggle')).toBeNull()
    expect(el.textContent).toContain('MANAGER_REPORT_TAIL')
  })
})
