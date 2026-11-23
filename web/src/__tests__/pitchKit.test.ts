import { describe, expect, it } from 'vitest'
import { buildPitchKit } from '../lib/pitchKit'

const now = new Date('2026-11-23T00:00:00Z')

describe('pitch kit', () => {
  it('leads with a recent impurity recall and quotes its reason', () => {
    const kit = buildPitchKit('Hikma', 'Ciprofloxacin', [
      { signal_type: 'regulatory_application', event_date: '2025-01-10', source_type: 'regulatory' },
      { signal_type: 'impurity_recall', event_date: '2026-10-20', source_type: 'recall',
        evidence_text: 'FDA recall D-0166-2027: Ciprofloxacin Tablets. Reason: CGMP Deviations: N-nitroso-ciprofloxacin results above the FDA recommended interim control limit.' },
    ], now)
    expect(kit.lead_signal).toBe('impurity_recall')
    expect(kit.personalization_hook).toBe("The October 2026 FDA recall of Hikma's Ciprofloxacin cited: N-nitroso-ciprofloxacin results above the FDA recommended interim control limit.")
    expect(kit.why_now).toContain('34 days ago')
    expect(kit.value_hypothesis).toMatch(/root cause/)
  })

  it('ranks impurity evidence above filing context and dates the hook', () => {
    const kit = buildPitchKit('Cipla', 'Ledipasvir', [
      { signal_type: 'phase_iii', event_date: '2026-02-01', source_type: 'trial' },
      { signal_type: 'degradation_product', event_date: '2024-03-02', source_type: 'publication' },
    ], now)
    expect(kit.lead_signal).toBe('degradation_product')
    expect(kit.personalization_hook).toBe("Cipla's Ledipasvir shows degradation product work (publication, March 2024).")
    expect(kit.why_now).toContain('within the last year')
  })

  it('says no trigger is established when evidence is old or missing', () => {
    expect(buildPitchKit('Bayer', 'Darolutamide', [{ signal_type: 'stability', event_date: '2021-02-01', source_type: 'patent' }], now).why_now)
      .toContain('no current trigger')
    const empty = buildPitchKit('Bayer', 'Darolutamide', [], now)
    expect(empty.lead_signal).toBeNull()
    expect(empty.why_now).toBeNull()
    expect(empty.discovery_question).toContain('Darolutamide')
  })
})
