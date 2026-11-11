import type { AgentId } from '../../types/agents'
import type { AgentResultRecord, AgentStepRecord, ChatMessage } from '../../types/chat'

interface WorkflowMessageDto {
  id: string
  requestId?: string | null
  selectedAgents?: string[]
  agentResults?: AgentResultRecord[]
  agentStatuses?: Record<string, string>
  stage?: string
  durationMs?: number
  errors?: { agent: string; message: string }[]
}

export function workflowMessageFields(dto: WorkflowMessageDto): Pick<
  ChatMessage,
  'requestId' | 'selectedAgents' | 'agentResults' | 'agentStatuses' | 'executionStage' | 'durationMs' | 'errors' | 'agentSteps' | 'evidenceFiles'
> {
  const selectedAgents = dto.selectedAgents as AgentId[] | undefined
  const evidenceFiles = [...new Map(
    (dto.agentResults ?? []).flatMap((result) => (result.evidence ?? [])
      .filter((evidence): evidence is typeof evidence & { path: string } => Boolean(evidence.path))
      .map((evidence) => {
        const line = evidence.focusLine ?? evidence.startLine
        const file = {
          path: evidence.path,
          line,
          reason: evidence.reason ?? 'Retrieved as repository evidence for this response.',
        }
        return [`${file.path}:${line ?? ''}`, file] as const
      })),
  ).values()]
  const agentSteps: AgentStepRecord[] | undefined = selectedAgents?.map((agentId, index) => {
    const state = dto.agentStatuses?.[agentId] ?? 'completed'
    return {
      id: `${dto.id}-workflow-step-${index}`,
      agentId,
      label: `Agent ${state}`,
      state: state === 'running' ? 'running' : 'done',
    }
  })

  return {
    requestId: dto.requestId ?? undefined,
    selectedAgents,
    agentResults: dto.agentResults,
    agentStatuses: dto.agentStatuses,
    executionStage: dto.stage,
    durationMs: dto.durationMs,
    errors: dto.errors,
    agentSteps,
    evidenceFiles,
  }
}
