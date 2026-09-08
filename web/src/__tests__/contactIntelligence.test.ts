import { describe, expect, it } from 'vitest'
import { dedupeSources, normalizeContactIntelligence, sourceCoverage, researchCompleteness, personSummary } from '../data/contactIntelligence'

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
})
