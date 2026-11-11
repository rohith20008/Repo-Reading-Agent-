import { useCallback, useEffect, useState } from 'react'

import { getAiStatus, type AiStatus } from '../services/api/ai'
import { agentsApi, listAgentWorkflows, type AgentWorkflowRecord } from '../services/api/agents'
import { errorMessage } from '../services/http'
import type { AgentMonitorData } from '../types/agents'

type Status = 'loading' | 'ready' | 'error'

/** Loads the Agent Monitor data (run history) and the AI provider status, with loading, error and retry handling. */
export function useAgentMonitorData() {
  const [status, setStatus] = useState<Status>('loading')
  const [data, setData] = useState<AgentMonitorData | null>(null)
  const [ai, setAi] = useState<AiStatus | null>(null)
  const [workflows, setWorkflows] = useState<AgentWorkflowRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    let pollTimer: number | undefined
    const load = () => Promise.all([agentsApi.getMonitorData(), getAiStatus().catch(() => null), listAgentWorkflows()])
      .then(([result, aiStatus, workflowRows]) => {
        if (cancelled) return
        setData(result)
        setAi(aiStatus)
        setWorkflows(workflowRows)
        setStatus('ready')
        if (workflowRows.some((workflow) => workflow.status === 'running' || workflow.status === 'queued')) {
          pollTimer = window.setTimeout(load, 2500)
        }
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setError(errorMessage(reason, 'Could not load the agent data.'))
        setStatus('error')
      })
    void load()
    return () => {
      cancelled = true
      if (pollTimer !== undefined) window.clearTimeout(pollTimer)
    }
  }, [attempt])

  const reload = useCallback(() => {
    setStatus('loading')
    setError(null)
    setAttempt((value) => value + 1)
  }, [])

  return { status, data, ai, workflows, error, reload }
}
