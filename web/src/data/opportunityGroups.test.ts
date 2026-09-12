import { describe, expect, it } from 'vitest'
import { filterCompanyOpportunityGroups, groupCompanyOpportunities, moleculeEvidenceLabel } from './opportunityGroups'

const lead = (companyId: string, company: string, molecule: string, score: number, priority: string, signal = 'impurity') => ({
  id: `${companyId}-${molecule}`,
  account: { company, company_id: companyId, domain: `${companyId}.example` },
  opportunity: { molecule, score, priority, company_id: companyId, molecule_id: molecule.toLowerCase() },
  evidence: [{ url: `https://${companyId}.example/${molecule}`, date: '2026-09-10', signal_types: [signal] }],
  contacts: [],
})

describe('company opportunity read model', () => {
  it('renders one company group with all molecule children', () => {
    const groups = groupCompanyOpportunities([
      lead('jubilant', 'Jubilant Generics', 'Marbofloxacin', 82, 'HIGH'),
      lead('jubilant', 'Jubilant Generics', 'Eslicarbazepine', 91, 'HOT'),
      lead('jubilant', 'Jubilant Generics', 'Niacinamide', 64, 'REVIEW'),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]).toMatchObject({ companyId: 'jubilant', moleculeCount: 3, maxScore: 91, priority: 'HOT' })
    expect(groups[0].opportunities.map((item) => item.opportunity.molecule)).toEqual(['Eslicarbazepine', 'Marbofloxacin', 'Niacinamide'])
  })

  it('never collapses different canonical company ids with similar names', () => {
    const groups = groupCompanyOpportunities([
      lead('a', 'Acme Pharma', 'Drug A', 80, 'HIGH'),
      lead('b', 'Acme Pharma', 'Drug B', 90, 'HOT'),
    ])
    expect(groups.map((group) => group.companyId)).toEqual(['b', 'a'])
  })

  it('retains a company when a child molecule matches search or filters', () => {
    const groups = groupCompanyOpportunities([
      lead('jubilant', 'Jubilant Generics', 'Marbofloxacin', 82, 'HIGH'),
      lead('jubilant', 'Jubilant Generics', 'Eslicarbazepine', 91, 'HOT'),
      lead('other', 'Other Pharma', 'Marbofloxacin', 95, 'HOT'),
    ])
    const filtered = filterCompanyOpportunityGroups(groups, { query: 'Eslicarbazepine', priority: 'HOT' })
    expect(filtered).toHaveLength(1)
    expect(filtered[0].companyId).toBe('jubilant')
    expect(filtered[0].opportunities.map((item) => item.opportunity.molecule)).toEqual(['Eslicarbazepine'])
  })

  it('uses only explicitly linked child contacts for company readiness', () => {
    const first = lead('jubilant', 'Jubilant Generics', 'Marbofloxacin', 82, 'HIGH')
    first.contacts = [{ id: 'contact-1', name: 'A. Buyer', role_fit_score: 77 }]
    const groups = groupCompanyOpportunities([first, lead('jubilant', 'Jubilant Generics', 'Niacinamide', 64, 'REVIEW')])
    expect(groups[0].readiness).toBe('ready')
    expect(groups[0].topContact?.id).toBe('contact-1')
  })

  it('labels supported, partial, and unknown molecule intelligence conservatively', () => {
    expect(moleculeEvidenceLabel({ evidence_status: 'SUPPORTED' })).toBe('Evidence-backed summary')
    expect(moleculeEvidenceLabel({ evidence_status: 'PARTIAL' })).toContain('Partial summary')
    expect(moleculeEvidenceLabel({ evidence_status: 'UNKNOWN' })).toBe('Intelligence research pending')
  })
})
