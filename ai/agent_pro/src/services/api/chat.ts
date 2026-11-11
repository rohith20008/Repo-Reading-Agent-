import { API_BASE, AI_TIMEOUT_MS, ApiRequestError, apiRequest } from '../http'
import type { AgentId } from '../../types/agents'
import type { AgentResultRecord, AgentStepRecord, ChatConversation, ChatMessage, ReferencedFile } from '../../types/chat'
import { ChatStreamError, readChatStream } from './chatStream'
import { workflowMessageFields } from './workflowMessage'

// Chat is stored by the backend (conversations + messages) and answered by the Supervisor agent.

interface MessageDto {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  agent?: string | null
  files?: { path: string; line?: number | null; reason?: string }[]
  warnings?: string[]
  error?: string | null
  requestId?: string | null
  selectedAgents?: string[]
  agentResults?: AgentResultRecord[]
  agentStatuses?: Record<string, string>
  stage?: string
  durationMs?: number
  errors?: { agent: string; message: string }[]
}

interface ConversationSummaryDto {
  id: string
  title: string
  repositoryId: string
  createdAt: string
  updatedAt: string
  messageCount: number
}

interface ConversationDto extends ConversationSummaryDto {
  messages: MessageDto[]
}

interface ChatResponseDto {
  conversationId: string
  userMessage: MessageDto
  assistantMessage: MessageDto
  agent: string
  routeReason?: string
  steps?: { agentId: string; label: string }[]
  warnings?: string[]
  status?: string
  requestId?: string
  selectedAgents?: string[]
  agentStatuses?: Record<string, string>
  agentResults?: AgentResultRecord[]
  errors?: { agent: string; message: string }[]
  stage?: string
  durationMs?: number
}

export interface ChatReply {
  conversationId: string
  userMessage: ChatMessage
  assistantMessage: ChatMessage
}

const files = (dto: MessageDto): ReferencedFile[] =>
  (dto.files ?? []).map((file) => ({ path: file.path, line: file.line ?? undefined, reason: file.reason ?? 'Referenced in the answer' }))

export function toMessage(dto: MessageDto): ChatMessage {
  return {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    createdAt: dto.createdAt,
    status: dto.error ? 'error' : 'complete',
    errorMessage: dto.error ?? undefined,
    files: dto.role === 'assistant' ? files(dto) : undefined,
    agent: (dto.agent as AgentId | null | undefined) ?? undefined,
    warnings: dto.warnings && dto.warnings.length > 0 ? dto.warnings : undefined,
    ...workflowMessageFields(dto),
  }
}

const toConversation = (dto: ConversationSummaryDto, repositoryName: string | null): ChatConversation => ({
  id: dto.id,
  title: dto.title,
  repositoryId: dto.repositoryId,
  repositoryName,
  createdAt: dto.createdAt,
  updatedAt: dto.updatedAt,
  messages: [],
  messageCount: dto.messageCount,
  loaded: dto.messageCount === 0,
})

export const chatApi = {
  async listConversations(repositoryId: string, repositoryName: string | null): Promise<ChatConversation[]> {
    const list = await apiRequest<ConversationSummaryDto[]>(`/repositories/${encodeURIComponent(repositoryId)}/conversations`)
    return list.map((dto) => toConversation(dto, repositoryName))
  },

  async getConversation(id: string, repositoryName: string | null): Promise<ChatConversation> {
    const dto = await apiRequest<ConversationDto>(`/conversations/${encodeURIComponent(id)}`)
    return { ...toConversation(dto, repositoryName), messages: dto.messages.map(toMessage), loaded: true }
  },

  /** Sends one question. Rejects with ApiRequestError (503 = AI not configured, 502 = provider failed, 409 = scan first). */
  async send(repositoryId: string, message: string, conversationId?: string): Promise<ChatReply> {
    const response = await apiRequest<ChatResponseDto>(`/repositories/${encodeURIComponent(repositoryId)}/chat`, {
      method: 'POST',
      body: { message, conversationId },
      timeoutMs: AI_TIMEOUT_MS,
    })
    return toReply(response)
  },

  async stream(repositoryId: string, message: string, conversationId: string | undefined, onDelta: (text: string) => void,
    retryMessageId?: string): Promise<ChatReply> {
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), AI_TIMEOUT_MS)
    let response: Response
    try {
      response = await fetch(`${API_BASE}/api/repositories/${encodeURIComponent(repositoryId)}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ message, conversationId, retryMessageId }),
        signal: controller.signal,
      })
    } catch {
      window.clearTimeout(timer)
      if (controller.signal.aborted) {
        throw new ApiRequestError(0, 'timeout', 'The backend took too long to respond. Check that it is running and try again.')
      }
      throw new ApiRequestError(0, 'backend_unreachable', `Cannot reach the CODEMIND backend at ${API_BASE}. Start it and try again.`)
    }

    try {
      if (!response.ok) {
        let payload: { detail?: { code?: string; message?: string } } = {}
        try { payload = await response.json() as typeof payload } catch { /* use the HTTP fallback below */ }
        throw new ApiRequestError(response.status, payload.detail?.code ?? `http_${response.status}`,
          payload.detail?.message ?? `The backend returned an error (HTTP ${response.status}).`)
      }
      let payload: unknown
      try {
        payload = await readChatStream(response, onDelta)
      } catch (error) {
        if (error instanceof ChatStreamError) throw new ApiRequestError(502, error.code, error.message)
        if (controller.signal.aborted) {
          throw new ApiRequestError(0, 'timeout', 'The AI response took too long. Try again or use a smaller local model.')
        }
        throw error
      }
      return toReply(payload as ChatResponseDto)
    } finally {
      window.clearTimeout(timer)
    }
  },

  rename: (id: string, title: string) =>
    apiRequest<unknown>(`/conversations/${encodeURIComponent(id)}`, { method: 'PATCH', body: { title } }),

  remove: (id: string) => apiRequest<void>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

function toReply(response: ChatResponseDto): ChatReply {
  const steps: AgentStepRecord[] = (response.steps ?? []).map((step, index) => ({
    id: `${response.assistantMessage.id}-step-${index}`,
    agentId: step.agentId as AgentId,
    label: step.label,
    state: 'done',
  }))
  const assistant = toMessage(response.assistantMessage)
  const workflow = workflowMessageFields({
    id: response.assistantMessage.id,
    requestId: response.requestId,
    selectedAgents: response.selectedAgents,
    agentResults: response.agentResults,
    agentStatuses: response.agentStatuses,
    stage: response.stage,
    durationMs: response.durationMs,
    errors: response.errors,
  })
  return {
    conversationId: response.conversationId,
    userMessage: toMessage(response.userMessage),
    assistantMessage: {
      ...assistant,
      agent: (response.agent as AgentId) ?? assistant.agent,
      routeReason: response.routeReason,
      ...workflow,
      agentSteps: steps.length > 0 ? steps : workflow.agentSteps,
      warnings: [...(assistant.warnings ?? []), ...(response.warnings ?? []).filter((w) => !(assistant.warnings ?? []).includes(w))],
    },
  }
}
