import { supabase } from './supabase'

export const PIPELINE_STAGES = ['NEW', 'REVIEWED', 'OUTREACH READY', 'CONTACTED', 'REPLIED', 'MEETING', 'RFQ', 'WON', 'LOST'] as const
export type PipelineSource = 'database' | 'browser'

// Stages used to be kept only in this browser under this key, keyed by
// company + molecule with no separator.
const LEGACY_KEY = 'svak.workflow'

const norm = (value: unknown) => String(value ?? '').trim().toLowerCase().replace(/\s+/g, ' ')

export function pipelineKey(company: unknown, molecule: unknown) {
  return `${norm(company)}|${norm(molecule)}`
}

function readLegacy(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(LEGACY_KEY) || '{}') } catch { return {} }
}

function writeLegacy(states: Record<string, string>) {
  try { localStorage.setItem(LEGACY_KEY, JSON.stringify(states)) } catch { /* storage may be unavailable */ }
}

/** Database stages win; a stage saved only in this browser fills the gaps. */
export function resolveStates(leads: { account: { company: string }; opportunity: { molecule: string } }[], rows: { pipeline_key: string; stage: string }[], legacy: Record<string, string>) {
  const states: Record<string, string> = {}
  rows.forEach(row => { states[row.pipeline_key] = row.stage })
  const browserOnly: { key: string; company: string; molecule: string; stage: string }[] = []
  leads.forEach(lead => {
    const key = pipelineKey(lead.account.company, lead.opportunity.molecule)
    const legacyStage = legacy[key] || legacy[lead.account.company + lead.opportunity.molecule]
    if (!states[key] && legacyStage && (PIPELINE_STAGES as readonly string[]).includes(legacyStage)) {
      states[key] = legacyStage
      browserOnly.push({ key, company: lead.account.company, molecule: lead.opportunity.molecule, stage: legacyStage })
    }
  })
  return { states, browserOnly }
}

export async function loadPipelineStates(leads: Parameters<typeof resolveStates>[0], { canWrite }: { canWrite: boolean }) {
  const legacy = readLegacy()
  if (!supabase) return { states: resolveStates(leads, [], legacy).states, source: 'browser' as PipelineSource }
  const { data, error } = await supabase.from('opportunity_pipeline').select('pipeline_key,stage').range(0, 9999)
  if (error) return { states: resolveStates(leads, [], legacy).states, source: 'browser' as PipelineSource }
  const { states, browserOnly } = resolveStates(leads, data ?? [], legacy)
  // Carry stages saved before the shared pipeline existed into the database once.
  if (canWrite && browserOnly.length) {
    await supabase.from('opportunity_pipeline').upsert(browserOnly.map(item => ({ pipeline_key: item.key, company_name: item.company, molecule_name: item.molecule, stage: item.stage })), { onConflict: 'pipeline_key' })
  }
  return { states, source: 'database' as PipelineSource }
}

export async function savePipelineStage(company: string, molecule: string, stage: string): Promise<PipelineSource> {
  const key = pipelineKey(company, molecule)
  writeLegacy({ ...readLegacy(), [key]: stage })
  if (!supabase) return 'browser'
  const { error } = await supabase.from('opportunity_pipeline').upsert({ pipeline_key: key, company_name: company, molecule_name: molecule, stage }, { onConflict: 'pipeline_key' })
  return error ? 'browser' : 'database'
}
