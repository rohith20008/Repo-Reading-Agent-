import { apiRequest } from '../http'
import type { AiStatus } from './aiStatus'

export type { AiStatus, AiProviderState } from './aiStatus'
export { aiStatusLabel } from './aiStatus'

export const getAiStatus = (check = true, refresh = false) => {
  const params = new URLSearchParams()
  if (check) params.set('check', 'true')
  if (refresh) params.set('refresh', 'true')
  const query = params.toString()
  return apiRequest<AiStatus>(`/ai/status${query ? `?${query}` : ''}`, { timeoutMs: check ? 10_000 : 5_000 })
}

/** The six specialised agents the backend offers (GET /api/ai/agents). */
export interface AgentInfo {
  id: string
  name: string
  role: string
  description: string
  usesAi: boolean
}

export const listAgents = () => apiRequest<AgentInfo[]>('/ai/agents')
