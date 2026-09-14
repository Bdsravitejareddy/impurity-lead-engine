import { supabase } from './supabase'
import { emptyIntelligence, normalizeContactIntelligence } from './contactIntelligence'
import { buildCanonicalContacts, groupEvidenceBySource, rankContactsForOpportunity, readCurrentRoleConfidence, summarizeWorkState } from './integrity'

export async function loadSupabaseData() {
  if (!supabase) throw new Error('supabase_not_configured')
  const [opportunities, signals, contacts, companies, opportunityContacts, contactEvidence, runs, sources, positions, education, works, problems, themes, jtbd, claims, notes, history, conflicts, researchRuns, targetedJobs, agentJobs, agentSubmissions, moleculeSections, researchClaims, researchEntities] = await Promise.all([
    supabase.from('opportunities').select('*, companies(*), molecules(*)').neq('status', 'dismissed').order('score', { ascending: false }),
    supabase.from('signals').select('id,company_id,molecule_id,source_type,signal_type,source_url,source_record_id,evidence_text,event_date,confidence,base_weight,fingerprint').order('event_date', { ascending: false }),
    supabase.from('contacts').select('id,company_id,display_name,title,department,profile_url,primary_email,email_status,primary_phone,phone_status,role_fit_score,contact_confidence,last_verified_at'),
    supabase.from('companies').select('id,legal_name,normalized_name'),
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
    supabase.from('targeted_research_jobs').select('*').order('created_at', { ascending: false }).limit(100),
    supabase.from('agent_research_jobs').select('*').order('created_at', { ascending: false }).limit(100),
    supabase.from('agent_research_submissions').select('id,agent_job_id,validation_status,submitted_at,processed_at').order('submitted_at', { ascending: false }).limit(100),
    supabase.from('molecule_intelligence_sections').select('*'),
    supabase.from('research_claims').select('id,entity_id,claim_type,claim_text,source_url,source_class,attribution,provenance,confidence,created_at'),
    supabase.from('research_entities').select('id,entity_type,canonical_name,metadata_json'),
  ])
  for (const result of [opportunities, signals, contacts, companies, opportunityContacts, contactEvidence, runs, sources, positions, education, works, problems, themes, jtbd, claims, notes, history, conflicts, researchRuns, targetedJobs, agentJobs, agentSubmissions]) if (result.error) throw result.error
  const intelTables = {sources: sources.data ?? [], positions: positions.data ?? [], education: education.data ?? [], works: works.data ?? [], problems: problems.data ?? [], themes: themes.data ?? [], jtbd: jtbd.data ?? [], claims: claims.data ?? [], notes: notes.data ?? [], history: history.data ?? [], conflicts: conflicts.data ?? [], researchRuns: researchRuns.data ?? []}
  const contactEvidenceById = new Map<string, any[]>()
  ;(contactEvidence.data ?? []).forEach((e: any) => { const items = contactEvidenceById.get(e.contact_id) ?? []; if (!items.some((x: any) => x.source_url === e.source_url && x.evidence_type === e.evidence_type)) items.push(e); contactEvidenceById.set(e.contact_id, items) })
  const linksByOpportunity = new Map<string, any[]>()
  ;(opportunityContacts.data ?? []).forEach((link: any) => { const list = linksByOpportunity.get(link.opportunity_id) ?? []; list.push(link); linksByOpportunity.set(link.opportunity_id, list) })
  const contactByCompany = new Map<string, any[]>()
  const companyNames = new Map<string, string>()
  ;(companies.data ?? []).forEach((company: any) => { if (company.id) companyNames.set(company.id, company.legal_name || company.normalized_name || 'Unknown company') })
  ;(contacts.data ?? []).forEach((c: any) => {
    const list = contactByCompany.get(c.company_id) ?? []
    const evidence = contactEvidenceById.get(c.id) ?? []
    const metadata = evidence.map((e: any) => e.metadata_json || {}).reduce((acc: any, item: any) => ({ ...acc, ...item }), {})
    list.push({ id: c.id, company_id: c.company_id, display_name: c.display_name, name: c.display_name, title: c.title, function: c.department, profile_url: c.profile_url, email: c.primary_email, email_status: c.email_status, mailbox_verified: c.email_status === 'VERIFIED_PUBLIC', phone: c.primary_phone, phone_status: c.phone_status, role_fit_score: c.role_fit_score, confidence: Number(c.contact_confidence ?? 0), contact_confidence: c.contact_confidence, identity_confidence: c.contact_confidence, technical_relevance: c.technical_relevance, quality: c.quality_diagnostics?.score ?? null, quality_diagnostics: c.quality_diagnostics, current_role_confidence: readCurrentRoleConfidence(c), last_verified_at: c.last_verified_at, current_status: metadata.current_status || (evidence.some((e: any) => ['company_site','company_profile','professional_profile','conference','company_press','company_pdf','association','registry'].includes(e.source_type)) ? 'PROFESSIONAL_PROFILE' : 'UNKNOWN'), evidence_urls: evidence.map((e: any) => e.source_url).filter(Boolean), evidence, professional_themes: metadata.professional_themes || [], jtbd: metadata.jtbd || metadata.inferred_jtbd || [], why: metadata.why || metadata.observed_context, recommended_channel: metadata.recommended_channel, intelligence: normalizeContactIntelligence(c.id, intelTables) })
    contactByCompany.set(c.company_id, list)
  })
  const signalByPair = new Map<string, any[]>()
  ;(signals.data ?? []).forEach((s: any) => { const key = `${s.company_id}:${s.molecule_id}`; const list = signalByPair.get(key) ?? []; list.push(s); signalByPair.set(key, list) })
  const leads = (opportunities.data ?? []).map((o: any) => {
    const company = o.companies ?? {}; const molecule = o.molecules ?? {}; const pair = signalByPair.get(`${o.company_id}:${o.molecule_id}`) ?? []
    const links = [...(linksByOpportunity.get(o.id) ?? [])].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
    const linkedIds = new Set(links.map((link: any) => link.contact_id))
    const companyContacts = [...(contactByCompany.get(o.company_id) ?? [])]
    const primaryContacts = rankContactsForOpportunity(companyContacts.filter((contact: any) => linkedIds.has(contact.id)))
    const otherCompanyContacts = rankContactsForOpportunity(companyContacts.filter((contact: any) => !linkedIds.has(contact.id)))
    const intelligence = primaryContacts.reduce((acc: any, contact: any) => {
      const intel = contact.intelligence || {}
      ;(['observed', 'inferred', 'unknown'] as const).forEach(key => { acc[key].push(...(intel.claims || []).filter((claim: any) => key === 'observed' ? claim.provenance === 'OBSERVED' : key === 'inferred' ? claim.provenance === 'INFERRED' : claim.provenance === 'UNKNOWN').map((claim: any) => claim.claim_text || claim.statement || claim.basis).filter(Boolean)) })
      acc.observed.push(...(intel.works || []).filter((work: any) => work.attribution === 'PERSON_DIRECT').map((work: any) => `Person-direct work: ${work.title}`).filter(Boolean))
      acc.inferred.push(...(intel.themes || []).map((theme: any) => `Professional theme: ${theme.theme}`).filter(Boolean), ...(intel.jtbd || []).map((job: any) => `Likely JTBD: ${job.statement}`).filter(Boolean))
      return acc
    }, { observed: [], inferred: [], unknown: [] })
    const groupedEvidence = groupEvidenceBySource(pair.map((s: any) => ({ title: `${s.signal_type} evidence`, url: s.source_url, source: s.source_type, date: s.event_date, technical_context: s.evidence_text, signal_types: [s.signal_type], source_record_id: s.source_record_id })))
    const sections = (moleculeSections.data || []).filter((section: any) => section.molecule_id === o.molecule_id)
    return { id: o.id, account: { company: company.legal_name || company.normalized_name, company_id: o.company_id, domain: company.domain, country: company.country, buyer_type: company.company_type || 'pharmaceutical manufacturer/developer' }, opportunity: { molecule: molecule.canonical_name, molecule_id: o.molecule_id, company_id: o.company_id, regulatory_application: pair.find((s: any) => s.source_record_id)?.source_record_id, score: o.score, priority: o.priority, technical_relevance: o.rationale, urgency_bonus: 0 }, evidence: groupedEvidence, moleculeIntelligence: sections, contacts: primaryContacts, other_company_contacts: otherCompanyContacts, person_intelligence: { observed: Array.from(new Set(intelligence.observed)), inferred: Array.from(new Set(intelligence.inferred)), unknown: intelligence.unknown.length ? Array.from(new Set(intelligence.unknown)) : (primaryContacts.length ? [] : ['No validated person intelligence is available for this opportunity yet.']) }, outreach: { personalization_hook: o.rationale, discovery_question: 'Are there current or upcoming analytical requirements where an external partner could help?' } }
  })
  const latestRun = runs.data?.[0]
  const canonicalContacts = buildCanonicalContacts(Array.from(contactByCompany.values()).flat(), opportunityContacts.data ?? [], sources.data ?? [], companyNames)
  const latestTargeted = targetedJobs.data?.[0]
  const workExport = summarizeWorkState(agentJobs.data ?? [], agentSubmissions.data ?? [])
  const workIngestion = summarizeWorkState(agentJobs.data ?? [], agentSubmissions.data ?? [])
  const moleculeIntelligence = Object.fromEntries((moleculeSections.data || []).reduce((map: Map<string, any[]>, section: any) => { const rows = map.get(section.molecule_id) || []; rows.push(section); map.set(section.molecule_id, rows); return map }, new Map<string, any[]>()))
  const moleculeEntityIds = new Map<string, string>()
  ;(researchEntities.data || []).filter((entity: any) => entity.entity_type === 'MOLECULE').forEach((entity: any) => { const moleculeId = entity.metadata_json?.molecule_id; if (moleculeId) moleculeEntityIds.set(entity.id, moleculeId) })
  const moleculeClaims = Object.fromEntries((researchClaims.data || []).reduce((map: Map<string, any[]>, claim: any) => { const moleculeId = moleculeEntityIds.get(claim.entity_id); if (!moleculeId) return map; const rows = map.get(moleculeId) || []; rows.push(claim); map.set(moleculeId, rows); return map }, new Map<string, any[]>()))
  return { leads, canonicalContacts, moleculeIntelligence, moleculeClaims, researchClaims: researchClaims.data || [], candidates: [], pipeline: { crawler: latestRun || null, contactResearch: researchRuns.data?.[0] || null, targetedResearch: latestTargeted || null, workExport, workIngestion }, metrics: { qualified_ge_50: leads.length, hot: leads.filter((x: any) => x.opportunity.priority === 'HOT').length, high: leads.filter((x: any) => x.opportunity.priority === 'HIGH').length, review: leads.filter((x: any) => x.opportunity.priority === 'REVIEW').length, crawler: latestRun, canonical_contacts: canonicalContacts.length, opportunity_contact_links: opportunityContacts.data?.length ?? 0 } }
}
