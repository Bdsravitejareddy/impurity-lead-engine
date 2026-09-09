export type SourceState = 'DISCOVERED'|'QUEUED'|'FETCHING'|'INSPECTED'|'USED'|'REJECTED'|'BLOCKED_AUTH'|'FAILED'|'PENDING_REVIEW'
export type ContactSource = { id?: string; url: string; title?: string; publisher?: string; source_type: string; source_date?: string | null; accessed_at?: string; status: SourceState; evidence_strength?: string; why_used?: string; why_not_used?: string; rejection_reason?: string; raw_content?: string; extraction_json?: any; claims?: string[] }
export type ContactIntelligence = { sources: ContactSource[]; positions: any[]; education: any[]; works: any[]; problems: any[]; themes: any[]; jtbd: any[]; claims: any[]; notes: any[]; history: any[]; conflicts: any[]; researchRuns: any[] }
export const emptyIntelligence = (): ContactIntelligence => ({sources:[],positions:[],education:[],works:[],problems:[],themes:[],jtbd:[],claims:[],notes:[],history:[],conflicts:[],researchRuns:[]})
export function dedupeSources(rows: any[] = []): ContactSource[] { const seen = new Map<string, any>(); for (const row of rows) { const key = String(row.url || '').trim().toLowerCase(); if (key && !seen.has(key)) seen.set(key, row) } return [...seen.values()] }
export function normalizeContactIntelligence(contactId: string, tables: Record<string, any[]>): ContactIntelligence { return { sources: dedupeSources(tables.sources?.filter(x => x.contact_id === contactId) ?? []), positions: tables.positions?.filter(x => x.contact_id === contactId) ?? [], education: tables.education?.filter(x => x.contact_id === contactId) ?? [], works: tables.works?.filter(x => x.contact_id === contactId) ?? [], problems: tables.problems?.filter(x => x.contact_id === contactId) ?? [], themes: tables.themes?.filter(x => x.contact_id === contactId) ?? [], jtbd: tables.jtbd?.filter(x => x.contact_id === contactId) ?? [], claims: tables.claims?.filter(x => x.contact_id === contactId) ?? [], notes: tables.notes?.filter(x => x.contact_id === contactId) ?? [], history: tables.history?.filter(x => x.contact_id === contactId) ?? [], conflicts: tables.conflicts?.filter(x => x.contact_id === contactId) ?? [], researchRuns: tables.researchRuns?.filter(x => x.contact_id === contactId) ?? [] } }
export function sourceCoverage(sources: ContactSource[]) { const classes = new Set(sources.map(s => s.source_type)); return { inspected: sources.length, used: sources.filter(s => s.status === 'USED').length, rejected: sources.filter(s => s.status === 'REJECTED').length, blocked: sources.filter(s => s.status === 'BLOCKED_AUTH').length, pending: sources.filter(s => s.status === 'PENDING_REVIEW').length, classes: classes.size, byType: [...classes].map(type => ({type, inspected: sources.filter(s => s.source_type === type).length, used: sources.filter(s => s.source_type === type && s.status === 'USED').length, rejected: sources.filter(s => s.source_type === type && s.status === 'REJECTED').length})) } }
export type ProfilePosition = {title:string; company_name?:string; department?:string; start_date?:string; end_date?:string; attribution:'PERSON_DIRECT'; confidence:number}
export type ProfileEducation = {institution:string; degree?:string; field?:string; start_date?:string; end_date?:string; confidence:number}
export type ProfileWork = {title:string; work_type:string; work_date?:string; topic?:string; url?:string; attribution:'PERSON_DIRECT'; confidence:number}
export type ProfileExtraction = { claims: string[]; currentTitle?: string; headline?: string; currentCompany?: string; location?: string; about?: string; skills?: string[]; certifications?: {name:string; issuer?:string; issue_date?:string; expiry_date?:string; credential_url?:string; confidence:number}[]; activities?: ProfileWork[]; positions: ProfilePosition[]; education: ProfileEducation[]; themes: string[]; keywords: string[]; works: ProfileWork[] }
const profileHeadings = ['About','Experience','Education','Licenses & certifications','Certifications','Projects','Publications','Skills','Activity','Recommendations']
function profileSection(text: string, heading: string): string {
  const lines = text.split(/\r?\n/).map(x => x.trim()); const headingLower = heading.toLowerCase(); const start = lines.findIndex(x => x.toLowerCase() === headingLower); if (start < 0) return ''
  const end = lines.findIndex((x, i) => i > start && profileHeadings.some(h => h.toLowerCase() === x.toLowerCase())); return lines.slice(start + 1, end < 0 ? lines.length : end).filter(Boolean).join('\n').trim()
}
export function extractProfessionalProfile(text: string, name = ''): ProfileExtraction {
  const clean = text.replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' ').trim(); const lines = text.split(/\r?\n/).map(x => x.trim()).filter(Boolean).filter(x => !/^(home|about|experience|education|skills|interests|contact info|see more|show all|linkedin)$/i.test(x))
  const currentTitle = lines.find(x => /\b(head|director|vice president|vp|chief|manager|scientist|quality|analytical|cmc|r&d|development)\b/i.test(x) && x.length < 180)
  const currentCompany = lines.find(x => /\b(pharma|pharmaceutical|laboratories|laboratory|therapeutics|biotech|cipla|takeda|novartis|bayer|lupin)\b/i.test(x) && x.length < 140)
  const location = lines.find(x => /\b(india|japan|usa|united states|uk|united kingdom|mumbai|tokyo|london|new york|singapore)\b/i.test(x) && x.length < 120)
  const positions: ProfilePosition[] = [...clean.matchAll(/((?:19|20)\d{2})\s*(?:-|–|to)\s*(Present|(?:19|20)\d{2})\s*[:|,-]?\s*([^;|.\n]{3,100}?)(?:\s+at\s+|,\s+)([^;|.\n]{2,100})/gi)].slice(0, 12).map(m => ({start_date:m[1], end_date:/present/i.test(m[2])?'':m[2], title:m[3].trim(), company_name:m[4].trim(), attribution:'PERSON_DIRECT', confidence:0.85}))
  if (currentTitle && currentCompany && !positions.some(p => p.title === currentTitle)) positions.unshift({title:currentTitle, company_name:currentCompany, attribution:'PERSON_DIRECT', confidence:0.82})
  const education: ProfileEducation[] = [...clean.matchAll(/(?:M\.?(?:Sc|Pharm|Tech|BA|BS|MBA)|B\.?(?:Pharm|Tech|Sc|E)|Ph\.?D|Post Graduate|Bachelor|Master)[^.;|\n]{0,120}/gi)].slice(0, 8).map(m => ({institution:(m[0].match(/(?:at|from)\s+([^,.;|]+)/i)?.[1] || 'Institution not specified').trim(), degree:m[0].trim(), confidence:0.75}))
  const certSection = profileSection(text, 'Licenses & certifications') || profileSection(text, 'Certifications'); const certifications = certSection.split(/\n|;|•/).map(x=>x.trim()).filter(x=>x.length>2).slice(0,20).map(name=>({name,confidence:0.7}))
  const projectSection = profileSection(text, 'Projects'); const projectWorks: ProfileWork[] = projectSection.split(/\n|•/).map(x=>x.trim()).filter(x=>x.length>3).slice(0,12).map(title=>({title,work_type:'PROJECT',attribution:'PERSON_DIRECT',confidence:0.7}))
  const activitySection = profileSection(text, 'Activity'); const activities: ProfileWork[] = activitySection.split(/\n/).map(title=>title.trim()).filter(x=>x.length>20).slice(0,12).map(title=>({title,work_type:'PROFESSIONAL_ACTIVITY',attribution:'PERSON_DIRECT',confidence:0.65}))
  const themeTerms = ['analytical development','analytical','quality','quality control','quality assurance','CMC','stability','degradation','impurity','regulatory','process development','API','method validation','nitrosamine']; const themes = themeTerms.filter(t => clean.toLowerCase().includes(t.toLowerCase()))
  const keywords = [...new Set([name, currentCompany, currentTitle, location, ...themes].filter(Boolean).flatMap(x => String(x).split(/\s+/).filter(w => w.length > 3)))].slice(0, 50)
  const works: ProfileWork[] = [...projectWorks, ...lines.filter(x => /\b(publication|patent|conference|webinar|project|presentation|poster|study|method|validation)\b/i.test(x)).slice(0, 12).map(title => ({title, work_type:/patent/i.test(title)?'PATENT':/publication|study|method/i.test(title)?'PUBLICATION':'PROFESSIONAL_ACTIVITY', attribution:'PERSON_DIRECT', confidence:0.7}))]
  const about = profileSection(text, 'About'); const skillsSection = profileSection(text, 'Skills'); const skills = skillsSection.split(/,|\n|•/).map(x=>x.trim()).filter(x=>x.length>1 && x.length<80).slice(0,40)
  const claims = [currentTitle && `Current title: ${currentTitle}`, currentCompany && `Current employer context: ${currentCompany}`, location && `Professional location: ${location}`, about && `Professional summary: ${about.slice(0,400)}`, skills.length && `Explicit professional skills: ${skills.join(', ')}`, certifications.length && `Certifications supplied: ${certifications.map(c=>c.name).join(', ')}`].filter(Boolean) as string[]
  return {claims, currentTitle, headline:currentTitle, currentCompany, location, about, skills, certifications, activities, positions, education, themes, keywords, works}
}
export function researchQueries(profile: ProfileExtraction, name: string): string[] { const base = [name, profile.currentCompany].filter(Boolean).join(' '); const terms = ['publication','patent','conference','webinar','analytical','quality','CMC','impurity','degradation','stability','method validation']; return [...new Set(terms.map(t => `${base} ${t}`)), ...profile.positions.slice(1,4).flatMap(p => terms.slice(0,4).map(t => `${name} ${p.company_name || ''} ${t}`))].filter(q => q.trim().split(/\s+/).length >= 2).slice(0, 20) }
export function extractPdfText(buffer: ArrayBuffer): string { const raw = new TextDecoder('latin1').decode(buffer); return [...raw.matchAll(/\(([^()]{3,200})\)/g)].map(m => m[1].replace(/\\[nrt]/g, ' ')).join('\n').replace(/[^\x09\x0A\x0D\x20-\x7E]/g, ' ').replace(/\s+/g, ' ').trim() }
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
