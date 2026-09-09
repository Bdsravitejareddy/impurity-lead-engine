export type SourceState = 'DISCOVERED'|'QUEUED'|'FETCHING'|'INSPECTED'|'USED'|'REJECTED'|'BLOCKED_AUTH'|'FAILED'|'PENDING_REVIEW'
export type ContactSource = { id?: string; url: string; title?: string; publisher?: string; source_type: string; source_date?: string | null; accessed_at?: string; status: SourceState; evidence_strength?: string; why_used?: string; why_not_used?: string; rejection_reason?: string; raw_content?: string; extraction_json?: any; claims?: string[] }
export type ContactIntelligence = { sources: ContactSource[]; positions: any[]; education: any[]; works: any[]; problems: any[]; themes: any[]; jtbd: any[]; claims: any[]; notes: any[]; history: any[]; conflicts: any[]; researchRuns: any[] }
export const emptyIntelligence = (): ContactIntelligence => ({sources:[],positions:[],education:[],works:[],problems:[],themes:[],jtbd:[],claims:[],notes:[],history:[],conflicts:[],researchRuns:[]})
export function dedupeSources(rows: any[] = []): ContactSource[] { const seen = new Map<string, any>(); for (const row of rows) { const key = String(row.url || '').trim().toLowerCase(); if (key && !seen.has(key)) seen.set(key, row) } return [...seen.values()] }
export function normalizeContactIntelligence(contactId: string, tables: Record<string, any[]>): ContactIntelligence { return { sources: dedupeSources(tables.sources?.filter(x => x.contact_id === contactId) ?? []), positions: tables.positions?.filter(x => x.contact_id === contactId) ?? [], education: tables.education?.filter(x => x.contact_id === contactId) ?? [], works: tables.works?.filter(x => x.contact_id === contactId) ?? [], problems: tables.problems?.filter(x => x.contact_id === contactId) ?? [], themes: tables.themes?.filter(x => x.contact_id === contactId) ?? [], jtbd: tables.jtbd?.filter(x => x.contact_id === contactId) ?? [], claims: tables.claims?.filter(x => x.contact_id === contactId) ?? [], notes: tables.notes?.filter(x => x.contact_id === contactId) ?? [], history: tables.history?.filter(x => x.contact_id === contactId) ?? [], conflicts: tables.conflicts?.filter(x => x.contact_id === contactId) ?? [], researchRuns: tables.researchRuns?.filter(x => x.contact_id === contactId) ?? [] } }
export function sourceCoverage(sources: ContactSource[]) { const classes = new Set(sources.map(s => s.source_type)); return { inspected: sources.length, used: sources.filter(s => s.status === 'USED').length, rejected: sources.filter(s => s.status === 'REJECTED').length, blocked: sources.filter(s => s.status === 'BLOCKED_AUTH').length, pending: sources.filter(s => s.status === 'PENDING_REVIEW').length, classes: classes.size, byType: [...classes].map(type => ({type, inspected: sources.filter(s => s.source_type === type).length, used: sources.filter(s => s.source_type === type && s.status === 'USED').length, rejected: sources.filter(s => s.source_type === type && s.status === 'REJECTED').length})) } }
export type ProfilePosition = {title:string; company_name?:string; department?:string; start_date?:string; end_date?:string; location?:string; description?:string; employment_type?:string; attribution:'PERSON_DIRECT'; confidence:number; review_suggested?:boolean}
export type ProfileEducation = {institution:string; degree?:string; field?:string; start_date?:string; end_date?:string; description?:string; confidence:number; review_suggested?:boolean}
export type ProfileWork = {title:string; work_type:string; work_date?:string; topic?:string; url?:string; authors?:string; publisher?:string; description?:string; attribution:'PERSON_DIRECT'; confidence:number; review_suggested?:boolean}
export type PdfTextExtraction = { text: string; pages: number; warnings: string[] }
export type ProfileExtraction = { claims: string[]; currentTitle?: string; headline?: string; currentCompany?: string; location?: string; about?: string; skills?: string[]; certifications?: {name:string; issuer?:string; issue_date?:string; expiry_date?:string; credential_url?:string; confidence:number; review_suggested?:boolean}[]; activities?: ProfileWork[]; positions: ProfilePosition[]; education: ProfileEducation[]; themes: string[]; keywords: string[]; works: ProfileWork[]; warnings?: string[]; pages?: number }

const sectionAliases: Record<string, string> = {
  'about':'ABOUT','experience':'EXPERIENCE','work experience':'EXPERIENCE','education':'EDUCATION',
  'licenses & certifications':'CERTIFICATIONS','licenses and certifications':'CERTIFICATIONS','certifications':'CERTIFICATIONS',
  'projects':'PROJECTS','publications':'PUBLICATIONS','patents':'PATENTS','skills':'SKILLS','activity':'ACTIVITY',
  'recommendations':'RECOMMENDATIONS','honors & awards':'OTHER','honours & awards':'OTHER','volunteer experience':'OTHER',
  'languages':'OTHER','interests':'OTHER'
}
const profileHeadings = Object.keys(sectionAliases)
const uiNoise = /^(home|my network|messaging|notifications|jobs|contact info|see more|show all|linkedin|follow|connect|send message|subscribe|followers?|connections?|people also viewed|interests?)$/i
const dateRange = /^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+)?(?:19|20)\d{2}\s*(?:[-–—]|to)\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+)?(?:(?:19|20)\d{2}|present|current)(?:\s*:\s*.*)?$/i
const durationLine = /^\d+\s+(?:yr|yrs|year|years|mo|mos|month|months)/i
const cleanLine = (line: string) => line.replace(/\u00a0/g, ' ').replace(/[\t ]+/g, ' ').trim()
const usefulLines = (text: string) => text.split(/\r?\n/).map(cleanLine).filter(Boolean)
const canonicalHeading = (line: string) => sectionAliases[line.toLowerCase().replace(/\s+/g, ' ').trim()]

function splitProfileSections(text: string): { sections: Record<string,string[]>; preamble: string[] } {
  const sections: Record<string,string[]> = { PROFILE: [] }; let current = 'PROFILE'
  for (const original of usefulLines(text)) {
    const line = original.replace(/^[•·▪]\s*/, '').trim(); const heading = canonicalHeading(line)
    if (heading) { current = heading; if (!sections[current]) sections[current] = []; continue }
    if (uiNoise.test(line)) continue
    sections[current].push(line)
  }
  return { sections, preamble: sections.PROFILE || [] }
}

export function isSuspiciousExtractedField(value: string): boolean {
  const text = value.trim();
  const letters = (text.match(/[A-Za-z]/g) || []).length;
  const symbols = (text.match(/[^\p{L}\p{N}\s.,&()'\-/]/gu) || []).length;
  const words = text.split(/\s+/).filter(Boolean)
  return letters < 4 || (symbols >= 4 && symbols / Math.max(1, text.length) > 0.12) || /(?:>>|<<|\$\s*\/|\/\s*[>$])/.test(text) || /(?:\b(?:ucs|pdf|obj|endobj|stream|xref)\b)/i.test(text) && symbols > 1 || words.length > 1 && words.every(word => /^[^A-Za-z]*$/.test(word))
}

function confidenceFor(value: string, explicit = true) { return isSuspiciousExtractedField(value) ? 0.25 : explicit ? 0.95 : 0.75 }
function parseDateRange(value: string): { start_date?: string; end_date?: string } { const match = value.match(/((?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+)?(?:19|20)\d{2})\s*(?:[-–—]|to)\s*((?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+)?(?:19|20)\d{2}|present|current)/i); return match ? {start_date: match[1], end_date: /^present|current$/i.test(match[2]) ? '' : match[2]} : {} }
function isDateLine(line: string) { return dateRange.test(line) }
function isLikelyCompany(line: string) { return /\b(pharma(?:ceuticals?)?|laborator(?:y|ies)|therapeutics?|biotech|inc\.?|ltd\.?|limited|corporation|corp\.?|holdings?|university|institute|hospital|group|cipla|takeda|novartis|bayer|lupin)\b/i.test(line) }
function isLikelyDegree(line: string) { return /\b(?:M\.?\s*(?:Sc|Pharm|Tech|Eng|BA|BS|MBA)|B\.?\s*(?:Pharm|Tech|Sc|Eng|BA|BS)|Ph\.?\s*D|Bachelor|Master|Doctor|Diploma|Certificate|Post[- ]?graduate|Fellowship)\b/i.test(line) }
function sectionLines(sections: Record<string,string[]>, key: string) { return (sections[key] || []).filter(line => !uiNoise.test(line) && line.length > 1) }

function parseExperience(lines: string[]): ProfilePosition[] {
  const positions: ProfilePosition[] = []; let lastDateIndex = -1; let currentCompany = ''
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]; if (!isDateLine(line)) continue
    const range = parseDateRange(line); const trailing = line.match(/:\s*(.+)$/)?.[1]?.trim() || ''; const before = lines.slice(lastDateIndex + 1, i).filter(x => !durationLine.test(x) && !isDateLine(x))
    const inline = before.find(x => /\s+at\s+/i.test(x)); let title = ''; let company = currentCompany; let location = ''
    if (trailing) { const atMatch = trailing.match(/^(.+?)\s+at\s+(.+)$/i); title = (atMatch ? atMatch[1] : trailing).trim(); company = (atMatch ? atMatch[2] : '').trim(); const priorCompany = before.find(isLikelyCompany); if (priorCompany) company = priorCompany }
    else if (inline) { const parts = inline.split(/\s+at\s+/i); title = parts[0].trim(); company = parts.slice(1).join(' at ').trim() }
    else {
      const candidates = before.filter(x => !/^\d+\s+(?:followers?|connections?)/i.test(x) && !/\b(?:india|japan|tokyo|mumbai|london|new york|singapore|usa|uk)\b/i.test(x))
      const companyIndex = candidates.findIndex(isLikelyCompany)
      if (companyIndex >= 0) { company = candidates[companyIndex]; title = candidates[companyIndex + 1] || candidates[companyIndex - 1] || '' }
      else if (candidates.length >= 2) { title = candidates[candidates.length - 1]; company = currentCompany || candidates[candidates.length - 2] }
      else if (candidates.length === 1) title = candidates[0]
      if (title && /,\s*(?:[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)*)$/.test(title)) { const parts = title.split(','); location = parts.pop()!.trim(); title = parts.join(',').trim() }
    }
    if (!title || title.length > 160 || uiNoise.test(title)) { lastDateIndex = i; continue }
    if (!company && i > 0) company = lines.slice(0, i).reverse().find(x => isLikelyCompany(x)) || ''
    if (company) currentCompany = company
    const after = lines.slice(i + 1, lines.findIndex((x,j) => j > i && isDateLine(x)) < 0 ? lines.length : lines.findIndex((x,j) => j > i && isDateLine(x))).filter(x => !durationLine.test(x))
    const description = after.filter(x => x.length > 35 && !/^(?:present|current)$/i.test(x)).slice(0, 3).join(' ')
    const confidence = confidenceFor(title, true)
    positions.push({title, company_name: company || undefined, ...range, location: location || undefined, description: description || undefined, attribution:'PERSON_DIRECT', confidence})
    lastDateIndex = i
  }
  return positions.slice(0, 30)
}

function parseEducation(lines: string[]): ProfileEducation[] {
  const records: ProfileEducation[] = []; let pending: Partial<ProfileEducation> = {}
  const flush = () => { if (!pending.institution && !pending.degree) return; const institution = String(pending.institution || 'Institution not specified').trim(); const degree = pending.degree?.trim(); const value = degree || institution; const review_suggested = isSuspiciousExtractedField(value) || isSuspiciousExtractedField(institution); records.push({institution, degree, field: pending.field, start_date: pending.start_date, end_date: pending.end_date, description: pending.description, confidence: review_suggested ? 0.25 : Number(pending.confidence || 0.85), review_suggested}); pending = {} }
  for (const line of lines) {
    if (isDateLine(line)) { Object.assign(pending, parseDateRange(line)); continue }
    const direct = line.match(/^(.+?)\s+(?:from|at)\s+(.+)$/i)
    if (direct && isLikelyDegree(direct[1])) { flush(); pending = {degree: direct[1].trim(), institution: direct[2].trim(), confidence: 0.9}; continue }
    if (isLikelyDegree(line)) { if (pending.degree) flush(); pending.degree = line; pending.confidence = 0.9; continue }
    if (!pending.institution && /\b(?:university|college|institute|school|academy)\b/i.test(line)) { pending.institution = line; continue }
    if (pending.degree && !pending.field && line.length < 100 && !/^(?:activities|description|coursework)$/i.test(line)) { pending.field = line; continue }
    if (pending.institution && line.length > 20) pending.description = [pending.description, line].filter(Boolean).join(' ')
  }
  flush(); return records.filter(x => x.institution !== 'Institution not specified' || x.degree).slice(0, 20)
}

function parseWorkSection(lines: string[], type: string): ProfileWork[] { return lines.filter(x => x.length > 2 && !uiNoise.test(x)).slice(0, 30).map(title => ({title, work_type:type, attribution:'PERSON_DIRECT', confidence: confidenceFor(title, false)})) }

export function extractProfessionalProfile(text: string, name = ''): ProfileExtraction {
  const {sections, preamble} = splitProfileSections(text); const warnings: string[] = []
  const identityLines = preamble.filter(x => x.length > 1 && !/^\d+\s+(?:followers?|connections?)/i.test(x))
  const suppliedName = name || identityLines[0] || ''
  const headline = identityLines.find(x => x !== suppliedName && x.length < 180 && !isLikelyCompany(x) && !/https?:\/\//i.test(x))
  const location = identityLines.find(x => /\b(india|japan|usa|united states|uk|united kingdom|mumbai|tokyo|london|new york|singapore|canada|germany|switzerland)\b/i.test(x) && x !== headline)
  const fallbackLines = usefulLines(text)
  const positions = parseExperience(sectionLines(sections, 'EXPERIENCE').length ? sectionLines(sections, 'EXPERIENCE') : fallbackLines)
  const current = positions.find(x => x.end_date === '') || positions[0]
  const currentTitle = current?.title || (headline && /\b(head|director|vice president|vp|chief|manager|scientist|quality|analytical|cmc|r&d|development)\b/i.test(headline) ? headline : undefined)
  const currentCompany = current?.company_name
  const about = sectionLines(sections, 'ABOUT').join(' ').trim() || undefined
  const education = parseEducation(sectionLines(sections, 'EDUCATION').length ? sectionLines(sections, 'EDUCATION') : fallbackLines)
  const certifications = sectionLines(sections, 'CERTIFICATIONS').map(name => ({name, confidence: confidenceFor(name, true), review_suggested: isSuspiciousExtractedField(name)})).filter(x => x.name.length > 2).slice(0, 30)
  const projects = parseWorkSection(sectionLines(sections, 'PROJECTS'), 'PROJECT')
  const publications = parseWorkSection(sectionLines(sections, 'PUBLICATIONS'), 'PUBLICATION')
  const patents = parseWorkSection(sectionLines(sections, 'PATENTS'), 'PATENT')
  const activities = parseWorkSection(sectionLines(sections, 'ACTIVITY'), 'PROFESSIONAL_ACTIVITY')
  const works = [...projects, ...publications, ...patents, ...activities]
  const skills = sectionLines(sections, 'SKILLS').flatMap(x => x.split(/,|•|;/).map(y => y.trim())).filter(x => x.length > 1 && x.length < 100).slice(0, 60)
  const profileClaims = [headline && `Professional headline: ${headline}`, currentTitle && `Current title: ${currentTitle}`, currentCompany && `Current company: ${currentCompany}`, location && `Professional location: ${location}`, about && `Professional summary: ${about.slice(0, 600)}`, skills.length && `Explicit professional skills: ${skills.join(', ')}`, certifications.length && `Certifications supplied: ${certifications.map(c => c.name).join(', ')}`].filter(Boolean) as string[]
  const themes = ['analytical development','analytical','quality','quality control','quality assurance','CMC','stability','degradation','impurity','regulatory','process development','API','method validation','nitrosamine','respiratory','data integrity'].filter(t => text.toLowerCase().includes(t.toLowerCase()))
  const keywords = [...new Set([suppliedName, currentCompany, currentTitle, location, ...themes, ...skills.slice(0, 10)].filter(Boolean).flatMap(x => String(x).split(/\s+/).filter(w => w.length > 3)))].slice(0, 80)
  if (!text.trim()) warnings.push('No machine-readable profile text was found.')
  if (!positions.length) warnings.push('No dated experience positions were detected.')
  if (education.some(x => x.review_suggested)) warnings.push('One or more education fields need review.')
  return {claims: profileClaims, currentTitle, headline, currentCompany, location, about, skills, certifications, activities, positions, education, themes, keywords, works, warnings}
}

export function researchQueries(profile: ProfileExtraction, name: string): string[] {
  const base = [name, profile.currentCompany].filter(Boolean).join(' ')
  const terms = ['publication','patent','conference','webinar','analytical','quality','CMC','impurity','degradation','stability','method validation']
  return [...new Set(terms.map(term => `${base} ${term}`)), ...profile.positions.slice(1, 4).flatMap(position => terms.slice(0, 4).map(term => `${name} ${position.company_name || ''} ${term}`))].filter(query => query.trim().split(/\s+/).length >= 2).slice(0, 20)
}

export async function extractPdfText(buffer: ArrayBuffer): Promise<PdfTextExtraction> {
  const warnings: string[] = []
  try {
    const pdfjs: any = await import('pdfjs-dist/legacy/build/pdf.mjs')
    const document = await pdfjs.getDocument({data: new Uint8Array(buffer), disableWorker: true}).promise
    const pages: string[] = []
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber++) {
      const page = await document.getPage(pageNumber); const content = await page.getTextContent();
      const items = (content.items || []).filter((item: any) => typeof item.str === 'string')
      const lines: string[] = []; let lastY: number | null = null; let current = ''
      for (const item of items) { const y = Array.isArray(item.transform) ? item.transform[5] : null; if (lastY !== null && y !== null && Math.abs(y - lastY) > 2) { if (current.trim()) lines.push(current.trim()); current = '' } current += (current ? ' ' : '') + item.str; if (y !== null) lastY = y }
      if (current.trim()) lines.push(current.trim()); pages.push(lines.join('\n'))
    }
    const text = pages.join('\n\n').replace(/[ \t]+\n/g, '\n').trim()
    if (text.length < 40) warnings.push('Very little machine-readable text was found. Try Paste LinkedIn Text.')
    return {text, pages: document.numPages, warnings}
  } catch (error) {
    warnings.push('The PDF could not be read as machine-readable text. Try Paste LinkedIn Text.')
    return {text: '', pages: 0, warnings}
  }
}
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
