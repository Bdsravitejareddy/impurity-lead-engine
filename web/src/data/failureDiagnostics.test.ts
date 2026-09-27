import { describe, expect, it } from 'vitest'
import { describeFailure, getCandidateFailures, getPipelineFailures } from './failureDiagnostics'

describe('failure diagnostics', () => {
  it('turns a transport code into a plain-language explanation and next step', () => {
    expect(describeFailure('company_site_transport')).toEqual({
      title: 'Company website could not be reached',
      explanation: 'The company website did not respond or blocked the request, so no evidence was collected from it.',
      action: 'Check the website URL or retry the run later.',
    })
  })

  it('collects failed pipeline stages with their readable reasons', () => {
    const failures = getPipelineFailures({
      crawler: { status: 'FAILED', errors: ['company_site_transport'] },
      contactResearch: { status: 'COMPLETED' },
      targetedResearch: { status: 'FAILED', stop_reason: 'europe_pmc_no_match' },
    })

    expect(failures).toEqual([
      expect.objectContaining({ stage: 'Crawler', code: 'company_site_transport', title: 'Company website could not be reached' }),
      expect.objectContaining({ stage: 'Targeted research', code: 'europe_pmc_no_match', title: 'No matching research result was found' }),
    ])
  })

  it('summarizes candidate-level failures without treating a clean result as an error', () => {
    expect(getCandidateFailures([
      { status: 'failed', dominant_failure: 'company_site_transport' },
      { status: 'complete', dominant_failure: 'none; public FDA quality assessment' },
      { status: 'failed', dominant_failure: 'company_site_transport' },
    ])).toEqual([{ code: 'company_site_transport', count: 2, title: 'Company website could not be reached' }])
  })
})
