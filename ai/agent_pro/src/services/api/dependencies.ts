import type { AnalysisResult } from '../../types/architecture'
import type { Dependency, DependencyData, DependencyEcosystem, DependencyInsights, DependencyType, DependencyUsage } from '../../types/dependencies'
import { apiRequest, errorMessage } from '../http'
import { blockedReason, getDependencySummary, getGraphStats } from './analysisShared'

export interface DependencyGraphData {
  nodes: {
    id: string
    type: string
    language?: string | null
    label?: string | null
    path?: string | null
    kind?: string | null
    qualifiedName?: string | null
  }[]
  edges: { source: string; target: string; relation: string; depType: string; count: number; names: string[] }[]
  truncated: boolean
}

export function getDependencyGraph(repositoryId: string): Promise<DependencyGraphData> {
  return apiRequest<DependencyGraphData>(
    `/repositories/${encodeURIComponent(repositoryId)}/dependency-graph?types=internal,external,stdlib,unresolved&relations=true&limit=2000`,
    { timeoutMs: 60_000 },
  )
}

/** One row of GET /api/repositories/{id}/packages. */
interface PackageRecord {
  name: string
  version?: string | null
  ecosystem?: string
  type?: string
  usage?: string
  manifest: string
  observedImports?: { file: string; statement: string }[]
  relatedFiles?: string[]
}

const ECOSYSTEMS: DependencyEcosystem[] = ['npm', 'PyPI', 'Cargo', 'Go', 'Maven', 'NuGet', 'Composer', 'RubyGems', 'Other']
const USAGES: DependencyUsage[] = ['imported', 'declared-only', 'tooling']

function describe(record: PackageRecord, ecosystem: DependencyEcosystem, type: DependencyType, imports: number): string {
  const kind = type === 'production' ? 'runtime' : 'development'
  const used = imports > 0 ? ` Imported in ${imports} source file${imports === 1 ? '' : 's'}.` : ''
  return `Declared in ${record.manifest} as a ${kind} dependency (${ecosystem}).${used}`
}

function toDependency(record: PackageRecord): Dependency {
  const ecosystem = ECOSYSTEMS.includes(record.ecosystem as DependencyEcosystem) ? (record.ecosystem as DependencyEcosystem) : 'Other'
  const type: DependencyType = record.type === 'development' ? 'development' : 'production'
  const usage = USAGES.includes(record.usage as DependencyUsage) ? (record.usage as DependencyUsage) : 'declared-only'
  const observedImports = record.observedImports ?? []
  return {
    id: `${ecosystem}:${record.name}:${record.manifest}`,
    name: record.name,
    version: record.version?.trim() || 'not pinned',
    ecosystem,
    type,
    usage,
    manifest: record.manifest,
    description: describe(record, ecosystem, type, new Set(observedImports.map((item) => item.file)).size),
    observedImports,
    relatedFiles: record.relatedFiles ?? [],
  }
}

/** Packages declared in the repository's manifests, plus the repository-wide import classification. */
export async function getDependencies(repositoryId: string): Promise<AnalysisResult<DependencyData>> {
  const { blocked, repository } = await blockedReason(repositoryId, false)
  if (blocked || !repository) return blocked ?? { state: 'failed', message: 'The repository could not be loaded.' }

  try {
    const id = encodeURIComponent(repositoryId)
    const parsed = repository.parsed !== false
    const [packages, summary, stats] = await Promise.all([
      apiRequest<PackageRecord[]>(`/repositories/${id}/packages`),
      parsed ? getDependencySummary(repositoryId) : Promise.resolve(null),
      parsed ? getGraphStats(repositoryId) : Promise.resolve(null),
    ])
    const insights: DependencyInsights | null = {
      parsed,
      counts: summary?.counts ?? { internal: 0, external: 0, stdlib: 0, unresolved: 0 },
      internalFileEdges: summary?.internalFileEdges ?? 0,
      filesWithImports: summary?.filesWithImports ?? 0,
      isAcyclic: stats?.isAcyclic ?? true,
      circularGroups: (stats?.circularDependencies ?? []).map((group) => ({ size: group.size, files: group.files, exampleCycle: group.exampleCycle })),
      unresolved: summary?.unresolved ?? [],
      cycleNote: stats?.cycleNote ?? '',
      resolutionNote: summary?.resolution ?? '',
    }
    if (packages.length === 0 && !insights.parsed) {
      return { state: 'empty', message: 'No package manifest (package.json, requirements.txt, pyproject.toml, ...) was found in this repository.' }
    }
    return {
      state: 'ready',
      data: {
        dependencies: packages.map(toDependency),
        analysedAt: repository.lastParsedAt ?? repository.lastAnalysed ?? new Date().toISOString(),
        insights,
      },
    }
  } catch (error) {
    return { state: 'failed', message: errorMessage(error, 'The dependency analysis could not be loaded.') }
  }
}
