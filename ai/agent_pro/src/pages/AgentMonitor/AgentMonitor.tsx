import { Activity, Bot, CircleAlert, CircleCheck, CircleX, Info, RefreshCw, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { AgentCard } from '../../components/agents/AgentCard'
import { AgentDetailsPanel } from '../../components/agents/AgentDetailsPanel'
import { AgentDiagram } from '../../components/agents/AgentDiagram'
import { AgentTimeline } from '../../components/agents/AgentTimeline'
import { TaskExecutionFlow } from '../../components/agents/TaskExecutionFlow'
import { EmptyState } from '../../components/common/EmptyState'
import { Skeleton } from '../../components/common/LoadingState'
import { PageHeader } from '../../components/common/PageHeader'
import { SectionCard } from '../../components/common/SectionCard'
import { StatCard } from '../../components/common/StatCard'
import { Drawer } from '../../components/ui/Drawer'
import { PrimaryButton } from '../../components/ui/PrimaryButton'
import { useAgentMonitorData } from '../../hooks/useAgentMonitorData'
import { useElementWidth } from '../../hooks/useChatLayout'
import { useAppData } from '../../hooks/useAppData'
import type { AgentId } from '../../types/agents'
import { formatNumber } from '../../utils/format'
import { AGENT_DEFINITIONS } from '../../constants/agents'
import { formatDateTime } from '../../components/analysis/formatDateTime'
import './AgentMonitor.css'

/** Page width at which the agent details panel can sit beside the agent cards. */
const INLINE_DETAILS_MIN_WIDTH = 1000

function MonitorSkeleton() {
  return (
    <div role="status" aria-label="Loading agent monitor" className="space-y-6">
      <div className="grid grid-cols-4 gap-3 @max-[56rem]:grid-cols-2 @max-[28rem]:grid-cols-1">
        {Array.from({ length: 4 }, (_, index) => (
          <StatCard key={index} label="" value="" icon={Bot} loading />
        ))}
      </div>
      <Skeleton className="h-[30rem]" />
      <Skeleton className="h-40" />
    </div>
  )
}

export default function AgentMonitor() {
  const { status, data, ai, workflows, error, reload } = useAgentMonitorData()
  const { repositories } = useAppData()
  const [selectedId, setSelectedId] = useState<AgentId>('supervisor')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [repositoryFilter, setRepositoryFilter] = useState('all')
  const [agentFilter, setAgentFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [pageRef, width] = useElementWidth<HTMLDivElement>(1200)
  const inlineDetails = width >= INLINE_DETAILS_MIN_WIDTH

  const selected = data?.agents.find((agent) => agent.id === selectedId) ?? null
  const selectedTasks = data?.tasks.filter((task) => task.agentId === selectedId) ?? []
  const filteredWorkflows = workflows.filter((workflow) =>
    (repositoryFilter === 'all' || workflow.repositoryId === repositoryFilter)
    && (agentFilter === 'all' || workflow.selectedAgents.includes(agentFilter))
    && (statusFilter === 'all' || workflow.status === statusFilter)
    && (!startDate || workflow.startedAt.slice(0, 10) >= startDate)
    && (!endDate || workflow.startedAt.slice(0, 10) <= endDate))
  const successfulWorkflows = workflows.filter((workflow) => ['completed', 'evidence_only', 'no_evidence'].includes(workflow.status))
  const averageDuration = successfulWorkflows.filter((workflow) => workflow.durationMs > 0).length
    ? Math.round(successfulWorkflows.reduce((total, workflow) => total + workflow.durationMs, 0)
      / successfulWorkflows.filter((workflow) => workflow.durationMs > 0).length)
    : null
  const failedWorkflows = workflows.filter((workflow) => workflow.status === 'failed' || workflow.status === 'partial')
  const runningWorkflows = workflows.filter((workflow) => workflow.status === 'running' || workflow.status === 'queued')
  const executionCountByAgent = AGENT_DEFINITIONS.filter((agent) => agent.id !== 'supervisor').map((agent) => ({
    ...agent,
    count: workflows.filter((workflow) => workflow.selectedAgents.includes(agent.id)).length,
    succeeded: workflows.filter((workflow) => workflow.selectedAgents.includes(agent.id)
      && workflow.agentStatuses[agent.id] === 'completed').length,
    failed: workflows.filter((workflow) => workflow.selectedAgents.includes(agent.id)
      && (workflow.agentStatuses[agent.id] === 'failed' || workflow.agentStatuses[agent.id] === 'unavailable')).length,
  }))

  const select = (id: AgentId) => {
    setSelectedId(id)
    if (!inlineDetails) setDrawerOpen(true)
  }

  const details = selected && <AgentDetailsPanel agent={selected} tasks={selectedTasks} />

  return (
    <div ref={pageRef} className="animate-fade-up space-y-6">
      <PageHeader
        title="Agent Monitor"
        description="See the Supervisor Agent and its specialist agents, what each one has done, and how a request moves through the system."
      />

      {ai && (
        <div
          className={`flex items-start gap-2.5 rounded-lg border p-3 text-xs leading-relaxed text-mute ${
            ai.configured ? 'border-brand/20 bg-brand/5' : 'border-warn/30 bg-warn/5'
          }`}
        >
          {ai.configured ? (
            <Info className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden="true" />
          ) : (
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden="true" />
          )}
          <p>
            <span className="font-semibold text-ink">
              {ai.configured ? `AI provider: ${ai.provider} / ${ai.model}.` : 'No AI provider configured.'}
            </span>{' '}
            {ai.configured ? 'Every run below was recorded by the backend.' : ai.message}
          </p>
        </div>
      )}

      {status === 'loading' && <MonitorSkeleton />}

      {status === 'error' && (
        <EmptyState
          tone="error"
          icon={CircleAlert}
          title="We could not load the agent data"
          description={error ?? 'Something went wrong while loading the Agent Monitor.'}
          action={
            <PrimaryButton icon={<RefreshCw className="size-4" aria-hidden="true" />} onClick={reload}>
              Try again
            </PrimaryButton>
          }
        />
      )}

      {status === 'ready' && data && (
        <>
          <section aria-label="Workflow summary" className="space-y-3">
            <div className="grid grid-cols-4 gap-3 @max-[56rem]:grid-cols-2 @max-[28rem]:grid-cols-1">
              <StatCard label="Total executions" value={formatNumber(workflows.length)} hint="Persisted LangGraph workflows" icon={Activity} />
              <StatCard label="Successful" value={formatNumber(successfulWorkflows.length)} hint="Completed and evidence-only outcomes" icon={CircleCheck} />
              <StatCard label="Running" value={formatNumber(runningWorkflows.length)} hint="Live persisted workflow state" icon={Bot} />
              <StatCard label="Failed / partial" value={formatNumber(failedWorkflows.length)} hint="Includes specialist failures" icon={CircleX} />
            </div>
            <p className="text-right text-xs text-mute">
              Average duration: {averageDuration === null ? 'Not available yet' : `${(averageDuration / 1000).toFixed(1)} s (completed workflows)`}
            </p>
          </section>

          <SectionCard title="Workflow execution history" description="Persisted requests, routing decisions, live stages, agent results and errors. Active records refresh automatically.">
            <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
              <label className="text-xs text-mute">Repository
                <select aria-label="Filter by repository" value={repositoryFilter} onChange={(event) => setRepositoryFilter(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-line bg-surface px-2 text-sm text-ink">
                  <option value="all">All repositories</option>
                  {repositories.map((repository) => <option key={repository.id} value={repository.id}>{repository.name}</option>)}
                </select>
              </label>
              <label className="text-xs text-mute">Agent
                <select aria-label="Filter by agent" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-line bg-surface px-2 text-sm text-ink">
                  <option value="all">All agents</option>
                  {AGENT_DEFINITIONS.filter((agent) => agent.id !== 'supervisor').map((agent) =>
                    <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                </select>
              </label>
              <label className="text-xs text-mute">Status
                <select aria-label="Filter by workflow status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-line bg-surface px-2 text-sm text-ink">
                  <option value="all">All statuses</option>
                  {['queued', 'running', 'completed', 'partial', 'failed', 'evidence_only', 'no_evidence'].map((value) =>
                    <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                </select>
              </label>
              <label className="text-xs text-mute">From
                <input aria-label="Start date filter" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-line bg-surface px-2 text-sm text-ink" />
              </label>
              <label className="text-xs text-mute">To
                <input aria-label="End date filter" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-line bg-surface px-2 text-sm text-ink" />
              </label>
            </div>
            {filteredWorkflows.length === 0 ? (
              <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-mute">
                {workflows.length === 0 ? 'No persisted workflows yet. Run a request from AI Chat, Bug Investigation or Documentation.' : 'No executions match these filters.'}
              </p>
            ) : (
              <div className="space-y-3">
                {filteredWorkflows.map((workflow) => (
                  <details key={workflow.requestId} className="rounded-xl border border-line bg-surface/50">
                    <summary className="cursor-pointer list-none p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-ink">{workflow.question || 'Agent workflow'}</p>
                          <p className="mt-1 text-xs text-mute">{workflow.repositoryName} · {workflow.taskCategory || 'Routing'} · {formatDateTime(workflow.startedAt)}</p>
                          <p className="mt-1 text-xs text-mute">Agents: {workflow.selectedAgents.length ? workflow.selectedAgents.join(', ') : 'Awaiting supervisor selection'}</p>
                        </div>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                          workflow.status === 'failed' || workflow.status === 'partial' ? 'bg-danger/10 text-danger'
                            : workflow.status === 'running' || workflow.status === 'queued' ? 'bg-brand/10 text-brand'
                              : 'bg-ok/10 text-ok'}`}>{workflow.status} · {workflow.stage}</span>
                      </div>
                    </summary>
                    <div className="space-y-3 border-t border-line p-4 text-sm">
                      <p className="text-xs text-mute"><strong className="text-ink">Execution:</strong> {workflow.requestId} · duration {workflow.durationMs ? `${workflow.durationMs} ms` : 'in progress'} · finished {workflow.finishedAt ? formatDateTime(workflow.finishedAt) : 'not yet'}</p>
                      {workflow.routeReason && <p className="text-xs text-mute"><strong className="text-ink">Supervisor:</strong> {workflow.routeReason}</p>}
                      <div className="grid gap-3 md:grid-cols-2">
                        {workflow.agentResults.map((result) => (
                          <article key={result.agent} className="rounded-lg border border-line p-3">
                            <p className="text-xs font-semibold text-ink">{result.agent} · {result.status}</p>
                            {result.answer && <p className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-mute">{result.answer}</p>}
                            {result.error && <p className="mt-2 text-xs text-danger">{result.error}</p>}
                          </article>
                        ))}
                      </div>
                      {workflow.finalResponse && <details><summary className="cursor-pointer text-xs font-semibold text-brand">Final response</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-mute">{workflow.finalResponse}</p></details>}
                      {workflow.errors.map((item, index) => <p key={`${item.agent}-${index}`} className="text-xs text-danger">{item.agent}: {item.message}</p>)}
                    </div>
                  </details>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title="Specialist execution counts" description="Counts and failures from persisted workflow agent statuses.">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {executionCountByAgent.map((agent) => (
                <div key={agent.id} className="flex items-center justify-between rounded-lg border border-line bg-surface/50 p-3 text-xs">
                  <span className="font-medium text-ink">{agent.name}</span>
                  <span className="text-mute">{agent.count} runs · {agent.succeeded} succeeded · {agent.failed} failed</span>
                </div>
              ))}
            </div>
          </SectionCard>

          <section aria-label="Agent summary" className="grid grid-cols-4 gap-3 @max-[56rem]:grid-cols-2 @max-[28rem]:grid-cols-1">
            <StatCard label="Total Agents" value={formatNumber(data.overview.totalAgents)} hint="Supervisor plus six specialists" icon={Bot} />
            <StatCard label="Agents Used" value={formatNumber(data.overview.activeAgents)} hint="Specialists that handled a request" icon={Activity} />
            <StatCard label="Completed Tasks" value={formatNumber(data.overview.completedTasks)} hint="Runs that returned a result" icon={CircleCheck} />
            <StatCard label="Failed Tasks" value={formatNumber(data.overview.failedTasks)} hint="Runs that ended in an error" icon={CircleX} />
          </section>

          <SectionCard
            title="Supervisor and specialist agents"
            description="The Supervisor receives each request and coordinates the specialists. Select an agent to see its details."
          >
            <AgentDiagram agents={data.agents} selectedId={selectedId} onSelect={select} />
          </SectionCard>

          <SectionCard title="How a request moves through the system" description={data.timeline.length === 0 ? 'The stages every request goes through' : 'The stages of the most recent request'}>
            <TaskExecutionFlow stages={data.taskFlow} />
          </SectionCard>

          <div className={inlineDetails ? 'grid grid-cols-[minmax(0,1fr)_24rem] items-start gap-5' : 'block space-y-6'}>
            <div className="@container min-w-0 space-y-6">
              <section aria-label="Agents">
                <h2 className="mb-3 text-sm font-semibold text-ink">Agents ({data.agents.length})</h2>
                <div className="grid grid-cols-2 gap-3 @max-[34rem]:grid-cols-1">
                  {data.agents.map((agent) => (
                    <AgentCard key={agent.id} agent={agent} selected={agent.id === selectedId} onSelect={select} />
                  ))}
                </div>
              </section>

              <SectionCard title="Agent execution timeline" description="The most recent agent runs, oldest first">
                {data.timeline.length === 0 ? (
                  <p className="text-sm text-mute">No agent has run yet. Ask a question in AI Chat.</p>
                ) : (
                  <AgentTimeline items={data.timeline} />
                )}
              </SectionCard>
            </div>

            {inlineDetails && (
              <aside
                aria-label="Agent details"
                className="sticky top-20 max-h-[calc(100dvh/var(--zf,1)-7rem)] overflow-y-auto rounded-card border border-line bg-card shadow-card"
              >
                {details}
              </aside>
            )}
          </div>

          {!inlineDetails && (
            <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title={selected?.name ?? 'Agent details'}>
              {details}
            </Drawer>
          )}
        </>
      )}
    </div>
  )
}
