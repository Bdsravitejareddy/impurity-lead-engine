// "Find buyers for a compound": who makes or works on a drug, and who to contact.
// Runs in the browser against free public APIs that allow it (openFDA and
// Europe PMC both send Access-Control-Allow-Origin: *), merged with the
// companies and contacts already in the database. No key, no cost.

export type BuyerReason = { kind: 'fda_application' | 'ndc_labeler' | 'publication'; label: string; date?: string | null; url?: string }
export type PaperPerson = { name: string; affiliation: string; email: string | null; paper: string; date: string | null; url: string }
export type BuyerCompany = { key: string; name: string; reasons: BuyerReason[]; people: PaperPerson[]; latest: string | null }

type Fetch = (url: string) => Promise<any>

const SUFFIXES = /\b(inc|incorporated|llc|ltd|limited|pvt|private|corp|corporation|co|company|plc|gmbh|ag|sa|spa|bv|usa|us|america|holdings|group|pharmaceuticals?|pharma|laboratories|labs?|healthcare|lifesciences|life sciences)\b/g

/** 'Dr. Reddy's Laboratories Limited' and 'DR REDDYS LABS LTD' -> 'dr reddys'. */
export function companyKey(name: string): string {
  return name.toLowerCase().replace(/&/g, ' and ').replace(/['’.]/g, '').replace(/[^a-z0-9 ]/g, ' ')
    .replace(SUFFIXES, ' ').replace(/\s+/g, ' ').trim()
}

const COMPANY = /\b(ltd|limited|pvt|inc|llc|gmbh|ag|s\.?a\.?|s\.?p\.?a\.?|corp|corporation|laborator(?:y|ies)|labs|pharmaceuticals?|pharma|biotech|therapeutics|lifesciences|healthcare)\b/i
const ACADEMIC = /universit|college|school|institut|hospital|klinik|academy|faculty|centre for|center for|council|ministry|national|deemed|polytechnic|key laboratory/i
const SUFFIX_ONLY = /^(ltd|limited|pvt\.? ltd|inc|llc|gmbh|ag|s\.?a|corp|co)\.?$/i
const EMAIL = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi

/** The company named in an author affiliation, or null for academic and hospital authors. */
export function companyFromAffiliation(affiliation: string): string | null {
  if (!affiliation || ACADEMIC.test(affiliation)) return null
  const segments = affiliation.split(',').map(part => part.trim().replace(/^[.\s]+|[.\s]+$/g, ''))
  for (let index = 0; index < segments.length; index++) {
    const segment = segments[index]
    if (!segment || segment.includes('@')) continue
    if (SUFFIX_ONLY.test(segment) && index > 0) return `${segments[index - 1]} ${segment}`
    if (COMPANY.test(segment) && !/\b(department|division|r&d|analytical|quality|development|unit)\b/i.test(segment.split(' ').slice(0, 2).join(' '))) return segment
  }
  return null
}

/** An address in the affiliation that carries the author's own name. */
function personalEmail(affiliation: string, name: string): string | null {
  const words = name.toLowerCase().replace(/[^a-z ]/g, ' ').split(/\s+/).filter(word => word.length >= 3)
  return (affiliation.match(EMAIL) || []).map(value => value.replace(/\.$/, '').toLowerCase())
    .find(value => words.some(word => value.split('@')[0].includes(word))) || null
}

const IMPURITY_TERMS = ['impurity', 'impurities', 'degradation products', 'degradants', 'forced degradation', 'nitrosamine', 'NDSRI', 'genotoxic', 'related substances', 'stability-indicating']
const fdaDate = (value?: string) => value && /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : null
const quoted = (value: string) => `"${value.replace(/"/g, '')}"`

export async function findBuyers(compound: string, fetchJson: Fetch = url => fetch(url).then(r => r.ok ? r.json() : { results: [] })): Promise<BuyerCompany[]> {
  const name = compound.trim()
  if (!name) return []
  const companies = new Map<string, BuyerCompany>()
  const add = (rawName: string, reason: BuyerReason | null, person?: PaperPerson) => {
    const key = companyKey(rawName)
    if (!key) return
    const company = companies.get(key) || { key, name: rawName, reasons: [], people: [], latest: null }
    if (reason && !company.reasons.some(item => item.label === reason.label)) company.reasons.push(reason)
    if (person && !company.people.some(item => item.name === person.name)) company.people.push(person)
    const date = reason?.date || person?.date || null
    if (date && (!company.latest || date > company.latest)) company.latest = date
    companies.set(key, company)
  }

  const term = encodeURIComponent(quoted(name.toUpperCase()))
  const [applications, labelers, papers] = await Promise.all([
    fetchJson(`https://api.fda.gov/drug/drugsfda.json?search=products.active_ingredients.name:${term}&limit=100`).catch(() => ({ results: [] })),
    fetchJson(`https://api.fda.gov/drug/ndc.json?search=generic_name:${term}&limit=100`).catch(() => ({ results: [] })),
    fetchJson(`https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=${encodeURIComponent(
      `TITLE_ABS:${quoted(name)} AND (${IMPURITY_TERMS.map(t => `TITLE_ABS:${quoted(t)}`).join(' OR ')})`)}&format=json&resultType=core&pageSize=50`).catch(() => ({})),
  ])

  for (const row of applications.results || []) {
    if (!row.sponsor_name) continue
    const dates = (row.submissions || []).map((s: any) => fdaDate(s.submission_status_date)).filter(Boolean).sort()
    const number = String(row.application_number || '')
    add(row.sponsor_name, {
      kind: 'fda_application', label: `FDA ${number.replace(/^(ANDA|NDA|BLA)/, '$1 ')}`.trim(), date: dates[dates.length - 1] || null,
      url: `https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=${number.replace(/\D/g, '')}`,
    })
  }
  for (const row of labelers.results || []) {
    if (!row.labeler_name) continue
    add(row.labeler_name, { kind: 'ndc_labeler', label: `Markets ${row.brand_name || row.generic_name} in the US (NDC ${row.product_ndc})`, date: null })
  }
  for (const item of papers.resultList?.result || []) {
    const id = item.pmid || item.id
    const url = `https://europepmc.org/article/${item.pmid ? 'MED' : item.source || 'MED'}/${id}`
    for (const author of item.authorList?.author || []) {
      const affiliations = (author.authorAffiliationDetailsList?.authorAffiliation || []).map((a: any) => String(a.affiliation || ''))
      for (const affiliation of affiliations) {
        const company = companyFromAffiliation(affiliation)
        if (!company) continue
        const personName = String(author.firstName && author.lastName ? `${author.firstName} ${author.lastName}` : author.fullName || '')
        add(company, { kind: 'publication', label: `Published on ${name} impurities`, date: item.firstPublicationDate, url }, {
          name: personName, affiliation: affiliation.slice(0, 200), email: personalEmail(affiliation, personName),
          paper: String(item.title || '').slice(0, 200), date: item.firstPublicationDate || null, url,
        })
        break
      }
    }
  }
  // Impurity papers first (direct evidence and named people), then the newest activity.
  const weight = (company: BuyerCompany) => (company.people.length ? 2 : 0) + (company.reasons.some(r => r.kind === 'fda_application') ? 1 : 0)
  return Array.from(companies.values()).sort((a, b) => weight(b) - weight(a) || String(b.latest || '').localeCompare(String(a.latest || '')))
}
