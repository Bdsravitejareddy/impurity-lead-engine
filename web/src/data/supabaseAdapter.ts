import { supabase } from './supabase'
import { emptyIntelligence, normalizeContactIntelligence } from './contactIntelligence'

export async function loadSupabaseData() {
  if (!supabase) throw new Error('supabase_not_configured')
  const [opportunities, signals, contacts, opportunityContacts, contactEvidence, runs, sources, positions, education, works, problems, themes, jtbd, claims, notes, history, conflicts, researchRuns] = await Promise.all([
    supabase.from('opportunities').select('*, companies(*), molecules(*)').neq('status', 'dismissed').order('score', { ascending: false }),
    supabase.from('signals').select('id,company_id,molecule_id,source_type,signal_type,source_url,source_record_id,evidence_text,event_date,confidence,base_weight,fingerprint').order('event_date', { ascending: false }),
    supabase.from('contacts').select('id,company_id,display_name,title,department,profile_url,primary_email,email_status,primary_phone,phone_status,role_fit_score,contact_confidence,last_verified_at'),
    supabase.from('opportunity_contacts').select('opportunity_id,contact_id,role_fit_score,rank,rationale'),
    supabase.from('contact_evidence').select('contact_id,source_url,evidence_type,observed_at,evidence_text,source_type,metadata_json'),
    supabase.from('crawl_runs').select('id,started_at,completed_at,source_adapter,status,records_seen,records_inserted,errors,duration_seconds').order('started_at', { ascending: false }).limit(10),
    supabase.from('contact_sources').select('*'),
    supabase.from('contact_positions').select('*'),
    supabase.from('contact_education').select('*'),
    supabase.from('contact_works').select('*'),
    supabase.from('contact_problems').select('*'),
    supabase.from('contact_themes').select('*'),
    supabase.from('contact_jtbd').select('*'),
    supabase.from('contact_claims').select('*'),
    supabase.from('contact_notes').select('*'),
    supabase.from('contact_history').select('*').order('changed_at', { ascending: false }),
    supabase.from('contact_conflicts').select('*').eq('status','OPEN'),
    supabase.from('contact_research_runs').select('*').order('created_at', { ascending: false }),
  ])
  for (const result of [opportunities, signals, contacts, opportunityContacts, contactEvidence, runs, sources, positions, education, works, problems, themes, jtbd, claims, notes, history, conflicts, researchRuns]) if (result.error) throw result.error
  const intelTables = {sources: sources.data ?? [], positions: positions.data ?? [], education: education.data ?? [], works: works.data ?? [], problems: problems.data ?? [], themes: themes.data ?? [], jtbd: jtbd.data ?? [], claims: claims.data ?? [], notes: notes.data ?? [], history: history.data ?? [], conflicts: conflicts.data ?? [], researchRuns: researchRuns.data ?? []}
  const contactEvidenceById = new Map<string, any[]>()
  ;(contactEvidence.data ?? []).forEach((e: any) => { const items = contactEvidenceById.get(e.contact_id) ?? []; if (!items.some((x: any) => x.source_url === e.source_url && x.evidence_type === e.evidence_type)) items.push(e); contactEvidenceById.set(e.contact_id, items) })
  const linksByOpportunity = new Map<string, any[]>()
  ;(opportunityContacts.data ?? []).forEach((link: any) => { const list = linksByOpportunity.get(link.opportunity_id) ?? []; list.push(link); linksByOpportunity.set(link.opportunity_id, list) })
  const contactByCompany = new Map<string, any[]>()
  ;(contacts.data ?? []).forEach((c: any) => {
    const list = contactByCompany.get(c.company_id) ?? []
    const evidence = contactEvidenceById.get(c.id) ?? []
    const metadata = evidence.map((e: any) => e.metadata_json || {}).reduce((acc: any, item: any) => ({ ...acc, ...item }), {})
    list.push({ id: c.id, name: c.display_name, title: c.title, function: c.department, profile_url: c.profile_url, email: c.primary_email, email_status: c.email_status, mailbox_verified: c.email_status === 'VERIFIED_PUBLIC', phone: c.primary_phone, phone_status: c.phone_status, role_fit_score: c.role_fit_score, confidence: Number(c.contact_confidence ?? 0), last_verified_at: c.last_verified_at, current_status: metadata.current_status || (evidence.some((e: any) => ['company_site','company_profile','professional_profile','conference','company_press','company_pdf','association','registry'].includes(e.source_type)) ? 'PROFESSIONAL_PROFILE' : 'UNKNOWN'), evidence_urls: evidence.map((e: any) => e.source_url).filter(Boolean), evidence, professional_themes: metadata.professional_themes || [], jtbd: metadata.jtbd || metadata.inferred_jtbd || [], why: metadata.why || metadata.observed_context, recommended_channel: metadata.recommended_channel, intelligence: normalizeContactIntelligence(c.id, intelTables) })
    contactByCompany.set(c.company_id, list)
  })
  const signalByPair = new Map<string, any[]>()
  ;(signals.data ?? []).forEach((s: any) => { const key = `${s.company_id}:${s.molecule_id}`; const list = signalByPair.get(key) ?? []; list.push(s); signalByPair.set(key, list) })
  const leads = (opportunities.data ?? []).map((o: any) => {
    const company = o.companies ?? {}; const molecule = o.molecules ?? {}; const pair = signalByPair.get(`${o.company_id}:${o.molecule_id}`) ?? []
    const links = [...(linksByOpportunity.get(o.id) ?? [])].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
    const linkedIds = new Set(links.map((link: any) => link.contact_id))
    const companyContacts = [...(contactByCompany.get(o.company_id) ?? [])].sort((a: any, b: any) => Number(linkedIds.has(b.id)) - Number(linkedIds.has(a.id)) || (b.role_fit_score ?? 0) - (a.role_fit_score ?? 0))
    return { account: { company: company.legal_name || company.normalized_name, domain: company.domain, buyer_type: company.company_type || 'pharmaceutical manufacturer/developer' }, opportunity: { molecule: molecule.canonical_name, regulatory_application: pair.find((s: any) => s.source_record_id)?.source_record_id, score: o.score, priority: o.priority, technical_relevance: o.rationale, urgency_bonus: 0 }, evidence: pair.map((s: any) => ({ title: `${s.signal_type} evidence`, url: s.source_url, source: s.source_type, date: s.event_date, technical_context: s.evidence_text, signal_types: [s.signal_type] })), contacts: companyContacts, person_intelligence: { observed: [], inferred: [], unknown: ['Person intelligence is not stored in the production schema.'] }, outreach: { personalization_hook: o.rationale, discovery_question: 'Are there current or upcoming analytical requirements where an external partner could help?' } }
  })
  const latestRun = runs.data?.[0]
  return { leads, candidates: [], metrics: { qualified_ge_50: leads.length, hot: leads.filter((x: any) => x.opportunity.priority === 'HOT').length, high: leads.filter((x: any) => x.opportunity.priority === 'HIGH').length, review: leads.filter((x: any) => x.opportunity.priority === 'REVIEW').length, crawler: latestRun } }
}
