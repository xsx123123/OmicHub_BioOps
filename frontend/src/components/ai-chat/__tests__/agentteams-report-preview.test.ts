// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AgentTeamsReportPreview from '../AgentTeamsReportPreview.vue'

describe('AgentTeamsReportPreview', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('loads an allowed Case report into a script-only sandbox with CSP', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      '<html><head></head><body><script>window.rendered = true</script></body></html>',
      { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } },
    )))
    const host = document.createElement('div')
    document.body.appendChild(host)
    createApp(AgentTeamsReportPreview, {
      caseId: 'case-1',
      sourceUrl: '/api/v1/agent-teams/cases/case-1/artifacts/report.html',
    }).mount(host)

    host.querySelector<HTMLButtonElement>('button')?.click()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()

    const frame = document.body.querySelector<HTMLIFrameElement>('iframe')
    expect(frame?.getAttribute('sandbox')).toBe('allow-scripts')
    expect(frame?.getAttribute('sandbox')).not.toContain('allow-same-origin')
    expect(frame?.srcdoc).toContain('Content-Security-Policy')
    expect(frame?.srcdoc).toContain("connect-src 'none'")
  })

  it('rejects report URLs outside the current Case prefix', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const host = document.createElement('div')
    document.body.appendChild(host)
    createApp(AgentTeamsReportPreview, {
      caseId: 'case-1',
      sourceUrl: 'https://example.test/untrusted/report.html',
    }).mount(host)

    host.querySelector<HTMLButtonElement>('button')?.click()
    await nextTick()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('不属于当前 Case')
  })
})
