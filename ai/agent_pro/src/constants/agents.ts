import type { AgentDefinition } from '../types/agents'

// Static description of the supervisor and the six specialist agents. Ids match GET /api/ai/agents.
// Live numbers (tasks, last run, status) come from the backend's agent run history.

export const AGENT_DEFINITIONS: AgentDefinition[] = [
  {
    id: 'supervisor',
    name: 'Supervisor Agent',
    shortName: 'Supervisor',
    role: 'Coordinator',
    purpose: 'Receives each request and routes it to one or more relevant specialist agents.',
    description:
      'A LangGraph workflow routes each request to the relevant specialist, runs multiple specialists only for clearly combined requests, and records the evidence-backed results.',
    responsibilities: [
      'Interpret the request and select relevant specialist agents',
      'Pass the relevant repository evidence to that agent',
      'Return the answer with the files it is based on',
      'Record every run so it shows up in this monitor',
    ],
    icon: 'supervisor',
    inputSummary: 'The question, the selected repository and the recent conversation.',
    outputSummary: 'A structured response with references to the files it is based on.',
  },
  {
    id: 'repository-explorer',
    name: 'Repository Understanding Agent',
    shortName: 'Explorer',
    role: 'Repository discovery',
    purpose: 'Finds the files, folders and entry points relevant to a question.',
    description:
      'Uses indexed symbols, repository inventory and architecture data to explain modules, responsibilities, entry points and important files.',
    responsibilities: [
      'Explain repository structure, languages and entry points',
      'Summarise module responsibilities from architecture evidence',
      'Ground explanations in the repository index',
    ],
    icon: 'explorer',
    inputSummary: 'A search intent such as "authentication files".',
    outputSummary: 'A ranked list of relevant paths with a short reason for each.',
  },
  {
    id: 'code-intelligence',
    name: 'Code Analysis Agent',
    shortName: 'Code Intel',
    role: 'Code understanding',
    purpose: 'Reads and explains code, symbols and API relationships.',
    description:
      'Examines the implementation of functions and routes, traces call paths and extracts the snippets that serve as evidence in an answer.',
    responsibilities: [
      'Trace implementations and call paths',
      'Extract representative code evidence',
      'Relate API routes to the code that serves them',
    ],
    icon: 'code',
    inputSummary: 'Files and symbols selected by the Explorer and Architecture agents.',
    outputSummary: 'Annotated code snippets and a plain-language explanation.',
  },
  {
    id: 'bug-investigator',
    name: 'Bug Investigator Agent',
    shortName: 'Bug Investigator',
    role: 'Issue analysis',
    purpose: 'Looks for suspicious patterns and likely causes of problems.',
    description:
      'Reviews error reports and code paths for suspicious patterns and lists possible causes. Its output is a set of potential findings, not proven bugs.',
    responsibilities: [
      'Inspect error paths and stack traces',
      'Flag suspicious patterns as potential findings',
      'Suggest next debugging steps',
    ],
    icon: 'bug',
    inputSummary: 'An issue description, optional stack trace and affected files.',
    outputSummary: 'Ranked potential findings with severity and confidence labels.',
  },
  {
    id: 'dependency-analyst',
    name: 'Dependency Intelligence Agent',
    shortName: 'Dependencies',
    role: 'Package analysis',
    purpose: 'Identifies the packages a repository declares and imports.',
    description:
      'Reads manifests such as package.json and requirements.txt and relates declared packages to the imports found in the code.',
    responsibilities: [
      'List declared dependencies per ecosystem',
      'Relate packages to observed imports',
      'Report usage status without claiming vulnerabilities',
    ],
    icon: 'dependencies',
    inputSummary: 'Manifest files and import statements.',
    outputSummary: 'A dependency inventory grouped by ecosystem and type.',
  },
  {
    id: 'documentation',
    name: 'Documentation Agent',
    shortName: 'Documentation',
    role: 'Technical writing',
    purpose: 'Turns analysis results into structured documentation.',
    description:
      'Writes structured Markdown documents (overview, architecture, module, API and dependency reports) from facts taken from the repository index.',
    responsibilities: [
      'Draft overviews, architecture, module, API and dependency documents',
      'Keep structure and terminology consistent',
      'Cite the files each section is based on',
    ],
    icon: 'documentation',
    inputSummary: 'A requested document type and the repository index.',
    outputSummary: 'A Markdown document with a table of contents.',
  },
  {
    id: 'code-recommendation',
    name: 'Code Recommendation Agent',
    shortName: 'Recommendations',
    role: 'Evidence-based improvements',
    purpose: 'Suggests improvements without modifying repository source code.',
    description:
      'Reviews relevant indexed source evidence and recommends possible improvements with rationale and file references. It never applies changes.',
    responsibilities: [
      'Identify measurable maintainability concerns',
      'Recommend improvements with supporting evidence',
      'Clearly distinguish hypotheses from confirmed facts',
    ],
    icon: 'recommendation',
    inputSummary: 'Relevant source files, symbols and repository relationships.',
    outputSummary: 'Evidence-grounded recommendations; no source files are modified.',
  },
]
