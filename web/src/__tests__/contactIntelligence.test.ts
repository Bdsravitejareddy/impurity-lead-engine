import { describe, expect, it } from 'vitest'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { dedupeSources, normalizeContactIntelligence, sourceCoverage, researchCompleteness, personSummary, extractProfessionalProfile, researchQueries, extractPdfText, isSuspiciousExtractedField, inferProfileJtbd, inferProfilePersona, inferProfileProblems } from '../data/contactIntelligence'
import { normalizeProfileRows, profileSourceKey } from '../data/profilePersistence'

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
  it('uses accepted canonical contact evidence as a source fallback when source rows are temporarily unavailable', () => {
    const intel = normalizeContactIntelligence('c1', {
      sources: [], positions: [], education: [], works: [], problems: [], themes: [], jtbd: [], claims: [], notes: [], history: [], conflicts: [], researchRuns: [],
      evidence: [{ contact_id: 'c1', source_url: 'https://example.test/publication', source_type: 'PUBLICATION', observed_at: '2026-09-20', evidence_text: 'Author listed.' }],
    })
    expect(intel.sources).toEqual([expect.objectContaining({
      url: 'https://example.test/publication', source_type: 'PUBLICATION', status: 'USED',
    })])
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
  it('extracts a structured PDF result and warns when machine-readable text is sparse', async () => {
    const buffer = new TextEncoder().encode('BT (Keisuke Inoue) (Site Quality) ET').buffer
    const result = await extractPdfText(buffer)
    expect(result.text).toBe('')
    expect(result.failureClass).toBe('CORRUPT_OR_UNSUPPORTED_PDF')
    expect(result.warnings.join(' ')).toMatch(/machine-readable|could not be read/i)
  })
  it('parses a realistic multi-role LinkedIn profile by section', () => {
    const profile = extractProfessionalProfile(`
      Home\nMy Network\nMessaging\n\nAsha Rao\nDirector, Analytical Development\nMumbai, India\n\nAbout\nAnalytical development leader for complex generic products and stability programmes.\n\nExperience\nCipla Limited\nDirector, Analytical Development\nJan 2022 - Present\nMumbai, India\nLeads analytical readiness and method validation across regulated programmes.\nManager, Analytical R&D\n2018 - 2022\nMumbai, India\n\nNova Therapeutics\nScientist, CMC\n2015 - 2018\n\nEducation\nUniversity of Mumbai\nMaster of Pharmacy\nPharmaceutical Chemistry\n2009 - 2011\n\nLicenses & certifications\nGood Manufacturing Practice — ISPE\n\nProjects\nGlobal stability method programme\n\nPublications\nStability-indicating method validation for complex generics\n\nPatents\nImpurity control process\n\nSkills\nAnalytical Development, CMC, Method Validation, Quality Systems\n    `, 'Asha Rao')
    expect(profile.currentTitle).toMatch(/Director/i)
    expect(profile.currentCompany).toMatch(/Cipla/i)
    expect(profile.positions.length).toBe(3)
    expect(profile.positions[0].end_date).toBe('')
    expect(profile.positions.slice(0, 2).every(position => /Cipla/i.test(position.company_name || ''))).toBe(true)
    expect(profile.education[0]).toMatchObject({institution: 'University of Mumbai', degree: 'Master of Pharmacy', field: 'Pharmaceutical Chemistry'})
    expect(profile.certifications?.[0].name).toMatch(/Good Manufacturing/i)
    expect(profile.works.some(work => work.work_type === 'PROJECT')).toBe(true)
    expect(profile.works.some(work => work.work_type === 'PUBLICATION')).toBe(true)
    expect(profile.works.some(work => work.work_type === 'PATENT')).toBe(true)
    expect(profile.skills).toEqual(expect.arrayContaining(['Analytical Development', 'CMC']))
  })
  it('parses LinkedIn tenure suffixes and nested employer roles without misassigning the company', () => {
    const profile = extractProfessionalProfile(`
      Dr. Amit Gosar
      Experience
      Indoco Remedies Ltd
      18 yrs 5 mos
      Head - Indoco Analytical Solutions
      Full-time
      May 2008 - Present · 18 yrs 5 mos
      Navi Mumbai, Maharashtra, India
      Project Management, Business Development and +5 skills
      Head Analytical research and development (API)
      May 2008 - Present · 18 yrs 5 mos
      Analytical method development, analytical method validations, impurity profile and characterization.
      Sr. Manager ADL
      Elder pharmaceuticals Ltd.
      Jan 2007 - May 2008 · 1 yr 5 mos
      Analytical method development, method validation, impurity profiling, polymorphism
      IPCA logo
      Asst. Manager
      IPCA
      2000 – 2006
      Education
      MEDIAMITRA-Digital Marketing Course Training Institute
      Master's degree, Digital Marketing
    `, 'Dr. Amit Gosar')
    expect(profile.positions.length).toBe(4)
    expect(profile.positions[0]).toMatchObject({title: 'Head - Indoco Analytical Solutions', company_name: 'Indoco Remedies Ltd', end_date: ''})
    expect(profile.positions[1]).toMatchObject({title: 'Head Analytical research and development (API)', company_name: 'Indoco Remedies Ltd', end_date: ''})
    expect(profile.positions[2]).toMatchObject({title: 'Sr. Manager ADL', company_name: 'Elder pharmaceuticals Ltd.'})
    expect(profile.positions[3]).toMatchObject({title: 'Asst. Manager', company_name: 'IPCA'})
  })
  it('removes LinkedIn footer and endorsement noise from observed claims and summary', () => {
    const profile = extractProfessionalProfile(`
      Dr. Amit Gosar
      Head - Indoco Analytical Solutions
      Indoco Remedies Ltd
      About
      Experienced Head with a demonstrated history in pharmaceuticals. Skilled in method development and validation.
      Accessibility Talent Solutions Community Guidelines Careers Marketing Solutions Privacy & Terms Ad Choices
      Experience
      Indoco Remedies Ltd
      Head - Indoco Analytical Solutions
      May 2008 - Present · 18 yrs 5 mos
      Skills
      Analytical Research and Development, HPLC, Endorsed by 25 colleagues at Indoco Remedies Ltd., Privacy & Terms
    `, 'Dr. Amit Gosar')
    expect(profile.claims.join(' ')).not.toMatch(/Accessibility|Endorsed by|Privacy & Terms/i)
    expect(profile.skills).toEqual(expect.arrayContaining(['Analytical Research and Development', 'HPLC']))
    expect(profile.skills).not.toContain('Endorsed by 25 colleagues at Indoco Remedies Ltd.')
    const summary = personSummary(normalizeContactIntelligence('c1', {sources: [{contact_id:'c1',url:'manual://c1',status:'USED',source_type:'PROFESSIONAL_PROFILE'}], positions: profile.positions.map(x => ({contact_id:'c1',...x})), education: [], works: [], problems: [], themes: [], jtbd: [], claims: profile.claims.map(claim_text => ({contact_id:'c1',claim_text,provenance:'OBSERVED'})), notes: [], history: [], conflicts: [], researchRuns: []}), {name: 'Dr. Amit Gosar', title: 'Head - Indoco Analytical Solutions'}, 'Indoco Remedies Ltd')
    expect(summary).not.toMatch(/Accessibility|Endorsed by|Privacy & Terms/i)
  })
  it('derives traceable inferred JTBD immediately from supplied profile context', () => {
    const rows = inferProfileJtbd({currentTitle: 'Head Analytical Research and Development', currentCompany: 'Indoco Remedies Ltd', skills: ['HPLC', 'Method validation'], about: 'Leads analytical method development.'}, 'c1', 'source-1')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows[0]).toMatchObject({provenance: 'INFERRED', source_ids: ['source-1'], basis: 'ROLE_ONTOLOGY_V1 + SUPPLIED_PROFILE_CONTEXT'})
    expect(rows[0]).not.toHaveProperty('id')
  })
  it('derives persona hypotheses with explicit observation anchors', () => {
    const persona = inferProfilePersona({
      currentTitle: 'Head - Analytical Research', currentCompany: 'Indoco Remedies',
      skills: ['Method development', 'HPLC', 'Validation'], about: 'Leads analytical development and impurity profiling.',
      positions: [{title: 'Head - Analytical Research', company_name: 'Indoco Remedies'}, {title: 'Manager', company_name: 'IPCA'}],
      education: [{degree: 'PhD Chemistry', institution: 'University of Mumbai'}], works: [], themes: ['analytical development', 'impurity']
    }, 'contact-1', 'source-1')
    expect(persona.length).toBeGreaterThan(0)
    expect(persona[0]).toMatchObject({claim_type: 'PERSONA_INFERENCE', provenance: 'INFERRED', source_ids: ['source-1']})
    expect(persona[0].claim_text).toMatch(/Anchored observations:/i)
    expect(persona[0].claim_text).toMatch(/education|vocabulary|career|work/i)
  })
  it('separates persona inferences from ordinary claims', () => {
    const intel = normalizeContactIntelligence('c1', {sources: [], positions: [], education: [], works: [], problems: [], themes: [], jtbd: [], claims: [{contact_id:'c1', claim_type:'PERSONA_INFERENCE', claim_text:'Working style hypothesis', provenance:'INFERRED'}], notes: [], history: [], conflicts: [], researchRuns: []})
    expect(intel.persona).toHaveLength(1)
    expect(intel.claims).toHaveLength(0)
  })
  it('derives role problems from supplied evidence without claiming observed demand', () => {
    const problems = inferProfileProblems({currentTitle: 'Head Analytical Research', currentCompany: 'Indoco Remedies', skills: ['HPLC'], about: 'Leads impurity profiling and validation.'}, 'contact-1', 'source-1')
    expect(problems.length).toBeGreaterThan(0)
    expect(problems[0]).toMatchObject({attribution: 'FUNCTIONAL', confidence: 0.6, source_ids: ['source-1']})
    expect(problems[0].problem).toMatch(/analytical|impurit/i)
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
  it('executes source-key generation after hashing supplied profile content', () => {
    const key = profileSourceKey('contact-1', '', 'Vijayasarathi Ramaswami profile', 123)
    expect(key).toMatch(/^manual:\/\/contact-1\/[0-9a-f]+$/)
    expect(profileSourceKey('contact-1', 'https://example.com/profile', 'profile', 123)).toBe('https://example.com/profile')
    expect(profileSourceKey('contact-1', '  ', '', 123)).toBe('manual://contact-1/123')
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
  it('extracts text from a sanitized LinkedIn-style PDF fixture page by page', async () => {
    const bytes = await readFile(resolve(process.cwd(), 'src/__tests__/fixtures/linkedin-profile-sample.pdf'))
    const result = await extractPdfText(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))
    expect(result.pages).toBe(1)
    expect(result.warnings).toEqual([])
    expect(result.text).toContain('Director, Analytical Development')
    expect(extractProfessionalProfile(result.text, 'Asha Rao').currentCompany).toMatch(/Cipla/i)
  })
})
