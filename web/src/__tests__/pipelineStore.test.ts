import { describe, expect, it } from 'vitest'
import { pipelineKey, resolveStates } from '../data/pipelineStore'

const lead = (company: string, molecule: string) => ({ account: { company }, opportunity: { molecule } })

describe('shared pipeline states', () => {
  it('keys a lead by normalized company and molecule', () => {
    expect(pipelineKey('  Takeda Pharmaceuticals ', 'IXAZOMIB  CITRATE')).toBe('takeda pharmaceuticals|ixazomib citrate')
  })

  it('prefers database stages and carries browser-only stages forward once', () => {
    const leads = [lead('Takeda', 'Ixazomib'), lead('Cipla', 'Ledipasvir'), lead('Bayer', 'Darolutamide')]
    const legacy = { TakedaIxazomib: 'CONTACTED', CiplaLedipasvir: 'REPLIED', BayerDarolutamide: 'NOT A STAGE' }
    const { states, browserOnly } = resolveStates(leads, [{ pipeline_key: 'takeda|ixazomib', stage: 'MEETING' }], legacy)
    expect(states).toEqual({ 'takeda|ixazomib': 'MEETING', 'cipla|ledipasvir': 'REPLIED' })
    expect(browserOnly).toEqual([{ key: 'cipla|ledipasvir', company: 'Cipla', molecule: 'Ledipasvir', stage: 'REPLIED' }])
  })
})
