// Molecule facts from the FDA drug label (openFDA), for molecule pages whose
// researched sections are still empty. Free, keyless and browser-callable.
// Every section keeps its source: the label on DailyMed, or the FDA approvals
// list. Nothing is invented; a field the label lacks stays empty.

export type LabelSection = { text: string; source: string; url: string }
export type LabelFacts = Partial<Record<'SUMMARY' | 'WHAT_IT_IS' | 'CLINICAL_USE' | 'MECHANISM' | 'CLINICAL_SAFETY' | 'TOX_HAZARD' | 'SVAK_RELEVANCE', LabelSection>>

type Fetch = (url: string) => Promise<any>

const HEADING = /^(?:[\d.]+\s+)?(?:DESCRIPTION|INDICATIONS\s*(?:AND|&)\s*USAGE|MECHANISM OF ACTION|CLINICAL PHARMACOLOGY|WARNINGS AND PRECAUTIONS|WARNINGS|PRECAUTIONS|ADVERSE REACTIONS|BOXED WARNING|NONCLINICAL TOXICOLOGY|Carcinogenesis,\s*Mutagenesis,?\s*(?:and\s*)?Impairment of Fertility|Mechanism of Action)\b[:.]?\s*/i

/** Label text without its section number and heading, cut at a sentence near ``limit``. */
export function labelText(value: unknown, limit = 420): string {
  const raw = Array.isArray(value) ? String(value[0] || '') : String(value || '')
  let text = raw.replace(/\s+/g, ' ').trim()
  // Drop the section number and heading, repeatedly: '13 NONCLINICAL TOXICOLOGY 13.1 Carcinogenesis, ...'
  for (let i = 0; i < 4; i++) {
    const next = text.replace(HEADING, '').trim()
    if (next === text) break
    text = next
  }
  if (text.length <= limit) return text
  const cut = text.slice(0, limit)
  const end = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('; '))
  return (end > limit * 0.5 ? cut.slice(0, end + 1) : cut.trimEnd() + '…')
}

const firstSentence = (text: string) => (text.match(/^.*?[.;](?=\s|$)/)?.[0] || text).trim()

export async function fetchLabelFacts(molecule: string, fetchJson: Fetch = url => fetch(url).then(r => r.ok ? r.json() : { results: [] })): Promise<LabelFacts> {
  const name = molecule.trim().toUpperCase().replace(/"/g, '')
  if (!name) return {}
  const term = encodeURIComponent(`"${name}"`)
  const [labels, approvals] = await Promise.all([
    fetchJson(`https://api.fda.gov/drug/label.json?search=openfda.generic_name:${term}&limit=1`).catch(() => ({ results: [] })),
    fetchJson(`https://api.fda.gov/drug/drugsfda.json?search=products.active_ingredients.name:${term}&limit=100`).catch(() => ({ results: [] })),
  ])
  const facts: LabelFacts = {}
  const label = labels.results?.[0]
  if (label) {
    const setId = label.openfda?.spl_set_id?.[0]
    const url = setId ? `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=${setId}` : 'https://open.fda.gov/apis/drug/label/'
    const source = `FDA drug label${label.openfda?.brand_name?.[0] ? ` (${label.openfda.brand_name[0]})` : ''}`
    const put = (key: keyof LabelFacts, value: unknown, limit?: number) => { const text = labelText(value, limit); if (text) facts[key] = { text, source, url } }
    put('WHAT_IT_IS', label.description)
    put('CLINICAL_USE', label.indications_and_usage)
    put('MECHANISM', label.mechanism_of_action || label.clinical_pharmacology)
    put('CLINICAL_SAFETY', label.boxed_warning || label.warnings_and_cautions || label.warnings || label.precautions || label.adverse_reactions)
    put('TOX_HAZARD', label.carcinogenesis_and_mutagenesis_and_impairment_of_fertility || label.nonclinical_toxicology)
    const what = facts.WHAT_IT_IS ? firstSentence(facts.WHAT_IT_IS.text) : ''
    const use = facts.CLINICAL_USE ? firstSentence(facts.CLINICAL_USE.text) : ''
    if (what || use) facts.SUMMARY = { text: [what, use].filter(Boolean).join(' '), source, url }
  }
  const rows = approvals.results || []
  if (rows.length) {
    const holders = (prefix: string) => Array.from(new Set(rows.filter((r: any) => String(r.application_number || '').startsWith(prefix)).map((r: any) => String(r.sponsor_name)))) as string[]
    const brand = holders('NDA'), generic = holders('ANDA')
    const parts = []
    if (brand.length) parts.push(`${brand.length} NDA holder${brand.length > 1 ? 's' : ''} (${brand.slice(0, 3).join(', ')}${brand.length > 3 ? '…' : ''})`)
    if (generic.length) parts.push(`${generic.length} generic (ANDA) holder${generic.length > 1 ? 's' : ''}`)
    const why = generic.length
      ? 'Each generic maker needs impurity reference standards to file and maintain its ANDA, so the generic holders are the widest buyer pool.'
      : 'No generic approvals yet: demand comes from the originator and from generic developers preparing filings.'
    facts.SVAK_RELEVANCE = { text: `${parts.join('; ')} in the US. ${why}`, source: 'FDA approvals (Drugs@FDA)', url: `https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=BasicSearch.process&searchterm=${encodeURIComponent(molecule)}` }
  }
  return facts
}
