// Trial comparators are stored as DRUG interventions by ClinicalTrials.gov.
// Mirrors impurity_leads.normalize.is_inactive_comparator so rows written
// before the crawler filtered them are hidden too.
const inactiveComparator = /\b(placebo|vehicle|sham|dummy)\b/i

export function isInactiveComparator(name: string | null | undefined): boolean {
  return inactiveComparator.test(String(name || ''))
}
