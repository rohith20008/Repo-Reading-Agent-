export type AiProviderState =
  | 'ready'
  | 'unchecked'
  | 'checking'
  | 'invalid_configuration'
  | 'invalid_endpoint'
  | 'unavailable'
  | 'timeout'
  | 'model_missing'
  | 'error'

export interface AiStatus {
  configured: boolean
  provider: string | null
  model: string | null
  /** Host only, for display. */
  endpoint: string | null
  state: AiProviderState
  message: string
  reachable: boolean | null
  modelAvailable: boolean | null
  detail?: string | null
}

export function aiStatusLabel(status: AiStatus | null): string {
  if (!status) return 'Checking AI status…'
  switch (status.state) {
    case 'ready': return 'Ollama connected'
    case 'model_missing': return 'Ollama model missing'
    case 'unavailable': return 'Ollama unavailable'
    case 'timeout': return 'Ollama timed out'
    case 'invalid_endpoint': return 'Invalid Ollama endpoint'
    case 'invalid_configuration': return 'AI not configured'
    case 'unchecked': return 'AI status unchecked'
    case 'checking': return 'Checking Ollama…'
    case 'error': return 'Ollama status error'
  }
}
