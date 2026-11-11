export class ChatStreamError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'ChatStreamError'
    this.code = code
  }
}

interface StreamEvent {
  type: string
  text?: string
  data?: { code?: string; message?: string }
}

export async function readChatStream(response: Response, onDelta: (text: string) => void): Promise<unknown> {
  if (!response.body) throw new Error('The backend did not provide a streaming response.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completion: unknown
  const processFrame = (frame: string) => {
    const data = frame.split('\n').filter((line) => line.startsWith('data: ')).map((line) => line.slice(6)).join('\n')
    if (!data) return
    const event = JSON.parse(data) as StreamEvent
    if (event.type === 'delta' && event.text) onDelta(event.text)
    else if (event.type === 'complete' && event.data) completion = event.data
    else if (event.type === 'error') {
      throw new ChatStreamError(event.data?.code ?? 'ai_provider_error', event.data?.message ?? 'The AI request failed.')
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      frames.forEach(processFrame)
      if (done) break
    }
    if (buffer.trim()) processFrame(buffer)
  } finally {
    reader.releaseLock()
  }
  if (!completion) throw new Error('The backend ended the stream without a completed chat response.')
  return completion
}
