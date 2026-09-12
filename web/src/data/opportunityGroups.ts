export type CompanyOpportunityGroup = {
  companyId: string
  company: any
  opportunities: any[]
  moleculeCount: number
  maxScore: number
  priority: string
  signalCount: number
  latestEvidence: string | null
  topContact: any | null
  readiness: 'ready' | 'research'
}

const priorityRank: Record<string, number> = { HOT: 3, HIGH: 2, REVIEW: 1 }

function dateValue(value: any) {
  const parsed = value ? Date.parse(String(value)) : NaN
  return Number.isNaN(parsed) ? 0 : parsed
}

function latestFor(lead: any) {
  return (lead.evidence || []).map((item: any) => item.date).filter(Boolean).sort((a: string, b: string) => dateValue(b) - dateValue(a))[0] || null
}

export function groupCompanyOpportunities(leads: any[]): CompanyOpportunityGroup[] {
  const groups = new Map<string, CompanyOpportunityGroup>()
  for (const lead of leads || []) {
    const companyId = String(lead.account?.company_id || lead.opportunity?.company_id || lead.account?.company || 'unknown-company')
    const existing = groups.get(companyId)
    if (existing) {
      existing.opportunities.push(lead)
      continue
    }
    groups.set(companyId, {
      companyId,
      company: lead.account || { company: 'Unknown company' },
      opportunities: [lead],
      moleculeCount: 0,
      maxScore: 0,
      priority: 'REVIEW',
      signalCount: 0,
      latestEvidence: null,
      topContact: null,
      readiness: 'research',
    })
  }
  return Array.from(groups.values()).map((group) => {
    const opportunities = [...group.opportunities].sort((a, b) => {
      const p = (priorityRank[b.opportunity?.priority] || 0) - (priorityRank[a.opportunity?.priority] || 0)
      return p || Number(b.opportunity?.score || 0) - Number(a.opportunity?.score || 0)
    })
    const latest = opportunities.flatMap((lead) => lead.evidence || []).map((item: any) => item.date).filter(Boolean).sort((a: string, b: string) => dateValue(b) - dateValue(a))[0] || null
    const signalKeys = new Set(opportunities.flatMap((lead) => (lead.evidence || []).flatMap((item: any) => (item.signal_types || []).map((signal: string) => `${item.url || item.source_key || item.title || 'source'}:${signal}`))))
    const contacts = opportunities.flatMap((lead) => lead.contacts || [])
    return {
      ...group,
      opportunities,
      moleculeCount: opportunities.length,
      maxScore: Math.max(...opportunities.map((lead) => Number(lead.opportunity?.score || 0)), 0),
      priority: opportunities[0]?.opportunity?.priority || 'REVIEW',
      signalCount: signalKeys.size,
      latestEvidence: latest,
      topContact: contacts.sort((a: any, b: any) => Number(b.role_fit_score || b.confidence || 0) - Number(a.role_fit_score || a.confidence || 0))[0] || null,
      readiness: opportunities.some((lead) => (lead.contacts || []).length > 0) ? 'ready' : 'research',
    }
  }).sort((a, b) => (priorityRank[b.priority] || 0) - (priorityRank[a.priority] || 0) || b.maxScore - a.maxScore || dateValue(b.latestEvidence) - dateValue(a.latestEvidence))
}

export function filterCompanyOpportunityGroups(groups: CompanyOpportunityGroup[], options: { query?: string; priority?: string; readiness?: string } = {}) {
  const query = String(options.query || '').trim().toLowerCase()
  return groups.map((group) => {
    const opportunities = group.opportunities.filter((lead) => {
      const matchesQuery = !query || JSON.stringify(lead).toLowerCase().includes(query) || String(group.company?.company || '').toLowerCase().includes(query)
      const matchesPriority = !options.priority || lead.opportunity?.priority === options.priority
      const matchesReadiness = !options.readiness || options.readiness === ((lead.contacts || []).length ? 'ready' : 'research')
      return matchesQuery && matchesPriority && matchesReadiness
    })
    return opportunities.length ? { ...group, opportunities, moleculeCount: opportunities.length } : null
  }).filter(Boolean) as CompanyOpportunityGroup[]
}

export function moleculeEvidenceLabel(section: any) {
  const status = String(section?.evidence_status || 'UNKNOWN').toUpperCase()
  return status === 'SUPPORTED' ? 'Evidence-backed summary' : status === 'PARTIAL' ? 'Partial summary — limited public evidence' : 'Intelligence research pending'
}
