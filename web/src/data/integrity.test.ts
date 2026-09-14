import { describe, expect, it } from 'vitest'
import { buildCanonicalContacts, formatQuality, formatRoleConfidence, groupEvidenceBySource, rankContactsForOpportunity, readCurrentRoleConfidence, summarizeWorkState } from './integrity'

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
    expect(rows[0].quality).toBeNull()
    expect(rows[0].current_role_confidence).toBeNull()
  })

  it('uses persisted quality diagnostics for canonical contact quality', () => {
    const [row] = buildCanonicalContacts([{ id: 'c1', display_name: 'A', company_id: 'co1', quality_diagnostics: { score: 61.1, dimensions: { current_role: 20 } } }], [], [], new Map([['co1', 'Acme']]))
    expect(row.quality).toBe(61.1)
    expect(row.current_role_confidence).toBe(0.2)
  })

  it('does not count rejected source rows or use identity as a quality fallback', () => {
    const [row] = buildCanonicalContacts([{ id: 'c1', display_name: 'A', company_id: 'co1', contact_confidence: 0.94 }], [], [
      { contact_id: 'c1', url: 'https://example.test/accepted', status: 'USED' },
      { contact_id: 'c1', url: 'https://example.test/rejected', status: 'REJECTED' },
    ], new Map([['co1', 'Acme']]))
    expect(row.sources).toBe(1)
    expect(row.quality).toBeNull()
    expect(row.current_role_confidence).toBeNull()
  })

  it('ranks explicitly linked contacts by qualification and evidence', () => {
    const ranked = rankContactsForOpportunity([
      { id: 'weak', quality: 85, identity_confidence: 0.6, technical_relevance: 90, contactability: 'VERIFIED_PUBLIC' },
      { id: 'strong', quality: 78, identity_confidence: 0.9, technical_relevance: 80, contactability: 'ROLE_ONLY' },
    ])
    expect(ranked[0].id).toBe('strong')
  })

  it('summarizes applied Work jobs instead of exposing the latest pending row', () => {
    const summary = summarizeWorkState([{ status: 'APPLIED' }, { status: 'APPLIED' }], [{ validation_status: 'VALID' }])
    expect(summary).toMatchObject({ status: 'APPLIED', applied: 2, pending: 0 })
  })

  it('formats missing score inputs without inventing zeros', () => {
    expect(formatQuality(null)).toBe('Not scored')
    expect(formatRoleConfidence(null)).toBe('Not established')
    expect(formatQuality(0)).toBe('0')
  })

  it('shows role confidence as unestablished when diagnostics say evidence is missing', () => {
    expect(readCurrentRoleConfidence({ quality_diagnostics: { dimensions: { current_role: 62 }, diagnostics: { current_role: 'Current role evidence is missing' } } })).toBeNull()
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
