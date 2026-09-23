export type SourceState = 'DISCOVERED'|'QUEUED'|'FETCHING'|'INSPECTED'|'USED'|'REJECTED'|'BLOCKED_AUTH'|'FAILED'|'PENDING_REVIEW'
export type ContactSource = { id?: string; url: string; title?: string; publisher?: string; source_type: string; source_date?: string | null; accessed_at?: string; status: SourceState; evidence_strength?: string; why_used?: string; why_not_used?: string; rejection_reason?: string; raw_content?: string; extraction_json?: any; claims?: string[] }
export type ContactIntelligence = { sources: ContactSource[]; positions: any[]; education: any[]; works: any[]; problems: any[]; themes: any[]; jtbd: any[]; persona: any[]; claims: any[]; notes: any[]; history: any[]; conflicts: any[]; researchRuns: any[] }
// Bump when extraction or derived profile persistence changes so re-pasting an
// unchanged source still repairs rows written by an older parser.
export const PROFILE_PARSER_VERSION = '5'

const roleJtbdTemplates: Record<string, string[]> = {
  analytical: [
    'Define and maintain analytical methods for identity, purity, impurities and degradation products.',
    'Review laboratory results, investigations and method performance for release or stability decisions.',
    'Coordinate analytical quality priorities with internal laboratories and external technical partners.',
  ],
  quality: [
    'Ensure quality systems and analytical records support compliant product decisions.',
    'Review deviations, CAPA and validation evidence with the responsible technical teams.',
    'Assess external technical work for quality-system and regulatory fit.',
  ],
  cmc: [
    'Develop and transfer robust processes with defined impurity and degradation controls.',
    'Evaluate process data and analytical evidence during scale-up or technical transfer.',
    'Coordinate specialist external support for process, impurity or stability work.',
  ],
  regulatory: [
    'Assemble and maintain technical evidence required for regulatory submissions and responses.',
    'Identify evidence gaps in impurity, stability and analytical documentation.',
    'Coordinate technical contributors so submitted quality information is consistent and traceable.',
  ],
  procurement: [
    'Identify and qualify suppliers for technically critical materials and services.',
    'Compare supplier capability, quality evidence, delivery risk and commercial fit.',
    'Coordinate procurement decisions with analytical, quality and regulatory stakeholders.',
  ],
}

export function inferProfileJtbd(profile: Pick<ProfileExtraction, 'currentTitle' | 'currentCompany' | 'skills' | 'about'>, contactId: string, sourceId: string, existingStatements: string[] = []) {
  const text = [profile.currentTitle, profile.currentCompany, ...(profile.skills || []), profile.about].filter(Boolean).join(' ').toLowerCase()
  const family = text.match(/analytical|method development|hplc|chromatography|laboratory|quality control|quality assurance|gmp|validation|data integrity|cmc|process development|technical operations|regulatory|submission|procurement|sourcing|supplier/)?.[0]
  const key = /analytical|method development|hplc|chromatography|laboratory|quality control/.test(text) ? 'analytical' : /quality assurance|gmp|validation|data integrity/.test(text) ? 'quality' : /cmc|process development|technical operations/.test(text) ? 'cmc' : /regulatory|submission/.test(text) ? 'regulatory' : /procurement|sourcing|supplier/.test(text) ? 'procurement' : null
  if (!key) return []
  const existing = new Set(existingStatements.map(value => value.toLowerCase()))
  return roleJtbdTemplates[key].filter(statement => !existing.has(statement.toLowerCase())).map(statement => ({
    contact_id: contactId,
    statement,
    category: key,
    basis: 'ROLE_ONTOLOGY_V1 + SUPPLIED_PROFILE_CONTEXT',
    evidence: 'Derived from the supplied professional profile; independently verify with person-specific evidence.',
    confidence: family ? 0.68 : 0.58,
    provenance: 'INFERRED',
    svak_mapping: 'Role and profile context indicate a possible technical or quality workflow fit.',
    discovery_question: 'Is this an active responsibility or requirement for your team today?',
    source_ids: [sourceId],
  }))
}
export function inferProfileProblems(profile: Pick<ProfileExtraction, 'currentTitle' | 'currentCompany' | 'skills' | 'about'>, contactId: string, sourceId: string) {
  const text = [profile.currentTitle, profile.currentCompany, ...(profile.skills || []), profile.about].filter(Boolean).join(' ').toLowerCase()
  const templates = /analytical|method development|hplc|chromatography|laboratory|quality control/.test(text)
    ? ['maintaining reliable analytical methods', 'controlling impurities and degradation products', 'managing laboratory data integrity']
    : /quality assurance|gmp|validation|data integrity/.test(text)
      ? ['maintaining compliant quality systems', 'reviewing deviations, CAPA and audit readiness', 'ensuring validated data supports regulated decisions']
      : /cmc|process development|technical operations/.test(text)
        ? ['scaling a robust process', 'controlling process-related impurities', 'transferring technical methods into manufacturing']
        : /regulatory|submission/.test(text)
          ? ['assembling defensible CMC evidence', 'answering regulator questions', 'maintaining consistent technical documentation']
          : []
  return templates.map(problem => ({contact_id: contactId, problem, context: 'Role and supplied profile vocabulary support this functional hypothesis; current active need is not confirmed.', attribution: 'FUNCTIONAL', technical_relevance: 'analytical_quality', svak_relevance: 'INFERRED', confidence: 0.6, source_ids: [sourceId]}))
}
type PersonaProfile = Pick<ProfileExtraction, 'currentTitle' | 'currentCompany' | 'skills' | 'about' | 'positions' | 'education' | 'works' | 'themes'>
/**
 * Produce cautious professional-persona hypotheses from explicit profile
 * observations. These are never treated as psychological facts or scoring
 * inputs; every statement carries the source that supplied its anchors.
 */
export function inferProfilePersona(profile: PersonaProfile, contactId: string, sourceId: string) {
  const anchors: string[] = []
  const skills = [...new Set((profile.skills || []).map(String).map(x => x.trim()).filter(Boolean))].slice(0, 6)
  const education = (profile.education || []).map(item => [item.degree, item.field, item.institution].filter(Boolean).join(' at ')).filter(Boolean).slice(0, 3)
  const career = (profile.positions || []).map(item => [item.title, item.company_name].filter(Boolean).join(' at ')).filter(Boolean).slice(0, 4)
  const works = (profile.works || []).map(item => [item.work_type, item.title, item.topic].filter(Boolean).join(': ')).filter(Boolean).slice(0, 3)
  const themes = [...new Set((profile.themes || []).map(String).map(x => x.trim()).filter(Boolean))].slice(0, 6)
  if (education.length) anchors.push(`education: ${education.join('; ')}`)
  if (skills.length) anchors.push(`vocabulary/skills: ${skills.join(', ')}`)
  if (career.length) anchors.push(`career: ${career.join('; ')}`)
  if (works.length) anchors.push(`work: ${works.join('; ')}`)
  if (themes.length) anchors.push(`themes: ${themes.join(', ')}`)
  if (profile.about) anchors.push(`about: ${String(profile.about).slice(0, 220)}`)
  if (!anchors.length) return []
  const text = [profile.currentTitle, profile.currentCompany, ...skills, ...themes, profile.about].filter(Boolean).join(' ').toLowerCase()
  const hypotheses: string[] = []
  if (/analytical|method|hplc|chromatography|laboratory|impurity|stability|validation/.test(text)) hypotheses.push('Likely evidence-led and technically rigorous in professional decisions.')
  if (/head|director|vp|vice president|chief|lead|manager/.test(text) || career.length > 1) hypotheses.push('Likely balances functional ownership with cross-functional coordination.')
  if (/ph\.d|phd|master|mba|university|research|publication/.test(text) || education.length > 1) hypotheses.push('Likely values structured learning and defensible specialist evidence.')
  if (/quality|gmp|regulatory|compliance|data integrity/.test(text)) hypotheses.push('Likely risk-aware and attentive to traceability, compliance and decision confidence.')
  if (!hypotheses.length) hypotheses.push('Likely oriented toward the priorities reflected in the documented role and professional vocabulary.')
  return hypotheses.slice(0, 4).map(statement => ({
    contact_id: contactId,
    claim_type: 'PERSONA_INFERENCE',
    claim_text: `${statement} Anchored observations: ${anchors.join('; ')}.`,
    provenance: 'INFERRED',
    confidence: 0.52,
    source_ids: [sourceId],
  }))
}
export const emptyIntelligence = (): ContactIntelligence => ({sources:[],positions:[],education:[],works:[],problems:[],themes:[],jtbd:[],persona:[],claims:[],notes:[],history:[],conflicts:[],researchRuns:[]})
export function dedupeSources(rows: any[] = []): ContactSource[] { const seen = new Map<string, any>(); for (const row of rows) { const key = String(row.url || '').trim().toLowerCase(); if (key && !seen.has(key)) seen.set(key, row) } return [...seen.values()] }
export function normalizeContactIntelligence(contactId: string, tables: Record<string, any[]>): ContactIntelligence {
  const sourceRows = tables.sources?.filter(x => x.contact_id === contactId) ?? []
  // contact_evidence is already canonical, accepted production evidence. It
  // remains a provenance-preserving fallback if the richer source workspace
  // read is temporarily unavailable; it never manufactures a claim.
  const evidenceSources = (tables.evidence?.filter(x => x.contact_id === contactId) ?? [])
    .filter((row: any) => Boolean(row.source_url))
    .map((row: any) => ({
      id: `contact-evidence:${row.contact_id}:${row.source_url}`,
      url: row.source_url,
      title: row.evidence_type ? `${row.evidence_type} evidence` : 'Accepted contact evidence',
      source_type: row.source_type || 'OTHER_PUBLIC',
      source_date: row.observed_at || null,
      status: 'USED' as SourceState,
      evidence_strength: 'CANONICAL_CONTACT_EVIDENCE',
      why_used: 'Accepted canonical contact evidence',
      source_kind: 'CONTACT_EVIDENCE',
    }))
  const claims = tables.claims?.filter(x => x.contact_id === contactId) ?? []
  return { sources: dedupeSources([...sourceRows, ...evidenceSources]), positions: tables.positions?.filter(x => x.contact_id === contactId) ?? [], education: tables.education?.filter(x => x.contact_id === contactId) ?? [], works: tables.works?.filter(x => x.contact_id === contactId) ?? [], problems: tables.problems?.filter(x => x.contact_id === contactId) ?? [], themes: tables.themes?.filter(x => x.contact_id === contactId) ?? [], jtbd: tables.jtbd?.filter(x => x.contact_id === contactId) ?? [], persona: claims.filter(x => x.claim_type === 'PERSONA_INFERENCE'), claims: claims.filter(x => x.claim_type !== 'PERSONA_INFERENCE'), notes: tables.notes?.filter(x => x.contact_id === contactId) ?? [], history: tables.history?.filter(x => x.contact_id === contactId) ?? [], conflicts: tables.conflicts?.filter(x => x.contact_id === contactId) ?? [], researchRuns: tables.researchRuns?.filter(x => x.contact_id === contactId) ?? [] }
}
export function sourceCoverage(sources: ContactSource[]) { const classes = new Set(sources.map(s => s.source_type)); return { inspected: sources.length, used: sources.filter(s => s.status === 'USED').length, rejected: sources.filter(s => s.status === 'REJECTED').length, blocked: sources.filter(s => s.status === 'BLOCKED_AUTH').length, pending: sources.filter(s => s.status === 'PENDING_REVIEW').length, classes: classes.size, byType: [...classes].map(type => ({type, inspected: sources.filter(s => s.source_type === type).length, used: sources.filter(s => s.source_type === type && s.status === 'USED').length, rejected: sources.filter(s => s.source_type === type && s.status === 'REJECTED').length})) } }
export type ProfilePosition = {title:string; company_name?:string; department?:string; start_date?:string; end_date?:string; location?:string; description?:string; employment_type?:string; attribution:'PERSON_DIRECT'; confidence:number; review_suggested?:boolean}
export type ProfileEducation = {institution:string; degree?:string; field?:string; start_date?:string; end_date?:string; description?:string; confidence:number; review_suggested?:boolean}
export type ProfileWork = {title:string; work_type:string; work_date?:string; topic?:string; url?:string; authors?:string; publisher?:string; description?:string; attribution:'PERSON_DIRECT'; confidence:number; review_suggested?:boolean}
export type PdfFailureClass = 'IMAGE_ONLY_PDF'|'TEXT_PRESENT_BUT_RECONSTRUCTION_FAILED'|'CORRUPT_OR_UNSUPPORTED_PDF'
export type PdfTextExtraction = { text: string; pages: number; warnings: string[]; failureClass?: PdfFailureClass; metrics?: { itemCounts: number[]; characterCounts: number[]; averageItemLengths: number[]; fragmentedPages: number[] } }
export type ProfileExtraction = { claims: string[]; currentTitle?: string; headline?: string; currentCompany?: string; location?: string; about?: string; skills?: string[]; certifications?: {name:string; issuer?:string; issue_date?:string; expiry_date?:string; credential_url?:string; confidence:number; review_suggested?:boolean}[]; activities?: ProfileWork[]; positions: ProfilePosition[]; education: ProfileEducation[]; themes: string[]; keywords: string[]; works: ProfileWork[]; warnings?: string[]; pages?: number; parser_version?: string }

const sectionAliases: Record<string, string> = {
  'about':'ABOUT','experience':'EXPERIENCE','work experience':'EXPERIENCE','education':'EDUCATION',
  'licenses & certifications':'CERTIFICATIONS','licenses and certifications':'CERTIFICATIONS','certifications':'CERTIFICATIONS',
  'projects':'PROJECTS','publications':'PUBLICATIONS','patents':'PATENTS','skills':'SKILLS','activity':'ACTIVITY',
  'recommendations':'RECOMMENDATIONS','honors & awards':'OTHER','honours & awards':'OTHER','volunteer experience':'OTHER',
  'languages':'OTHER','interests':'OTHER'
}
const profileHeadings = Object.keys(sectionAliases)
const uiNoise = /^(home|my network|messaging|notifications|jobs|contact info|see more|show all|linkedin|follow|connect|send message|subscribe|followers?|connections?|people also viewed|interests?)$/i
// LinkedIn exports append tenure after the date range, e.g.
// "May 2008 - Present · 18 yrs 5 mos". Keep the date portion and ignore the
// trailing tenure when building canonical career positions.
const dateRange = /^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+)?(?:19|20)\d{2}\s*(?:[-–—]|to)\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+)?(?:(?:19|20)\d{2}|present|current)(?:\s*(?:·|\||•)\s*.*)?(?:\s*:\s*.*)?$/i
const durationLine = /^\d+\s+(?:yr|yrs|year|years|mo|mos|month|months)/i
const profileFooter = /^(?:accessibility|talent solutions|community guidelines|careers|marketing solutions|privacy & terms|ad choices|advertising|sales solutions|mobile small business|safety center|linkedin corporation|questions\?|visit our help center|recommendation transparency|learn more about recommended content|go to your settings|home|my network|messaging|notifications|search|me|for business|learning|more profiles for you|show more|show all \d+ educations?)\b/i
const noisySkill = /(?:endorsement|endorsed by|logo$|show all|\b(?:all|industry knowledge|tools & technologies|interpersonal skills)\b|community guidelines|privacy & terms|linkedin corporation|\b\d+\+?\s+endorsements?\b)/i
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
function isLikelyCompany(line: string) { return /\b(pharma(?:ceuticals?)?|laborator(?:y|ies)|therapeutics?|biotech|inc\.?|ltd\.?|limited|corporation|corp\.?|holdings?|university|institute|hospital|group|cipla|takeda|novartis|bayer|lupin|ipca|indoco|elder)\b/i.test(line) }
function isLikelyDegree(line: string) { return /\b(?:M\.?\s*(?:Sc|Pharm|Tech|Eng|BA|BS|MBA)|B\.?\s*(?:Pharm|Tech|Sc|Eng|BA|BS)|Ph\.?\s*D|Bachelor|Master|Doctor|Diploma|Certificate|Post[- ]?graduate|Fellowship)\b/i.test(line) }
function sectionLines(sections: Record<string,string[]>, key: string) { return (sections[key] || []).filter(line => !uiNoise.test(line) && !profileFooter.test(line) && line.length > 1) }
function cleanAbout(value: string | undefined): string | undefined {
  if (!value) return undefined
  const cleaned = value.split(/\b(?:Accessibility|Talent Solutions|Community Guidelines|Careers|Marketing Solutions|Privacy & Terms|Ad Choices|Advertising|Sales Solutions|LinkedIn Corporation)\b/i)[0]
    .replace(/\s+/g, ' ').trim()
  return cleaned.length >= 20 ? cleaned.slice(0, 700) : undefined
}

function parseExperience(lines: string[]): ProfilePosition[] {
  const positions: ProfilePosition[] = []; let lastDateIndex = -1; let currentCompany = ''
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]; if (!isDateLine(line)) continue
    const range = parseDateRange(line); const trailing = line.match(/:\s*(.+)$/)?.[1]?.trim() || ''; const before = lines.slice(lastDateIndex + 1, i).filter(x => !durationLine.test(x) && !isDateLine(x) && !/^(?:full[- ]?time|part[- ]?time|contract|internship|freelance)$/i.test(x) && !/\blogo$/i.test(x))
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
  const about = cleanAbout(sectionLines(sections, 'ABOUT').join(' ').trim())
  const education = parseEducation(sectionLines(sections, 'EDUCATION').length ? sectionLines(sections, 'EDUCATION') : fallbackLines)
  const certifications = sectionLines(sections, 'CERTIFICATIONS').map(name => ({name, confidence: confidenceFor(name, true), review_suggested: isSuspiciousExtractedField(name)})).filter(x => x.name.length > 2).slice(0, 30)
  const projects = parseWorkSection(sectionLines(sections, 'PROJECTS'), 'PROJECT')
  const publications = parseWorkSection(sectionLines(sections, 'PUBLICATIONS'), 'PUBLICATION')
  const patents = parseWorkSection(sectionLines(sections, 'PATENTS'), 'PATENT')
  const activities = parseWorkSection(sectionLines(sections, 'ACTIVITY'), 'PROFESSIONAL_ACTIVITY')
  const works = [...projects, ...publications, ...patents, ...activities]
  const skills = sectionLines(sections, 'SKILLS').flatMap(x => x.split(/,|•|;/).map(y => y.trim())).filter(x => x.length > 1 && x.length < 100 && !noisySkill.test(x)).slice(0, 40)
  const profileClaims = [headline && `Professional headline: ${headline}`, currentTitle && `Current title: ${currentTitle}`, currentCompany && `Current company: ${currentCompany}`, location && `Professional location: ${location}`, about && `Professional summary: ${about.slice(0, 600)}`, skills.length && `Explicit professional skills: ${skills.slice(0, 12).join(', ')}`, certifications.length && `Certifications supplied: ${certifications.map(c => c.name).join(', ')}`].filter(Boolean) as string[]
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

function reconstructPdfPage(items: any[]): { text: string; fragmented: boolean } {
  const positioned = items.map(item => ({
    text: String(item.str || ''),
    x: Array.isArray(item.transform) ? Number(item.transform[4] || 0) : 0,
    y: Array.isArray(item.transform) ? Number(item.transform[5] || 0) : 0,
    width: Number(item.width || 0),
    hasEOL: Boolean(item.hasEOL),
  })).filter(item => item.text.trim())
  positioned.sort((a, b) => b.y - a.y || a.x - b.x)
  const lines: { y: number; items: typeof positioned }[] = []
  for (const item of positioned) {
    const line = lines.find(candidate => Math.abs(candidate.y - item.y) <= 3)
    if (line) line.items.push(item); else lines.push({y: item.y, items: [item]})
  }
  const rendered = lines.map(line => {
    line.items.sort((a, b) => a.x - b.x)
    const averageLength = line.items.reduce((sum, item) => sum + item.text.length, 0) / Math.max(1, line.items.length)
    const fragmented = line.items.length > 8 && averageLength <= 2
    let value = ''
    for (const item of line.items) {
      const previous = line.items[line.items.indexOf(item) - 1]
      const gap = previous ? item.x - (previous.x + previous.width) : 0
      const separator = !value || fragmented ? (fragmented && gap < 8 ? '' : ' ') : gap > 4 ? ' ' : ''
      value += separator + item.text
    }
    return {value: value.trim(), fragmented}
  })
  return {text: rendered.map(item => item.value).filter(Boolean).join('\n'), fragmented: rendered.some(item => item.fragmented)}
}

export async function extractPdfText(buffer: ArrayBuffer): Promise<PdfTextExtraction> {
  const warnings: string[] = []; const itemCounts: number[] = []; const characterCounts: number[] = []; const averageItemLengths: number[] = []; const fragmentedPages: number[] = []
  try {
    const pdfjs: any = await import('pdfjs-dist/legacy/build/pdf.mjs')
    const document = await pdfjs.getDocument({data: new Uint8Array(buffer), disableWorker: true}).promise
    const pages: string[] = []
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber++) {
      const page = await document.getPage(pageNumber); const content = await page.getTextContent();
      const items = (content.items || []).filter((item: any) => typeof item.str === 'string')
      itemCounts.push(items.length); characterCounts.push(items.reduce((sum: number, item: any) => sum + String(item.str || '').length, 0)); averageItemLengths.push(items.length ? characterCounts[characterCounts.length - 1] / items.length : 0)
      const reconstructed = reconstructPdfPage(items); if (reconstructed.fragmented) fragmentedPages.push(pageNumber); pages.push(reconstructed.text)
    }
    const text = pages.join('\n\n').replace(/[ \t]+\n/g, '\n').trim(); const metrics = {itemCounts, characterCounts, averageItemLengths, fragmentedPages}
    if (!text && itemCounts.every(count => count === 0)) { warnings.push('No machine-readable text objects were found. Try Paste LinkedIn Text.'); return {text, pages: document.numPages, warnings, failureClass:'IMAGE_ONLY_PDF', metrics} }
    if (text.length < 40) { warnings.push('Very little machine-readable text was found. Try Paste LinkedIn Text.'); return {text, pages: document.numPages, warnings, failureClass:'TEXT_PRESENT_BUT_RECONSTRUCTION_FAILED', metrics} }
    return {text, pages: document.numPages, warnings, metrics}
  } catch (error) {
    const safeError = error instanceof Error ? `${error.name}: ${error.message.slice(0, 160)}` : 'Unknown PDF parser error'
    warnings.push(`The PDF could not be read as machine-readable text (${safeError}). Try Paste LinkedIn Text.`)
    return {text: '', pages: 0, warnings, failureClass:'CORRUPT_OR_UNSUPPORTED_PDF', metrics:{itemCounts, characterCounts, averageItemLengths, fragmentedPages}}
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
  const observedClaims = intel.claims.filter(c => c.provenance === 'OBSERVED').map(c => String(c.claim_text || '')).filter(Boolean)
  const summaryClaim = observedClaims.find(c => /^professional summary:/i.test(c))
  const headlineClaim = observedClaims.find(c => /^professional headline:/i.test(c))
  const observed = [headlineClaim, summaryClaim].filter(Boolean).map(c => String(c).replace(/^[^:]+:\s*/, '')).join(' ')
  const roles = intel.positions.slice(0, 5).map(p => [p.title, p.company_name].filter(Boolean).join(' at ')).join('; ')
  const direct = intel.works.filter(w => w.attribution === 'PERSON_DIRECT').map(w => w.title).join('; ')
  const companyWork = intel.works.filter(w => w.attribution !== 'PERSON_DIRECT').map(w => w.title).join('; ')
  const problems = intel.problems.map(p => p.problem).join('; ')
  const themes = intel.themes.map(t => t.theme).join(', ')
  const jtbd = intel.jtbd.slice(0, 3).map(j => j.statement).join('; ')
  const persona = (intel.persona || []).slice(0, 2).map(item => String(item.claim_text || '').split(/\s+Anchored observations:/i)[0]).filter(Boolean).join(' ')
  return `${contact.name} is publicly described as ${contact.title || 'a professional contact'} at ${company}${contact.function ? `, working in ${contact.function}` : ''}. ${observed ? `The supplied profile describes ${observed}` : ''} ${roles ? `Documented career history includes ${roles}.` : ''} ${intel.education.length ? `Public education records include ${intel.education.slice(0, 3).map(e => [e.degree, e.institution].filter(Boolean).join(' at ')).join('; ')}.` : ''} ${direct ? `Person-direct technical work includes ${direct}.` : 'No person-specific technical publication, patent or project has been independently verified.'} ${companyWork ? `Organisational context includes ${companyWork}; this does not establish personal authorship.` : ''} ${problems ? `Role-related problem areas are ${problems}.` : ''} ${themes ? `Professional themes include ${themes}.` : ''} ${jtbd ? `Inferred JTBD hypotheses include ${jtbd}.` : ''} ${persona ? `Persona hypotheses include ${persona}` : ''} Current priorities, active projects, supplier preferences and purchase requirements remain unknown.`
}
