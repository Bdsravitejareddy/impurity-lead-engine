export function buildCanonicalContacts(
  contacts: any[],
  opportunityLinks: any[],
  sources: any[],
  companyNames: Map<string, string>,
) {
  const opps = new Map<string, Set<string>>()
  const sourceKeys = new Map<string, Set<string>>()
  opportunityLinks.forEach(link => { if (!link.contact_id) return; const set = opps.get(link.contact_id) || new Set<string>(); if (link.opportunity_id) set.add(link.opportunity_id); opps.set(link.contact_id, set) })
  sources.forEach(source => { if (!source.contact_id) return; const set = sourceKeys.get(source.contact_id) || new Set<string>(); const key = source.url || source.source_url || source.id; if (key) set.add(key); sourceKeys.set(source.contact_id, set) })
  return contacts.map(contact => ({
    ...contact,
    id: contact.id,
    company: companyNames.get(contact.company_id) || 'Unknown company',
    linked_opportunities: opps.get(contact.id)?.size || 0,
    sources: sourceKeys.get(contact.id)?.size || 0,
    quality: Number(contact.contact_quality_score ?? contact.quality_diagnostics?.score ?? contact.contact_confidence ?? 0),
    current_role_confidence: contact.current_role_confidence != null ? Number(contact.current_role_confidence) : contact.quality_diagnostics?.dimensions?.current_role != null ? Number(contact.quality_diagnostics.dimensions.current_role) / 100 : Number(contact.contact_confidence ?? 0),
    contactability: contact.email_status || contact.phone_status || (contact.profile_url ? 'PROFESSIONAL' : 'UNKNOWN'),
    last_verified: contact.last_verified_at || null,
  }))
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
