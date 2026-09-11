import { describe, expect, it } from 'vitest'
import { buildCanonicalContacts, groupEvidenceBySource } from './integrity'

describe('canonical contact read model', () => {
  it('returns one row per contact id and counts explicit opportunity links', () => {
    const rows = buildCanonicalContacts(
      [
        { id: 'c1', display_name: 'Jitendra Singh', title: 'Quality', company_id: 'co1', contact_confidence: 0.8, last_verified_at: '2026-09-01' },
        { id: 'c2', display_name: 'Asha Rao', title: 'QC', company_id: 'co1', contact_confidence: 0.7, last_verified_at: null },
      ],
      [{ contact_id: 'c1', opportunity_id: 'o1' }, { contact_id: 'c1', opportunity_id: 'o2' }],
      [{ contact_id: 'c1', source_url: 'https://example.com/a' }, { contact_id: 'c1', source_url: 'https://example.com/a' }],
      new Map([['co1', 'Acme']]),
    )
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ id: 'c1', company: 'Acme', linked_opportunities: 2, sources: 1 })
  })

  it('uses persisted quality diagnostics for canonical contact quality', () => {
    const [row] = buildCanonicalContacts([{ id: 'c1', display_name: 'A', company_id: 'co1', quality_diagnostics: { score: 61.1, dimensions: { current_role: 20 } } }], [], [], new Map([['co1', 'Acme']]))
    expect(row.quality).toBe(61.1)
    expect(row.current_role_confidence).toBe(0.2)
  })
})

describe('evidence read model', () => {
  it('groups repeated signals into one canonical source card', () => {
    const grouped = groupEvidenceBySource([
      { url: 'https://example.com/paper', title: 'Paper', signal_types: ['impurity'] },
      { url: 'https://example.com/paper', title: 'Paper', signal_types: ['degradation'] },
      { url: 'https://example.com/other', title: 'Other', signal_types: ['stability'] },
    ])
    expect(grouped).toHaveLength(2)
    expect(grouped[0].signal_types).toEqual(['impurity', 'degradation'])
  })
})
