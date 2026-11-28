import { describe, expect, it } from 'vitest'
import { fetchLabelFacts, labelText } from '../lib/moleculeLabel'

describe('molecule facts from the FDA label', () => {
  it('drops section numbers and headings', () => {
    expect(labelText(['11 DESCRIPTION Olaparib is a PARP inhibitor.'])).toBe('Olaparib is a PARP inhibitor.')
    expect(labelText(['13 NONCLINICAL TOXICOLOGY 13.1 Carcinogenesis, Mutagenesis, Impairment of Fertility Olaparib was clastogenic.'])).toBe('Olaparib was clastogenic.')
    expect(labelText(['INDICATIONS AND USAGE Sucralfate tablets are indicated in ulcers.'])).toBe('Sucralfate tablets are indicated in ulcers.')
  })

  it('builds sections with sources, and the buyer pool from approvals', async () => {
    const fake = async (url: string) => url.includes('label.json')
      ? { results: [{ description: ['11 DESCRIPTION Olaparib is a PARP inhibitor.'], indications_and_usage: ['1 INDICATIONS AND USAGE Lynparza is indicated for ovarian cancer.'], openfda: { spl_set_id: ['abc'], brand_name: ['Lynparza'] } }] }
      : { results: [{ application_number: 'NDA208558', sponsor_name: 'ASTRAZENECA' }, { application_number: 'ANDA210001', sponsor_name: 'NATCO' }, { application_number: 'ANDA210002', sponsor_name: 'SUN PHARMA' }] }
    const facts = await fetchLabelFacts('olaparib', fake)
    expect(facts.SUMMARY?.text).toBe('Olaparib is a PARP inhibitor. Lynparza is indicated for ovarian cancer.')
    expect(facts.WHAT_IT_IS?.url).toContain('setid=abc')
    expect(facts.MECHANISM).toBeUndefined()
    expect(facts.SVAK_RELEVANCE?.text).toMatch(/^1 NDA holder \(ASTRAZENECA\); 2 generic \(ANDA\) holders/)
  })
})
