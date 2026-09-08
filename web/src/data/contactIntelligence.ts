export type ContactSource = { id?: string; url: string; title?: string; publisher?: string; source_type: string; source_date?: string | null; accessed_at?: string; status: 'USED'|'INSPECTED'|'REJECTED'; evidence_strength?: string; why_used?: string; why_not_used?: string; claims?: string[] }
export type ContactIntelligence = { sources: ContactSource[]; positions: any[]; education: any[]; works: any[]; problems: any[]; themes: any[]; jtbd: any[]; claims: any[]; notes: any[]; history: any[]; conflicts: any[]; researchRuns: any[] }
export const emptyIntelligence = (): ContactIntelligence => ({sources:[],positions:[],education:[],works:[],problems:[],themes:[],jtbd:[],claims:[],notes:[],history:[],conflicts:[],researchRuns:[]})
export function dedupeSources(rows: any[] = []): ContactSource[] { const seen = new Map<string, any>(); for (const row of rows) { const key = String(row.url || '').trim().toLowerCase(); if (key && !seen.has(key)) seen.set(key, row) } return [...seen.values()] }
export function normalizeContactIntelligence(contactId: string, tables: Record<string, any[]>): ContactIntelligence { return { sources: dedupeSources(tables.sources?.filter(x => x.contact_id === contactId) ?? []), positions: tables.positions?.filter(x => x.contact_id === contactId) ?? [], education: tables.education?.filter(x => x.contact_id === contactId) ?? [], works: tables.works?.filter(x => x.contact_id === contactId) ?? [], problems: tables.problems?.filter(x => x.contact_id === contactId) ?? [], themes: tables.themes?.filter(x => x.contact_id === contactId) ?? [], jtbd: tables.jtbd?.filter(x => x.contact_id === contactId) ?? [], claims: tables.claims?.filter(x => x.contact_id === contactId) ?? [], notes: tables.notes?.filter(x => x.contact_id === contactId) ?? [], history: tables.history?.filter(x => x.contact_id === contactId) ?? [], conflicts: tables.conflicts?.filter(x => x.contact_id === contactId) ?? [], researchRuns: tables.researchRuns?.filter(x => x.contact_id === contactId) ?? [] } }
export function sourceCoverage(sources: ContactSource[]) { const classes = new Set(sources.map(s => s.source_type)); return { inspected: sources.length, used: sources.filter(s => s.status === 'USED').length, rejected: sources.filter(s => s.status === 'REJECTED').length, classes: classes.size, byType: [...classes].map(type => ({type, inspected: sources.filter(s => s.source_type === type).length, used: sources.filter(s => s.source_type === type && s.status === 'USED').length, rejected: sources.filter(s => s.source_type === type && s.status === 'REJECTED').length})) } }
export type ResearchState = 'UNRESEARCHED'|'PARTIAL'|'RESEARCHED'|'DEEP PROFILE'
export function researchCompleteness(intel: ContactIntelligence, contact: { profile_url?: string | null; email?: string | null; phone?: string | null; current_status?: string | null }) {
  const used = intel.sources.filter(s => s.status === 'USED').length
  const claims = intel.claims.filter(c => c.provenance === 'OBSERVED').length
  const dimensions = [
    Boolean(contact.profile_url || claims),
    Boolean(claims && intel.positions.length),
    intel.positions.length > 1,
    intel.education.length > 0,
    intel.works.some(w => w.attribution === 'PERSON_DIRECT'),
    intel.works.some(w => w.attribution !== 'PERSON_DIRECT'),
    intel.problems.length > 0,
    intel.themes.length > 0,
    Boolean(intel.researchRuns.some(r => r.status === 'COMPLETED') || intel.sources.some(s => s.source_date)),
    Boolean(contact.email || contact.phone || contact.profile_url),
    intel.jtbd.length > 0,
    new Set(intel.sources.map(s => s.source_type)).size >= 2,
  ]
  const score = Math.round(dimensions.filter(Boolean).length / dimensions.length * 100)
  const state: ResearchState = used === 0 && claims === 0 ? 'UNRESEARCHED' : score >= 75 && dimensions.filter(Boolean).length >= 9 ? 'DEEP PROFILE' : score >= 50 ? 'RESEARCHED' : 'PARTIAL'
  return { score, state, dimensionsCovered: dimensions.filter(Boolean).length, dimensionsTotal: dimensions.length }
}
export function personSummary(intel: ContactIntelligence, contact: { name: string; title?: string | null; function?: string | null }, company: string) {
  const completeness = researchCompleteness(intel, contact)
  if (completeness.state === 'UNRESEARCHED') return 'Not enough verified evidence is available to generate a person-level briefing yet.'
  const observed = intel.claims.filter(c => c.provenance === 'OBSERVED').map(c => c.claim_text).join(' ')
  const roles = intel.positions.map(p => [p.title, p.company_name].filter(Boolean).join(' at ')).join('; ')
  const direct = intel.works.filter(w => w.attribution === 'PERSON_DIRECT').map(w => w.title).join('; ')
  const companyWork = intel.works.filter(w => w.attribution !== 'PERSON_DIRECT').map(w => w.title).join('; ')
  const problems = intel.problems.map(p => p.problem).join('; ')
  const themes = intel.themes.map(t => t.theme).join(', ')
  const jtbd = intel.jtbd.slice(0, 3).map(j => j.statement).join('; ')
  return `${contact.name} is publicly described as ${contact.title || 'a professional contact'} at ${company}${contact.function ? `, working in ${contact.function}` : ''}. ${observed} ${roles ? `The documented career progression includes ${roles}.` : ''} ${intel.education.length ? `Public education records include ${intel.education.map(e => [e.degree, e.institution].filter(Boolean).join(' at ')).join('; ')}.` : ''} ${direct ? `Person-direct professional work includes ${direct}.` : 'No person-specific technical publication, patent or project has been independently verified.'} ${companyWork ? `Relevant organisational context includes ${companyWork}. This establishes the working environment, not personal authorship.` : ''} ${problems ? `Documented or functionally supported problems include ${problems}.` : ''} ${themes ? `Recurring professional themes are ${themes}.` : ''} ${jtbd ? `Likely jobs to be done are inferred as ${jtbd}.` : ''} The account is relevant to SVAK because the role and evidence intersect with analytical quality, impurity control, stability, degradation or reference-standard workflows. This is a sales hypothesis rather than evidence of a current purchase requirement. Current priorities, active projects and supplier preferences remain unknown.`
}
