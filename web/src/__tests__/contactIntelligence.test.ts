import { describe, expect, it } from 'vitest'
import { dedupeSources, normalizeContactIntelligence, sourceCoverage, researchCompleteness, personSummary, extractProfessionalProfile, researchQueries, extractPdfText, isSuspiciousExtractedField } from '../data/contactIntelligence'
import { normalizeProfileRows } from '../data/profilePersistence'

describe('contact intelligence normalization', () => {
  it('deduplicates a source URL while retaining status', () => {
    const rows = dedupeSources([{ url: 'https://example.com', status: 'INSPECTED', source_type: 'web' }, { url: 'https://example.com', status: 'USED', source_type: 'web' }])
    expect(rows).toHaveLength(1)
  })
  it('keeps person and company work attribution separate', () => {
    const model = normalizeContactIntelligence('c1', { sources: [], positions: [], education: [], works: [{ contact_id: 'c1', attribution: 'PERSON_DIRECT' }, { contact_id: 'c1', attribution: 'COMPANY_CONTEXT' }], problems: [], themes: [], jtbd: [], claims: [], notes: [], history: [], conflicts: [], researchRuns: [] })
    expect(model.works.map(x => x.attribution)).toEqual(['PERSON_DIRECT', 'COMPANY_CONTEXT'])
  })
  it('reports inspected, used, rejected and independent source classes', () => {
    expect(sourceCoverage([{ url: 'a', status: 'USED', source_type: 'Official company' }, { url: 'b', status: 'REJECTED', source_type: 'Professional profile' }])).toMatchObject({ inspected: 2, used: 1, rejected: 1, classes: 2 })
  })
  it('marks zero-source contacts unresearched and suppresses generic summaries', () => {
    const intel = normalizeContactIntelligence('k', {sources: [], positions: [], education: [], works: [], problems: [], themes: [], jtbd: [], claims: [], notes: [], history: [], conflicts: [], researchRuns: []})
    expect(researchCompleteness(intel, {profile_url: null, email: null, phone: null})).toMatchObject({score: 0, state: 'UNRESEARCHED'})
    expect(personSummary(intel, {name: 'Keisuke Inoue', title: 'Quality'}, 'Takeda')).toContain('Not enough verified evidence')
  })
  it('recognizes a deep profile from category coverage rather than row count', () => {
    const intel = normalizeContactIntelligence('v', {sources: [{contact_id:'v',url:'a',status:'USED',source_type:'Professional profile'},{contact_id:'v',url:'b',status:'USED',source_type:'Official company'}], positions: [{contact_id:'v',title:'Global Head'} ,{contact_id:'v',title:'VP'}], education: [{contact_id:'v',degree:'MSc'}], works: [{contact_id:'v',attribution:'PERSON_DIRECT'},{contact_id:'v',attribution:'COMPANY_CONTEXT'}], problems: [{contact_id:'v',problem:'Quality'}], themes: [{contact_id:'v',theme:'Quality'}], jtbd: [{contact_id:'v',statement:'Investigate impurities'}], claims: [{contact_id:'v',provenance:'OBSERVED',claim_text:'Current'}], notes: [], history: [], conflicts: [], researchRuns: [{contact_id:'v',status:'COMPLETED'}]})
    expect(researchCompleteness(intel, {profile_url:'p', email:null, phone:null})).toMatchObject({state: 'DEEP PROFILE'})
  })
  it('extracts observed profile facts and useful research queries from supplied text', () => {
    const profile = extractProfessionalProfile('Keisuke Inoue\nSenior Director, Site Quality Head\nTakeda Pharmaceuticals\nTokyo, Japan\n2018 – Present: Site Quality at Takeda\nMSc Chemistry from Kyoto University\nPresented a conference on analytical method validation and stability.', 'Keisuke Inoue')
    expect(profile.currentTitle).toMatch(/Quality/i)
    expect(profile.currentCompany).toMatch(/Takeda/i)
    expect(profile.positions.length).toBeGreaterThan(0)
    expect(profile.education.length).toBeGreaterThan(0)
    expect(profile.keywords).toContain('Keisuke')
    expect(researchQueries(profile, 'Keisuke Inoue')).toContain('Keisuke Inoue Takeda Pharmaceuticals publication')
  })
  it('retains blocked-auth as a distinct source state', () => {
    const coverage = sourceCoverage([{ url: 'https://www.linkedin.com/in/example', status: 'BLOCKED_AUTH', source_type: 'PROFESSIONAL_PROFILE' }])
    expect(coverage.blocked).toBe(1)
    expect(coverage.rejected).toBe(0)
  })
  it('extracts basic text operands from a supplied PDF buffer without claiming unsupported facts', () => {
    const buffer = new TextEncoder().encode('BT (Keisuke Inoue) (Site Quality) ET').buffer
    expect(extractPdfText(buffer)).toContain('Keisuke Inoue')
  })
  it('flags corrupted extracted education text without deleting the source value', () => {
    expect(isSuspiciousExtractedField('be UCS $ / >> P')).toBe(true)
    expect(isSuspiciousExtractedField('MSc Chemistry')).toBe(false)
    const profile = extractProfessionalProfile('Education\nMaster be UCS $ / >> P from University of Mumbai', 'Example')
    expect(profile.education[0]?.review_suggested).toBe(true)
  })
  it('normalizes profile writes to the production schema and excludes parser-only fields', () => {
    const profile = extractProfessionalProfile('Education\nMaster of Pharmacy from University of Mumbai\nExperience\n2022 - Present: Quality Director at Cipla\nProjects\nStability method validation', 'Example')
    profile.education.push({ institution: 'Noisy', degree: 'be UCS $ / >> P', confidence: 0.2, review_suggested: true })
    profile.works.push({ title: 'Project', work_type: 'PROJECT', url: 'https://example.test', attribution: 'PERSON_DIRECT', confidence: 0.7 })
    const rows = normalizeProfileRows(profile, 'contact-1', 'source-1', value => /^\d{4}$/.test(String(value || '')) ? `${value}-01-01` : null)
    expect(rows.education.every(row => !('review_suggested' in row))).toBe(true)
    expect(rows.education.some(row => row.institution === 'Noisy')).toBe(false)
    expect(rows.works.every(row => !('url' in row))).toBe(true)
    expect(rows.works[0]).toMatchObject({ contact_id: 'contact-1', source_ids: ['source-1'] })
  })
  it('structures a messy full-profile export without turning navigation text into work', () => {
    const profile = extractProfessionalProfile(`
      Home
      Vijayasarathi Ramaswami
      Global Head of Quality
      Cipla Limited
      Mumbai, India
      About
      Quality and analytical development leader supporting regulated pharmaceutical programs.
      Experience
      2022 – Present: Global Head of Quality at Cipla Limited
      2018 – 2022: Vice President, Quality at Example Pharma
      Education
      Master of Pharmacy from University of Mumbai
      Licenses & certifications
      Good Manufacturing Practice — ISPE
      Projects
      Global analytical readiness programme
      Publications
      Stability indicating method validation for complex generics
      Skills
      Analytical Development, CMC, Stability, Quality Systems
      LinkedIn
      See more
    `, 'Vijayasarathi Ramaswami')
    expect(profile.currentCompany).toMatch(/Cipla/i)
    expect(profile.positions.length).toBeGreaterThanOrEqual(2)
    expect(profile.education.length).toBeGreaterThan(0)
    expect(profile.certifications?.length).toBe(1)
    expect(profile.works.some(work => /analytical readiness/i.test(work.title))).toBe(true)
    expect(profile.skills).toEqual(expect.arrayContaining(['Analytical Development', 'CMC']))
    expect(profile.works.some(work => /^LinkedIn$/i.test(work.title))).toBe(false)
    expect(researchQueries(profile, 'Vijayasarathi Ramaswami').length).toBeLessThanOrEqual(20)
  })
})
