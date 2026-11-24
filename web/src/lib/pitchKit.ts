// Deterministic pitch kit built from a lead's stored, dated evidence.
// No model call: each signal type maps to the service it implies, and the
// newest dated record supplies the hook and the "why now".

export type PitchSignal = {
  signal_type?: string | null
  event_date?: string | null
  evidence_text?: string | null
  source_type?: string | null
  source_record_id?: string | null
}

export type PitchKit = {
  lead_signal: string | null
  personalization_hook: string
  discovery_question: string
  value_hypothesis: string
  likely_service_requirement: string
  why_now: string | null
}

type Playbook = { label: string; service: string; value: string; question: string }

// Strongest buying evidence first.
const PLAYBOOKS: [string, Playbook][] = [
  ['direct_impurity_rfq', {
    label: 'a published request for impurity material',
    service: 'Custom impurity synthesis or supply against the stated requirement',
    value: 'A quoted lead time and certificate of analysis for the requested impurity, so the requirement can be closed without in-house synthesis.',
    question: 'Is the requirement still open, and what quantity, purity and documentation do you need?',
  }],
  ['impurity_recall', {
    label: 'an FDA recall linked to an impurity result',
    service: 'Impurity identification, reference standards and method support for the investigation and new controls',
    value: 'Characterised impurity standards and a validated method for the failing impurity, to support root cause, release testing and the corrective-action file.',
    question: 'Is any impurity identification, standard or method work still open from that investigation?',
  }],
  ['nitrosamine_ndsri', {
    label: 'nitrosamine (NDSRI) work',
    service: 'NDSRI reference standards and confirmatory testing against the FDA acceptable intake limit',
    value: 'The specific N-nitroso standard and a sensitive method to confirm levels against the acceptable intake, without building synthesis in-house.',
    question: 'Do you already have the N-nitroso standard and a confirmatory method for this product, or is that still being sourced?',
  }],
  ['genotoxic_impurity', {
    label: 'genotoxic impurity (ICH M7) work',
    service: 'Mutagenic impurity standards, purge assessment support and trace-level methods',
    value: 'Standards and trace methods for the ICH M7 impurities, so control strategies can be justified with data.',
    question: 'Which mutagenic impurities still need standards or a trace-level method for your control strategy?',
  }],
  ['reference_standard', {
    label: 'reference standard requirements',
    service: 'Pharmacopeial and non-pharmacopeial impurity reference standards',
    value: 'Characterised impurity standards with full certificates, including impurities that pharmacopeias do not supply.',
    question: 'Which impurity standards for this molecule are hardest to source today?',
  }],
  ['impurity_characterization', {
    label: 'impurity characterisation work',
    service: 'Impurity isolation and structure elucidation',
    value: 'Isolation and structure confirmation of unknown peaks, with data ready for the regulatory file.',
    question: 'Are there unidentified impurities above the identification threshold that still need structure confirmation?',
  }],
  ['degradation_product', {
    label: 'degradation product work',
    service: 'Degradation impurity standards and identification',
    value: 'Standards for the known degradants and identification of new ones seen on stability.',
    question: 'Are any degradation products on stability still unidentified or without a standard?',
  }],
  ['stability', {
    label: 'stability and forced-degradation work',
    service: 'Forced-degradation studies and stability-indicating method support',
    value: 'Forced-degradation data and degradant standards to support a stability-indicating method.',
    question: 'Is your stability-indicating method fully supported with degradant standards?',
  }],
  ['method_validation', {
    label: 'analytical method development',
    service: 'Analytical method development and validation for related substances',
    value: 'Related-substances method development and validation, with the impurity standards the method needs.',
    question: 'Is there related-substances method work planned where outside capacity would help?',
  }],
  ['company_announcement', {
    label: 'a recent company announcement',
    service: 'Impurity standards and analytical support for the work the announcement starts',
    value: 'Impurity standards and methods ready for the filing, launch, site or process change the announcement describes.',
    question: 'Does the work behind this announcement need impurity standards or analytical capacity you have not lined up yet?',
  }],
  ['regulatory_application', {
    label: 'an FDA application',
    service: 'Impurity profiling and standards for the filing and post-approval changes',
    value: 'Impurity standards and profiling to support the application and later supplements, such as site or supplier changes.',
    question: 'Are any supplements or supplier changes planned for this product that will need impurity data?',
  }],
  ['phase_iii', {
    label: 'a late-stage clinical programme',
    service: 'Impurity qualification and standards ahead of the marketing application',
    value: 'Impurity standards and characterisation for the CMC section before the NDA filing.',
    question: 'Have the specified impurities for the commercial process been fully characterised and sourced as standards?',
  }],
  ['phase_ii', {
    label: 'a mid-stage clinical programme',
    service: 'Early impurity profiling and standards as the process is fixed',
    value: 'Early impurity identification and standards, so the commercial specification is set with confidence.',
    question: 'Is impurity profiling keeping pace with process changes on this programme?',
  }],
]
const ORDER = new Map(PLAYBOOKS.map(([type], index) => [type, index]))
const BY_TYPE = new Map(PLAYBOOKS)

const SOURCE_NAME: Record<string, string> = {
  recall: 'FDA enforcement report', regulatory: 'FDA record', trial: 'ClinicalTrials.gov',
  publication: 'publication', patent: 'patent', standards: 'pharmacopeial record', site: 'company website',
  news: 'company announcement',
}

const parseDate = (value?: string | null) => {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}
const monthYear = (date: Date) => date.toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const daysBetween = (from: Date, to: Date) => Math.max(0, Math.floor((to.getTime() - from.getTime()) / 86_400_000))

function recallReason(text?: string | null) {
  const match = /Reason:\s*(.+)$/i.exec(text || '')
  if (!match) return null
  return match[1].replace(/^CGMP Deviations:\s*/i, '').replace(/\.$/, '').slice(0, 140)
}

export function buildPitchKit(company: string, molecule: string, signals: PitchSignal[], now: Date = new Date()): PitchKit {
  const known = signals.filter(signal => BY_TYPE.has(String(signal.signal_type)))
  if (!known.length) {
    return {
      lead_signal: null,
      personalization_hook: `${company} has public activity on ${molecule}.`,
      discovery_question: `Are there current or upcoming impurity or analytical requirements on ${molecule} where an external partner could help?`,
      value_hypothesis: `Impurity standards and analytical support for ${molecule}.`,
      likely_service_requirement: 'Not yet established from the evidence.',
      why_now: null,
    }
  }
  const strongestType = [...known].sort((a, b) => (ORDER.get(String(a.signal_type))! - ORDER.get(String(b.signal_type))!))[0].signal_type as string
  const playbook = BY_TYPE.get(strongestType)!
  // The newest dated record of the strongest type anchors the hook.
  const anchor = known
    .filter(signal => signal.signal_type === strongestType)
    .sort((a, b) => (parseDate(b.event_date)?.getTime() ?? 0) - (parseDate(a.event_date)?.getTime() ?? 0))[0]
  const anchorDate = parseDate(anchor.event_date)
  const source = SOURCE_NAME[String(anchor.source_type)] || 'public record'
  const when = anchorDate ? ` (${source}, ${monthYear(anchorDate)})` : ` (${source})`
  let hook = `${company}'s ${molecule} shows ${playbook.label}${when}.`
  if (strongestType === 'company_announcement') {
    const headline = (anchor.evidence_text || '').split(/\.\s/)[0].trim().slice(0, 160)
    if (headline) hook = `${company} announced "${headline}"${anchorDate ? ` (${monthYear(anchorDate)})` : ''}.`
  }
  if (strongestType === 'impurity_recall') {
    const reason = recallReason(anchor.evidence_text)
    hook = `The ${anchorDate ? monthYear(anchorDate) + ' ' : ''}FDA recall of ${company}'s ${molecule}${reason ? ` cited: ${reason}` : ' cited an impurity result'}.`
  }

  const newest = known.map(signal => parseDate(signal.event_date)).filter((date): date is Date => Boolean(date)).sort((a, b) => b.getTime() - a.getTime())[0]
  let whyNow: string | null = null
  if (newest) {
    const days = daysBetween(newest, now)
    if (days <= 180) whyNow = `Newest evidence is from ${monthYear(newest)}, ${days} days ago: the work is likely active now.`
    else if (days <= 365) whyNow = `Newest evidence is from ${monthYear(newest)}, within the last year: follow-up work is likely still open.`
    else whyNow = `Newest dated evidence is from ${monthYear(newest)}; no current trigger is established, so lead with a question.`
  }
  return {
    lead_signal: strongestType,
    personalization_hook: hook,
    discovery_question: playbook.question,
    value_hypothesis: playbook.value,
    likely_service_requirement: playbook.service,
    why_now: whyNow,
  }
}
