import { describe, expect, it } from 'vitest'
import {
  inferStudioTaskKind,
  inferStudioTaskStatus,
  parseTaskUnderstanding,
  researchToolMeta,
} from '@/utils/studioPresentation'
import type { StudioSessionDTO } from '@/api/studio'
import type { ChatMessage, ToolCall } from '@/components/ai-chat/types'

const session = (overrides: Partial<StudioSessionDTO> = {}): StudioSessionDTO => ({
  session_id: 's-1', title: 'RNA-seq 差异表达', agent_id: 'agent-1', model_id: 'model-1',
  message_count: 1, status: '', mode: 'studio', created_at: '2026-08-07T00:00:00Z',
  updated_at: '2026-08-07T00:00:00Z', last_message_at: null, ...overrides,
})

const userMessage = (content: string): ChatMessage => ({
  id: 'm-1', role: 'user', content, createdAt: '2026-08-07T00:00:00Z',
})

describe('studio presentation helpers', () => {
  it('infers conservative task icons and status lights', () => {
    expect(inferStudioTaskKind('单细胞亚群注释')).toBe('single-cell')
    expect(inferStudioTaskKind('RNA-seq 差异分析')).toBe('transcriptomics')
    expect(inferStudioTaskKind('我的研究任务')).toBe('generic')
    expect(inferStudioTaskStatus(session(), 's-1', true)).toBe('running')
    expect(inferStudioTaskStatus(session({ status: 'completed' }), 's-2', false)).toBe('completed')
    expect(inferStudioTaskStatus(session({ status: '' }), 's-2', false)).toBe('waiting')
  })

  it('only creates task understanding when domain and goal are parseable', () => {
    expect(parseTaskUnderstanding([userMessage('你好')], false)).toBeNull()
    expect(parseTaskUnderstanding([userMessage('请分析这个 RNA-seq 数据并比较处理组差异')], true)).toMatchObject({
      domain: '转录组学', status: '执行中',
    })
  })

  it('uses the caller fallback domain for a valid general task', () => {
    expect(parseTaskUnderstanding([userMessage('帮我制定一个细胞实验验证方案')], true, '超频协作任务')).toMatchObject({
      domain: '超频协作任务',
      status: '执行中',
    })
  })

  it('maps research tools and provides a non-empty duration fallback', () => {
    const tool: ToolCall = { id: 't-1', name: 'read_file', arguments: {}, status: 'success' }
    expect(researchToolMeta(tool)).toMatchObject({ label: '读取数据文件', duration: '耗时未记录' })

    const knowledgeSearch: ToolCall = {
      id: 't-2', name: 'knowledge_search', arguments: { query: 'RNA-seq' }, status: 'success',
      mcpServer: 'cygnusx-research',
    }
    const webSearch: ToolCall = {
      id: 't-3', name: 'web_search', arguments: { query: 'RNA-seq' }, status: 'success',
      mcpServer: 'cygnusx-research',
    }
    expect(researchToolMeta(knowledgeSearch)).toMatchObject({ label: '检索平台知识库' })
    expect(researchToolMeta(webSearch)).toMatchObject({ label: '检索文献与资料' })
  })
})
