export async function loadLocalData() {
  const response = await fetch('/data.json', { cache: 'no-store' })
  if (!response.ok) throw new Error(`local_data_${response.status}`)
  const data = await response.json()
  try {
    const supplementalResponse = await fetch('/supplemental_contacts.json', { cache: 'no-store' })
    if (supplementalResponse.ok) {
      const supplemental = await supplementalResponse.json()
      const byCompany = new Map((supplemental ?? []).map((item: any) => [String(item.company).toLowerCase(), item.contacts ?? []]))
      data.leads = (data.leads ?? []).map((lead: any) => {
        const extra = byCompany.get(String(lead.account?.company ?? '').toLowerCase()) ?? []
        const existing = new Set((lead.contacts ?? []).map((contact: any) => String(contact.name).toLowerCase()))
        return { ...lead, contacts: [...(lead.contacts ?? []), ...extra.filter((contact: any) => !existing.has(String(contact.name).toLowerCase()))] }
      })
    }
  } catch { /* supplemental local intelligence is optional */ }
  const seen = new Map<string, any>()
  ;(data.leads ?? []).forEach((lead: any) => (lead.contacts ?? []).forEach((contact: any) => {
    const key = `${String(contact.name || '').toLowerCase()}::${String(lead.account?.company || '').toLowerCase()}`
    const existing = seen.get(key)
    const opportunityCount = (existing?.linked_opportunities || 0) + 1
    seen.set(key, { ...(existing || contact), id: contact.id || `local-${key}`, company: lead.account?.company || 'Unknown company', linked_opportunities: opportunityCount, sources: new Set([...(existing?.evidence_urls || []), ...(contact.evidence_urls || [])]).size, quality: contact.role_fit_score || contact.confidence || 0, current_role_confidence: contact.confidence || 0, contactability: contact.email_status || (contact.profile_url ? 'PROFESSIONAL' : 'UNKNOWN'), last_verified: contact.last_verified_at || null })
  }))
  data.canonicalContacts = Array.from(seen.values()).map((item: any) => ({ ...item, display_name: item.display_name || item.name }))
  data.leads = (data.leads ?? []).map((lead: any) => ({ ...lead, account: { ...(lead.account || {}), company_id: lead.account?.company_id || lead.account?.company || 'local-company' }, opportunity: { ...(lead.opportunity || {}), company_id: lead.account?.company_id || lead.account?.company || 'local-company', molecule_id: lead.opportunity?.molecule_id || lead.opportunity?.molecule } }))
  data.moleculeIntelligence = data.moleculeIntelligence || Object.fromEntries((data.leads ?? []).flatMap((lead: any) => (lead.moleculeIntelligence || []).length ? [[lead.opportunity.molecule_id, lead.moleculeIntelligence]] : []))
  data.pipeline = data.pipeline || {}
  return data
}
