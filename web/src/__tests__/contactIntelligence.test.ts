import { describe, expect, it } from 'vitest'
import { dedupeSources, normalizeContactIntelligence, sourceCoverage } from '../data/contactIntelligence'

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
})
