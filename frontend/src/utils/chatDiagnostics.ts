export type ChatDiagnosticPhase = 'stream-parse' | 'stream-empty' | 'stream-http-retry' | 'markdown-render' | 'attachment-preview'

export interface ChatDiagnosticPayload {
  phase: ChatDiagnosticPhase
  messageId?: string
  sessionId?: string
  rawResponseSummary?: unknown
  contentPreview?: string
  error?: unknown
}

function serializeError(error: unknown) {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    }
  }
  return error ? { message: String(error) } : undefined
}

export function reportChatDiagnostic(payload: ChatDiagnosticPayload): void {
  const detail = {
    ...payload,
    error: serializeError(payload.error),
    occurredAt: new Date().toISOString(),
  }

  console.error('[OmicHubChatDiagnostic]', detail)

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('omichub:chat-diagnostic', { detail }))
  }
}
