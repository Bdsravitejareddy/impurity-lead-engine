type FailureDescription = { title: string; explanation: string; action: string }

const descriptions: Record<string, FailureDescription> = {
  company_site_transport: {
    title: 'Company website could not be reached',
    explanation: 'The company website did not respond or blocked the request, so no evidence was collected from it.',
    action: 'Check the website URL or retry the run later.',
  },
  europe_pmc_no_match: {
    title: 'No matching research result was found',
    explanation: 'The research provider returned no publication that matched the company, molecule, or impurity query.',
    action: 'Review the search terms or try again after new research is available.',
  },
  'FDA baseline only': {
    title: 'Only baseline FDA evidence was available',
    explanation: 'The run completed, but it found no additional corroborating source beyond the FDA baseline.',
    action: 'Treat the result as incomplete and review it before outreach.',
  },
  supabase_not_configured: {
    title: 'Live data is not configured',
    explanation: 'This production build does not have the Supabase connection settings it needs to load live data.',
    action: 'Add the live Supabase URL and publishable key, then rebuild the website.',
  },
}

function cleanCode(value: unknown) {
  return String(value ?? '').trim()
}

export function describeFailure(code: unknown): FailureDescription {
  const normalized = cleanCode(code)
  if (descriptions[normalized]) return descriptions[normalized]
  if (normalized.includes('timeout')) {
    return {
      title: 'The service took too long to respond',
      explanation: 'The request exceeded its time limit, so this stage could not finish safely.',
      action: 'Retry the run. If it keeps happening, check the provider or network status.',
    }
  }
  if (normalized.includes('supabase_query')) {
    return {
      title: 'Live data could not be loaded',
      explanation: 'The database returned an error while the website was loading this stage.',
      action: 'Retry the connection. If it persists, check Supabase logs and permissions.',
    }
  }
  return {
    title: 'The stage did not complete',
    explanation: normalized ? `The system reported: ${normalized}.` : 'The system reported a failure without a detailed reason.',
    action: 'Retry the run and review the worker logs if it fails again.',
  }
}

const failedStatuses = new Set(['FAILED', 'PERMANENT_FAILED', 'ERROR'])
const stageNames: Array<[string, string]> = [
  ['crawler', 'Crawler'],
  ['contactResearch', 'Contact research'],
  ['targetedResearch', 'Targeted research'],
  ['workExport', 'Work export'],
  ['workIngestion', 'Work ingestion'],
]

function failureCodes(row: any): string[] {
  const errors = Array.isArray(row?.errors) ? row.errors : row?.errors ? [row.errors] : []
  const reasons = [row?.stop_reason, row?.failure_reason, row?.error_code, ...errors]
  return Array.from(new Set(reasons.map(cleanCode).filter(Boolean)))
}

export function getPipelineFailures(pipeline: Record<string, any> | null | undefined) {
  return stageNames.flatMap(([key, stage]) => {
    const row = pipeline?.[key]
    if (!row) return []
    const codes = failureCodes(row)
    if (!failedStatuses.has(String(row.status || '').toUpperCase()) && !codes.length) return []
    const resolvedCodes = codes.length ? codes : ['unknown_failure']
    return resolvedCodes.map(code => ({ stage, code, ...describeFailure(code) }))
  })
}

export function getCandidateFailures(candidates: any[] | null | undefined) {
  const counts = new Map<string, number>()
  ;(candidates ?? []).forEach(candidate => {
    const status = String(candidate?.status ?? '').toLowerCase()
    const code = cleanCode(candidate?.dominant_failure)
    if (status !== 'failed' || !code || code.startsWith('none')) return
    counts.set(code, (counts.get(code) ?? 0) + 1)
  })
  return Array.from(counts.entries()).map(([code, count]) => ({ code, count, title: describeFailure(code).title }))
}
