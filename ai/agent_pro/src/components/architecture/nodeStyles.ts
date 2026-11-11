import { Boxes, Cable, CircleHelp, Cog, Database, FileCode2, Globe, Library, Monitor, Package, type LucideIcon } from 'lucide-react'

import type { ArchitectureNodeType, ConnectionKind } from '../../types/architecture'

export interface NodeTypeStyle {
  label: string
  icon: LucideIcon
  /** Classes for the icon chip. */
  chip: string
}

export const NODE_TYPE_STYLES: Record<ArchitectureNodeType, NodeTypeStyle> = {
  client: { label: 'Client', icon: Globe, chip: 'bg-white/8 text-ink ring-white/15' },
  frontend: { label: 'Frontend', icon: Monitor, chip: 'bg-info/12 text-info ring-info/25' },
  api: { label: 'API layer', icon: Cable, chip: 'bg-brand/15 text-brand ring-brand/30' },
  service: { label: 'Service', icon: Cog, chip: 'bg-brand/10 text-[#ffa25c] ring-brand/20' },
  database: { label: 'Database', icon: Database, chip: 'bg-ok/12 text-ok ring-ok/25' },
  module: { label: 'Module', icon: Boxes, chip: 'bg-white/6 text-mute ring-white/10' },
  file: { label: 'File', icon: FileCode2, chip: 'bg-white/6 text-mute ring-white/10' },
  symbol: { label: 'Symbol', icon: FileCode2, chip: 'bg-brand/10 text-[#ffa25c] ring-brand/20' },
  external: { label: 'External package', icon: Package, chip: 'bg-info/10 text-info ring-info/25' },
  stdlib: { label: 'Standard library', icon: Library, chip: 'bg-white/8 text-ink ring-white/15' },
  unresolved: { label: 'Unresolved', icon: CircleHelp, chip: 'bg-warn/10 text-warn ring-warn/25' },
}

export const CONNECTION_LABELS: Record<ConnectionKind, string> = {
  http: 'HTTP',
  call: 'Call',
  import: 'Import',
  data: 'Data',
}

/** Edge colours (hex, because SVG strokes cannot use Tailwind classes). */
export const EDGE_COLORS: Record<ConnectionKind, string> = {
  http: '#F47721',
  call: '#9a9a9a',
  import: '#6f6f6f',
  data: '#3ecf8e',
}
