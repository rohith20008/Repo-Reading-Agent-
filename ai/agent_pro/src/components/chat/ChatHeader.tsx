import { FolderGit2, History, PanelRightClose, PanelRightOpen } from 'lucide-react'

import { aiStatusLabel, type AiStatus } from '../../services/api/aiStatus'
import { Badge } from '../ui/Badge'

interface ChatHeaderProps {
  title: string
  repositoryName: string | null
  /** Show the button that opens the conversation history drawer (narrow layouts). */
  showHistoryButton: boolean
  onOpenHistory: () => void
  activityOpen: boolean
  onToggleActivity: () => void
  aiStatus: AiStatus | null
}

export function ChatHeader({
  title,
  repositoryName,
  showHistoryButton,
  onOpenHistory,
  activityOpen,
  onToggleActivity,
  aiStatus,
}: ChatHeaderProps) {
  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-line px-4 py-3 max-sm:px-3">
      {showHistoryButton && (
        <button
          type="button"
          onClick={onOpenHistory}
          aria-label="Open conversation history"
          className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-surface text-mute transition hover:border-[#454545] hover:text-ink"
        >
          <History className="size-4" aria-hidden="true" />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-sm font-semibold text-ink">{title}</h1>
        <p className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-mute">
          <FolderGit2 className="size-3.5 shrink-0 text-brand" aria-hidden="true" />
          <span className="truncate">{repositoryName ?? 'No repository selected'}</span>
        </p>
      </div>
      <Badge tone={aiStatus?.state === 'ready' ? 'ok' : 'warn'} className="max-sm:hidden">
        {aiStatusLabel(aiStatus)}
      </Badge>
      <button
        type="button"
        onClick={onToggleActivity}
        aria-label={activityOpen ? 'Hide agent activity panel' : 'Show agent activity panel'}
        aria-pressed={activityOpen}
        title="Agent activity and context"
        className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-surface text-mute transition hover:border-[#454545] hover:text-ink aria-pressed:border-brand/50 aria-pressed:text-brand"
      >
        {activityOpen ? <PanelRightClose className="size-4" aria-hidden="true" /> : <PanelRightOpen className="size-4" aria-hidden="true" />}
      </button>
    </header>
  )
}
