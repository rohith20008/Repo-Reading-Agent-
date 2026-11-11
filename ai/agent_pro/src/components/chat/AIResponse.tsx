import type { ChatMessage } from '../../types/chat'
import { Markdown } from '../ui/Markdown'
import { FileReference } from './FileReference'

interface AIResponseProps {
  message: ChatMessage
  onOpenFile: (path: string, line?: number) => void
}

/** A finished assistant answer: rendered Markdown plus clickable chips for the files it cites. */
export function AIResponse({ message, onOpenFile }: AIResponseProps) {
  const files = message.files ?? []
  const evidenceFiles = message.evidenceFiles ?? []
  return (
    <div className="min-w-0">
      <Markdown source={message.content} onFileReference={onOpenFile} />
      {files.length > 0 && (
        <section aria-label="Files referenced in this answer" className="mt-4 border-t border-line pt-3">
          <p className="mb-2 text-[0.6875rem] font-semibold tracking-wide text-mute uppercase">Files referenced ({files.length})</p>
          <div className="flex flex-wrap gap-2">
            {files.map((file) => (
              <FileReference key={file.path} file={file} onOpen={onOpenFile} />
            ))}
          </div>
        </section>
      )}
      {evidenceFiles.length > 0 && (
        <section aria-label="Repository evidence retrieved for this answer" className="mt-4 border-t border-line pt-3">
          <p className="mb-2 text-[0.6875rem] font-semibold tracking-wide text-mute uppercase">
            Retrieved repository evidence — not cited in the answer ({evidenceFiles.length})
          </p>
          <div className="flex flex-wrap gap-2">
            {evidenceFiles.map((file) => (
              <FileReference key={`${file.path}:${file.line ?? ''}`} file={file} onOpen={onOpenFile} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
