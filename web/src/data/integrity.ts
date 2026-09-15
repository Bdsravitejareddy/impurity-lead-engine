export function buildCanonicalContacts(
  contacts: any[],
  opportunityLinks: any[],
  sources: any[],
  companyNames: Map<string, string>,
) {
  const opps = new Map<string, Set<string>>()
  const sourceKeys = new Map<string, Set<string>>()
  opportunityLinks.forEach(link => { if (!link.contact_id) return; const set = opps.get(link.contact_id) || new Set<string>(); if (link.opportunity_id) set.add(link.opportunity_id); opps.set(link.contact_id, set) })
  sources.forEach(source => {
    if (!source.contact_id) return
    const status = String(source.status || '').toUpperCase()
    if (status && status !== 'USED') return
    const set = sourceKeys.get(source.contact_id) || new Set<string>()
    const key = source.url || source.source_url || source.id
    if (key) set.add(key)
    sourceKeys.set(source.contact_id, set)
  })
  // The adapter may receive repeated contact objects when a backend query is
  // joined to child rows. Canonical identity is contacts.id: collapse only
  // those repeated IDs while retaining every child relationship/evidence item.
  const byId = new Map<string, any>()
  contacts.forEach((contact, index) => {
    const key = contact.id ? String(contact.id) : `__missing_id_${index}`
    const existing = byId.get(key)
    if (!existing) {
      byId.set(key, { ...contact })
      return
    }
    const merged = { ...existing }
    for (const field of ['evidence_urls', 'evidence', 'professional_themes', 'career', 'technical_evidence']) {
      if (Array.isArray(existing[field]) || Array.isArray(contact[field])) {
        const values = [...(existing[field] || []), ...(contact[field] || [])]
        merged[field] = values.filter((value: any, valueIndex: number, all: any[]) => all.findIndex(candidate => JSON.stringify(candidate) === JSON.stringify(value)) === valueIndex)
      }
    }
    // Keep the first non-null canonical scalar; later joined rows should not
    // overwrite identity fields with partial/null values.
    for (const [field, value] of Object.entries(contact)) if ((merged[field] == null || merged[field] === '') && value != null && value !== '') merged[field] = value
    byId.set(key, merged)
  })
  return Array.from(byId.values()).map(contact => ({
    ...contact,
    id: contact.id,
    company: companyNames.get(contact.company_id) || 'Unknown company',
    linked_opportunities: opps.get(contact.id)?.size || 0,
    sources: sourceKeys.get(contact.id)?.size || 0,
    quality: contact.contact_quality_score ?? contact.quality_diagnostics?.score ?? null,
    current_role_confidence: readCurrentRoleConfidence(contact),
    contactability: contact.email_status || contact.phone_status || (contact.profile_url ? 'PROFESSIONAL' : 'UNKNOWN'),
    last_verified: contact.last_verified_at || null,
  }))
}

export function readCurrentRoleConfidence(contact: any) {
  const diagnostic = String(contact.quality_diagnostics?.diagnostics?.current_role || '').toLowerCase()
  if (/missing|not established|stale/.test(diagnostic)) return null
  if (contact.current_role_confidence != null) return Number(contact.current_role_confidence)
  return contact.quality_diagnostics?.dimensions?.current_role != null ? Number(contact.quality_diagnostics.dimensions.current_role) / 100 : null
}

const toPercent = (value: any) => {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return number > 0 && number <= 1 ? number * 100 : number
}

const contactabilityRank: Record<string, number> = { VERIFIED_PUBLIC: 5, PATTERN_CONFIRMED: 4, PROFESSIONAL: 3, ROLE_ONLY: 2, STALE: 1, UNKNOWN: 0 }

export function formatQuality(value: any) {
  if (value === null || value === undefined || value === '') return 'Not scored'
  const number = Number(value)
  return Number.isFinite(number) ? String(Math.round(number)) : 'Not scored'
}

export function formatRoleConfidence(value: any) {
  if (value === null || value === undefined || value === '') return 'Not established'
  const number = Number(value)
  return Number.isFinite(number) ? `${Math.round(number > 0 && number <= 1 ? number * 100 : number)}%` : 'Not established'
}

export function isQualifiedContact(contact: any) {
  return Number(contact.quality) >= 70 && toPercent(contact.identity_confidence ?? contact.contact_confidence) >= 70 && toPercent(contact.technical_relevance) >= 55
}

export function rankContactsForOpportunity(contacts: any[]) {
  return [...contacts].sort((a, b) => {
    const qualified = Number(isQualifiedContact(b)) - Number(isQualifiedContact(a))
    if (qualified) return qualified
    const score = Number(b.quality ?? -1) - Number(a.quality ?? -1)
    if (score) return score
    const identity = toPercent(b.identity_confidence ?? b.contact_confidence) - toPercent(a.identity_confidence ?? a.contact_confidence)
    if (identity) return identity
    const technical = toPercent(b.technical_relevance) - toPercent(a.technical_relevance)
    if (technical) return technical
    const reach = (contactabilityRank[String(b.contactability || 'UNKNOWN').toUpperCase()] ?? 0) - (contactabilityRank[String(a.contactability || 'UNKNOWN').toUpperCase()] ?? 0)
    if (reach) return reach
    const role = toPercent(b.current_role_confidence) - toPercent(a.current_role_confidence)
    if (role) return role
    return String(b.last_verified || '').localeCompare(String(a.last_verified || ''))
  })
}

export function summarizeWorkState(jobs: any[] = [], submissions: any[] = []) {
  const counts = jobs.reduce((acc: Record<string, number>, job: any) => { const status = String(job.status || 'UNKNOWN').toUpperCase(); acc[status] = (acc[status] || 0) + 1; return acc }, {})
  const applied = counts.APPLIED || 0
  const pending = jobs.filter(job => !['APPLIED', 'REJECTED', 'FAILED', 'PARTIAL'].includes(String(job.status || '').toUpperCase())).length
  const status = applied > 0 && pending === 0 ? 'APPLIED' : applied > 0 ? 'PARTIAL' : (jobs[0]?.status || 'WAITING')
  const validation = submissions.reduce((acc: Record<string, number>, row: any) => { const value = String(row.validation_status || 'UNKNOWN').toUpperCase(); acc[value] = (acc[value] || 0) + 1; return acc }, {})
  return { status, counts, applied, pending, total: jobs.length, validation, jobs, submissions }
}

export function groupEvidenceBySource(items: any[]) {
  const grouped = new Map<string, any>()
  items.forEach(item => {
    const key = item.url || item.source_record_id || item.id || `${item.title || 'source'}:${item.publisher || ''}`
    const existing = grouped.get(key)
    const signals = Array.from(new Set([...(existing?.signal_types || []), ...(item.signal_types || [])].filter(Boolean)))
    const claims = Array.from(new Set([...(existing?.claims || []), ...(item.claims || [])].filter(Boolean)))
    grouped.set(key, { ...(existing || item), signal_types: signals, claims, source_key: key })
  })
  return Array.from(grouped.values())
}

/** Metrics for the complete opportunity collection, kept separate from the
 * qualified-lead read model so labels cannot conflate the two counts. */
export function summarizeOpportunityMetrics(opportunities: any[]) {
  const qualified = opportunities.filter(opportunity => String(opportunity.status || '').toLowerCase() !== 'dismissed' && Number(opportunity.score || 0) >= 50)
  return {
    total: opportunities.length,
    qualified: qualified.length,
    hot: qualified.filter(opportunity => opportunity.priority === 'HOT').length,
    high: qualified.filter(opportunity => opportunity.priority === 'HIGH').length,
    review: qualified.filter(opportunity => opportunity.priority === 'REVIEW').length,
  }
}
