// @vitest-environment jsdom
import { createApp, h, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import AskUserCard from '@/components/ai-chat/AskUserCard.vue'
import type { AskRequest, AskUserObjectReference } from '@/components/ai-chat/types'

const candidate = 'workspace/inputs/counts.csv'

function executionAsk(): AskRequest {
  return {
    questions: [{ question: '请选择用于执行的数据来源：', options: [candidate] }],
    objectRequired: true,
    workspaceCandidates: [{ kind: 'workspace', id: candidate, location: candidate }],
  }
}

let app: ReturnType<typeof createApp> | undefined

function mountCard(onSubmit: (answers: string[], reference?: AskUserObjectReference) => void) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  app = createApp({
    render: () => h(AskUserCard, { ask: executionAsk(), onSubmit }),
  })
  app.mount(root)
  return root
}

function buttonByText(text: string): HTMLButtonElement {
  const button = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.includes(text))
  if (!button) throw new Error(`未找到按钮：${text}`)
  return button as HTMLButtonElement
}

afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.innerHTML = ''
})

describe('AskUserCard execution object selection', () => {
  it('accepts a workspace candidate without entering a separate path', async () => {
    let submitted: [string[], AskUserObjectReference | undefined] | undefined
    mountCard((answers, reference) => { submitted = [answers, reference] })
    await nextTick()

    const candidateOption = document.querySelector<HTMLElement>('.auc-option')
    expect(candidateOption).not.toBeNull()
    candidateOption!.click()
    await nextTick()

    const submitButton = buttonByText('使用此数据继续')
    expect(submitButton.disabled).toBe(false)
    submitButton.click()

    expect(submitted).toEqual([[
      candidate,
    ], {
      path: undefined,
      file: undefined,
      contextRef: { kind: 'workspace', id: candidate, location: candidate },
    }])
  })

  it('accepts a workspace path without selecting a candidate', async () => {
    let submitted: [string[], AskUserObjectReference | undefined] | undefined
    mountCard((answers, reference) => { submitted = [answers, reference] })
    await nextTick()

    const pathInput = document.querySelector<HTMLInputElement>('input[placeholder*="工作区文件名"]')
    expect(pathInput).not.toBeNull()
    pathInput!.value = 'raw/counts.csv'
    pathInput!.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    const submitButton = buttonByText('使用此数据继续')
    expect(submitButton.disabled).toBe(false)
    submitButton.click()

    expect(submitted).toEqual([[''], { path: 'raw/counts.csv', file: undefined, contextRef: undefined }])
  })

  it('lets the user continue discussing instead of supplying data', async () => {
    let submitted: [string[], AskUserObjectReference | undefined] | undefined
    mountCard((answers, reference) => { submitted = [answers, reference] })
    await nextTick()

    buttonByText('先讨论方案').click()

    expect(submitted).toEqual([['先讨论方案（暂不执行）'], undefined])
  })
})
