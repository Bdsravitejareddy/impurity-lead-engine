import type { ProfileExtraction } from './contactIntelligence'

export type ProfileRows = {
  positions: any[]
  education: any[]
  works: any[]
  claims: any[]
  themes: any[]
}

export function normalizeProfileRows(profile: ProfileExtraction, contactId: string, sourceId: string, safeDate: (value: unknown) => string | null): ProfileRows {
  const claims = [...(profile.claims || [])]
  if (profile.headline) claims.push(`Professional headline: ${profile.headline}`)
  if (profile.about) claims.push(`Professional summary: ${profile.about}`)
  if (profile.currentTitle) claims.push(`Current title: ${profile.currentTitle}`)
  if (profile.currentCompany) claims.push(`Current company: ${profile.currentCompany}`)
  if (profile.location) claims.push(`Professional location: ${profile.location}`)
  if (profile.skills?.length) claims.push(`Explicit skills: ${profile.skills.join(', ')}`)
  if (profile.certifications?.length) claims.push(`Certifications supplied: ${profile.certifications.map(x => x.name).join(', ')}`)
  const positions = (profile.positions || []).filter(x => x.title || x.company_name).map(x => ({ contact_id: contactId, company_name: x.company_name || null, title: x.title, department: x.department || null, start_date: safeDate(x.start_date), end_date: safeDate(x.end_date), attribution: x.attribution || 'PERSON_DIRECT', confidence: Number(x.confidence || 0.5), source_ids: [sourceId] }))
  const education = (profile.education || []).filter(x => x.institution && !x.review_suggested).map(x => ({ contact_id: contactId, institution: x.institution, degree: x.degree || null, field: x.field || null, start_date: safeDate(x.start_date), end_date: safeDate(x.end_date), confidence: Number(x.confidence || 0.5), source_ids: [sourceId] }))
  const allWorks = [...(profile.works || []), ...(profile.activities || []), ...(profile.certifications || []).filter(x => x.name).map(x => ({ title: x.name, work_type: 'CERTIFICATION', work_date: x.issue_date, topic: x.issuer || 'Professional certification', attribution: 'PERSON_DIRECT', confidence: x.confidence || 0.7 }))]
  const works = allWorks.filter(x => x.title).map(x => ({ contact_id: contactId, work_type: x.work_type || 'PROJECT', title: x.title, work_date: safeDate(x.work_date), person_role: x.person_role || null, company_context: x.company_context || null, topic: x.topic || null, molecules: Array.isArray(x.molecules) ? x.molecules : [], technical_themes: Array.isArray(x.technical_themes) ? x.technical_themes : [], problem_addressed: x.problem_addressed || null, methods: x.methods || null, contribution: x.contribution || null, attribution: x.attribution || 'PERSON_DIRECT', confidence: Number(x.confidence || 0.5), source_ids: [sourceId] }))
  const themes = (profile.themes || []).map(theme => ({ contact_id: contactId, theme, evidence_count: 1, confidence: 0.65, source_ids: [sourceId] }))
  return { claims: claims.map(claim_text => ({ contact_id: contactId, claim_type: 'SUPPLIED_PROFILE_FACT', claim_text, provenance: 'OBSERVED', confidence: 0.78, source_ids: [sourceId] })), positions, education, works, themes }
}
