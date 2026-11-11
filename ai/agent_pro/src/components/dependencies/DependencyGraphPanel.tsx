import { Network, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { FilterSelect } from '../analysis/FilterSelect'
import { EmptyState } from '../common/EmptyState'
import { Skeleton } from '../common/LoadingState'
import { ArchitectureDiagram } from '../architecture/ArchitectureDiagram'
import { NodeDetailsPanel } from '../architecture/NodeDetailsPanel'
import { buildModuleDetails } from '../architecture/moduleDetails'
import { PrimaryButton } from '../ui/PrimaryButton'
import { getDependencyGraph, type DependencyGraphData } from '../../services/api/dependencies'
import type { ArchitectureDiagram as Diagram, ArchitectureEdge, ArchitectureNode } from '../../types/architecture'
import { columnLayout } from '../../services/api/architectureLayout'

const MAX_VISIBLE_NODES = 200

function directoryOf(path: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? '.' : path.slice(0, index) || '.'
}

function toNode(node: DependencyGraphData['nodes'][number]): ArchitectureNode {
  const path = node.path ?? (node.type === 'file' ? node.id : null)
  const label = node.label || path?.split('/').pop() || node.id
  const graphTypes: ArchitectureNode['type'][] = ['file', 'symbol', 'external', 'stdlib', 'unresolved']
  const type: ArchitectureNode['type'] = graphTypes.includes(node.type as ArchitectureNode['type'])
    ? node.type as ArchitectureNode['type']
    : 'module'
  const detail = node.type === 'symbol'
    ? `${node.kind ?? 'Symbol'} ${node.qualifiedName ?? label} in ${path ?? 'unknown file'}.`
    : path
      ? `${path}${node.language ? ` (${node.language})` : ''}.`
      : `${node.type}: ${label}.`
  return {
    id: node.id,
    label,
    type,
    subtitle: node.kind ?? node.language ?? node.type,
    description: detail,
    files: path ? [path] : [],
    fileCount: path ? 1 : 0,
    languages: node.language ? [node.language] : [],
    position: { x: 0, y: 0 },
  }
}

function relationshipLabel(edge: DependencyGraphData['edges'][number]): string {
  return `${edge.relation} · ${edge.count}`
}

export function DependencyGraphPanel({ repositoryId }: { repositoryId: string | null }) {
  const [loaded, setLoaded] = useState<{ repositoryId: string; attempt: number; graph: DependencyGraphData } | null>(null)
  const [failed, setFailed] = useState<{ repositoryId: string; attempt: number; message: string } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [relation, setRelation] = useState('all')
  const [module, setModule] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (!repositoryId) return
    let active = true
    getDependencyGraph(repositoryId)
      .then((result) => {
        if (active) setLoaded({ repositoryId, attempt, graph: result })
      })
      .catch((reason: unknown) => {
        if (active) setFailed({ repositoryId, attempt, message: reason instanceof Error ? reason.message : 'The dependency graph could not be loaded.' })
      })
    return () => {
      active = false
    }
  }, [repositoryId, attempt])

  const graph = loaded?.repositoryId === repositoryId && loaded.attempt === attempt ? loaded.graph : null
  const error = failed?.repositoryId === repositoryId && failed.attempt === attempt ? failed.message : null
  const loading = Boolean(repositoryId && !graph && !error)
  const relationOptions = useMemo(() => [
    { value: 'all', label: 'All relationships' },
    ...Array.from(new Set((graph?.edges ?? []).map((edge) => edge.relation))).sort().map((value) => ({ value, label: value })),
  ], [graph])
  const moduleOptions = useMemo(() => {
    const directories = new Set((graph?.nodes ?? []).flatMap((node) => {
      if (!node.path) return []
      const path = node.path.replace(/\\/g, '/')
      return path.includes('/') ? [path.slice(0, path.lastIndexOf('/'))] : ['.']
    }))
    return [{ value: 'all', label: 'All modules' }, ...[...directories].sort().map((value) => ({ value, label: value }))]
  }, [graph])

  const diagram = useMemo<Diagram | null>(() => {
    if (!graph) return null
    const nodesById = new Map(graph.nodes.map((node) => [node.id, node]))
    let edges = graph.edges.filter((edge) => relation === 'all' || edge.relation === relation)
    if (module !== 'all') {
      edges = edges.filter((edge) => [edge.source, edge.target].some((id) => {
        const path = nodesById.get(id)?.path
        return path ? directoryOf(path.replace(/\\/g, '/')) === module : false
      }))
    }

    const degree = new Map<string, number>()
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
    }
    const included = [...degree.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, MAX_VISIBLE_NODES)
      .map(([id]) => id)
    const includedIds = new Set(included)
    edges = edges.filter((edge) => includedIds.has(edge.source) && includedIds.has(edge.target))
    const archEdges: ArchitectureEdge[] = edges.map((edge) => ({
      id: `${edge.relation}:${edge.source}->${edge.target}`,
      source: edge.source,
      target: edge.target,
      kind: edge.relation === 'imports' ? 'import' : 'call',
      label: relationshipLabel(edge),
    }))
    const positions = columnLayout(included, archEdges)
    const archNodes = included.flatMap((id) => {
      const raw = nodesById.get(id)
      const position = positions.get(id)
      return raw && position ? [{ ...toNode(raw), position }] : []
    })
    return {
      view: 'imports',
      title: 'Source dependency graph',
      description: 'Parsed imports, resolved symbol calls and supported type relationships. Arrows are based on stored source evidence.',
      direction: 'LR',
      nodes: archNodes,
      edges: archEdges,
    }
  }, [graph, module, relation])

  const details = useMemo(() => diagram ? buildModuleDetails(diagram, selectedId) : null, [diagram, selectedId])

  if (!repositoryId) return <EmptyState icon={Network} title="Select a repository" description="Choose a repository to load its parsed source dependency graph." />
  if (loading) return <div role="status" aria-label="Loading dependency graph" className="space-y-4"><Skeleton className="h-10 w-full" /><Skeleton className="h-[34rem] w-full" /></div>
  if (error) return <EmptyState icon={Network} title="Dependency graph unavailable" description={error} tone="error" action={<PrimaryButton onClick={() => setAttempt((value) => value + 1)}>Retry</PrimaryButton>} />
  if (!graph || graph.nodes.length === 0 || !diagram?.nodes.length) {
    return <EmptyState icon={Network} title="No source relationships found" description="Scan and parse this repository to build a graph from its source imports and relationships." />
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <PrimaryButton
          variant="secondary"
          icon={<RefreshCw className="size-4" aria-hidden="true" />}
          onClick={() => setAttempt((value) => value + 1)}
        >
          Refresh graph
        </PrimaryButton>
        <FilterSelect label="Filter relationships" value={relation} onChange={(value) => { setRelation(value); setSelectedId(null) }} options={relationOptions} className="w-56" />
        <FilterSelect label="Filter by module" value={module} onChange={(value) => { setModule(value); setSelectedId(null) }} options={moduleOptions} className="w-56" />
        <span className="text-xs text-mute" aria-live="polite">
          Showing {diagram.nodes.length} nodes and {diagram.edges.length} relationships
          {diagram.nodes.length === MAX_VISIBLE_NODES || graph.truncated ? ' (large graph capped; use filters to narrow it)' : ''}
        </span>
      </div>
      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_21rem]">
        <ArchitectureDiagram diagram={diagram} selectedId={selectedId} onSelect={setSelectedId} />
        <NodeDetailsPanel details={details} repositoryId={repositoryId} onSelectNode={setSelectedId} className="max-h-[38rem] overflow-y-auto" />
      </div>
    </div>
  )
}
