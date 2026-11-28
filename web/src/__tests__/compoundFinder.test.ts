import { describe, expect, it } from 'vitest'
import { companyFromAffiliation, companyKey, findBuyers } from '../lib/compoundFinder'

const responses: Record<string, any> = {
  drugsfda: { results: [{ sponsor_name: 'DR REDDYS', application_number: 'ANDA214685', submissions: [{ submission_status_date: '20240105' }, { submission_status_date: '20251110' }] }] },
  ndc: { results: [{ labeler_name: 'ScieGen Pharmaceuticals Inc', brand_name: 'Sitagliptin', product_ndc: '50228-505' }] },
  europepmc: { resultList: { result: [{ pmid: '41000002', title: 'Identification of sitagliptin degradation impurities', firstPublicationDate: '2026-06-01', authorList: { author: [
    { firstName: 'Chandra S', lastName: 'Malleswararao', authorAffiliationDetailsList: { authorAffiliation: [{ affiliation: "Analytical R&D, Dr. Reddy's Laboratories Ltd., Hyderabad, India. malleswararao@drreddys.com" }] } },
    { fullName: 'Rao A', authorAffiliationDetailsList: { authorAffiliation: [{ affiliation: 'Department of Chemistry, Osmania University, Hyderabad' }] } },
  ] } }] } },
}
const fake = async (url: string) => responses[url.includes('drugsfda') ? 'drugsfda' : url.includes('ndc.json') ? 'ndc' : 'europepmc']

describe('compound buyer finder', () => {
  it('merges FDA filers with the same company named in a paper, and lists its scientists', async () => {
    const results = await findBuyers('sitagliptin', fake)
    const reddy = results.find(r => r.key === companyKey('DR REDDYS'))!
    expect(results[0]).toBe(reddy)
    expect(reddy.reasons.map(r => r.kind).sort()).toEqual(['fda_application', 'publication'])
    expect(reddy.people).toEqual([expect.objectContaining({ name: 'Chandra S Malleswararao', email: 'malleswararao@drreddys.com' })])
    expect(reddy.latest).toBe('2026-06-01')
    expect(results.some(r => r.name === 'ScieGen Pharmaceuticals Inc')).toBe(true)
    // University authors are not buyers.
    expect(results.some(r => /osmania/i.test(r.name))).toBe(false)
  })

  it('normalises company names and ignores academic affiliations', () => {
    expect(companyKey("Dr. Reddy's Laboratories Limited")).toBe(companyKey('DR REDDYS LABS LTD'))
    expect(companyFromAffiliation('Process Development, Amgen, Inc., Thousand Oaks')).toBe('Amgen Inc')
    expect(companyFromAffiliation('School of Pharmacy, University of Nottingham')).toBeNull()
  })

  it('returns nothing for an empty name and survives a source that fails', async () => {
    expect(await findBuyers('  ', fake)).toEqual([])
    const results = await findBuyers('sitagliptin', async url => { if (url.includes('ndc')) throw new Error('down'); return fake(url) })
    expect(results.length).toBe(1)
  })
})
