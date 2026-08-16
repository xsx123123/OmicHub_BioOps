// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import PipelineTaskCard from '@/components/ai-chat/PipelineTaskCard.vue'
import { useAgentHubStore } from '@/stores/agentHub'

vi.mock('@/api/client', () => ({
  default: { post: vi.fn() },
}))

function mountCard(taskId: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentHubStore()
  store.pipelineTasks[taskId] = {
    taskId,
    pipelineType: 'rna_seq',
    status: 'success',
    progress: 100,
    polling: false,
    metrics: {
      differential_gene_count: 12,
      upregulated_count: 7,
      downregulated_count: 5,
    },
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/tasks/:id', component: { template: '<div />' } }],
  })
  const element = document.createElement('div')
  const app = createApp({
    render: () => h(PipelineTaskCard, { taskId, pipelineType: 'rna_seq' }),
  })
  app.use(pinia)
  app.use(router)
  app.mount(element)
  return element
}

describe('PipelineTaskCard', () => {
  beforeEach(() => vi.clearAllMocks())

  it('完成时展示差异基因摘要和结果操作', () => {
    const element = mountCard('11111111-1111-1111-1111-111111111111')
    expect(element.textContent).toContain('已完成')
    expect(element.textContent).toContain('12')
    expect(element.textContent).toContain('上调')
    expect(element.textContent).toContain('查看详细结果')
    expect(element.textContent).toContain('生成可视化')
  })
})
