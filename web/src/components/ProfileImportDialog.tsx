import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { extractPdfText, extractProfessionalProfile, type ProfileExtraction } from '../data/contactIntelligence'

type Props = {
  contactName: string
  onClose: () => void
  onSave: (payload: { name: string; raw: string; url: string; kind: string; filename?: string; profile: ProfileExtraction; research: boolean }) => Promise<void>
}
type Position = ProfileExtraction['positions'][number]
type Education = ProfileExtraction['education'][number]
type Work = ProfileExtraction['works'][number]

const emptyProfile = (name: string): ProfileExtraction => ({
  claims: name ? [`Profile name: ${name}`] : [], currentTitle: '', headline: '', currentCompany: '', location: '', about: '', skills: [], certifications: [], activities: [], positions: [], education: [], themes: [], keywords: name ? [name] : [], works: []
})

export default function ProfileImportDialog({ contactName, onClose, onSave }: Props) {
  const [tab, setTab] = useState<'PDF' | 'TEXT' | 'FORM'>('PDF')
  const [url, setUrl] = useState('')
  const [raw, setRaw] = useState('')
  const [filename, setFilename] = useState('')
  const [fullName, setFullName] = useState(contactName)
  const [profile, setProfile] = useState<ProfileExtraction>(() => emptyProfile(contactName))
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState('')
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    dialogRef.current?.focus()
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', handleKey) }
  }, [onClose])

  const parse = (text: string, file = '') => {
    const extracted = extractProfessionalProfile(text, fullName || contactName)
    setRaw(text); setFilename(file); setProfile(extracted); setError(''); setTab('FORM')
  }
  const chooseFile = () => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown'
    input.onchange = () => {
      const selected = input.files?.[0]; if (!selected) return
      setParsing(true)
      const reader = new FileReader()
      reader.onload = () => { const content = selected.type === 'application/pdf' ? extractPdfText(reader.result as ArrayBuffer) : String(reader.result || ''); parse(content, selected.name); setParsing(false) }
      reader.onerror = () => { setError('The selected file could not be read.'); setParsing(false) }
      selected.type === 'application/pdf' ? reader.readAsArrayBuffer(selected) : reader.readAsText(selected)
    }
    input.click()
  }
  const update = (patch: Partial<ProfileExtraction>) => setProfile(current => ({ ...current, ...patch }))
  const updatePosition = (index: number, patch: Partial<Position>) => update({ positions: profile.positions.map((item, i) => i === index ? { ...item, ...patch } : item) })
  const updateEducation = (index: number, patch: Partial<Education>) => update({ education: profile.education.map((item, i) => i === index ? { ...item, ...patch } : item) })
  const updateWork = (index: number, patch: Partial<Work>) => update({ works: profile.works.map((item, i) => i === index ? { ...item, ...patch } : item) })
  const addPosition = () => update({ positions: [...profile.positions, { title: '', company_name: '', department: '', start_date: '', end_date: '', attribution: 'PERSON_DIRECT', confidence: 0.85 }] })
  const addEducation = () => update({ education: [...profile.education, { institution: '', degree: '', field: '', start_date: '', end_date: '', confidence: 0.75 }] })
  const addWork = (type = 'PROJECT') => update({ works: [...profile.works, { title: '', work_type: type, topic: '', work_date: '', url: '', attribution: 'PERSON_DIRECT', confidence: 0.7 }] })
  const removeAt = <T,>(items: T[], index: number) => items.filter((_, i) => i !== index)
  const submit = async (research: boolean) => {
    if (!profile.currentTitle && !profile.currentCompany && !profile.about && !profile.positions.length && !profile.education.length && !profile.works.length) { setError('Add profile text or at least one structured professional field.'); return }
    setParsing(true); setError('')
    try { await onSave({ name: fullName || contactName, raw, url, kind: 'PROFESSIONAL_PROFILE', filename, profile, research }) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save profile.') } finally { setParsing(false) }
  }
  const summary = useMemo(() => `${profile.positions.length} positions · ${profile.education.length} education records · ${profile.works.length} works · ${(profile.certifications || []).length} certifications`, [profile])

  return createPortal(<div className="source-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="profile-import-title">
    <div className="profile-import-modal" ref={dialogRef} tabIndex={-1}>
      <div className="profile-import-header">
        <div className="panelhead"><div><span className="eyebrow">CONTACT 360 / PROFILE INGESTION</span><h2 id="profile-import-title">Import professional profile</h2><p className="muted">Supply the profile once. PDF, pasted text and manual entries use the same normalized intelligence model.</p></div><button className="icon" onClick={onClose} aria-label="Close profile import">×</button></div>
        <div className="profile-import-tabs" role="tablist">{([['PDF','Upload LinkedIn PDF'],['TEXT','Paste LinkedIn Text'],['FORM','Fill Profile']] as const).map(([value,label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{label}</button>)}</div>
      </div>
      <div className="profile-import-body">
        {tab === 'PDF' && <section className="import-pane"><div className="upload-drop" onClick={chooseFile}><strong>{parsing ? 'Reading profile…' : 'Drop a LinkedIn profile PDF here'}</strong><span>or choose a PDF, TXT, Markdown or profile export</span><button type="button" className="refresh">Choose file</button></div><label>Optional LinkedIn/profile URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.linkedin.com/in/…" /></label><p className="muted">The supplied PDF is useful even when LinkedIn itself requires authentication.</p></section>}
        {tab === 'TEXT' && <section className="import-pane"><label>Optional LinkedIn/profile URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.linkedin.com/in/…" /></label><label>Paste the complete visible professional profile<textarea rows={16} value={raw} onChange={e => setRaw(e.target.value)} placeholder="Name\nHeadline\nAbout\nExperience\nEducation\nCertifications\nProjects\nPublications\nSkills\nActivity…" /></label><button className="refresh" onClick={() => parse(raw)} disabled={!raw.trim()}>Parse profile</button></section>}
        {tab === 'FORM' && <section className="import-pane profile-form"><div className="form-section form-section-first"><h3>Identity</h3><div className="form-grid"><label>Full name<input value={fullName} onChange={e => setFullName(e.target.value)} /></label><label>Professional headline<input value={profile.headline || ''} onChange={e => update({ headline: e.target.value })} /></label><label>Current job title<input value={profile.currentTitle || ''} onChange={e => update({ currentTitle: e.target.value })} /></label><label>Current company<input value={profile.currentCompany || ''} onChange={e => update({ currentCompany: e.target.value })} /></label><label>Business location<input value={profile.location || ''} onChange={e => update({ location: e.target.value })} /></label><label>LinkedIn/profile URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" /></label></div><label>Professional summary / About<textarea rows={5} value={profile.about || ''} onChange={e => update({ about: e.target.value })} /></label></div>
          <div className="form-section"><div className="section-heading"><h3>Experience</h3><button className="refresh" onClick={addPosition}>+ Add position</button></div>{profile.positions.map((position, i) => <div className="repeat-card" key={i}><div className="repeat-grid"><label>Job title<input aria-label="Job title" placeholder="Job title" value={position.title} onChange={e => updatePosition(i, { title: e.target.value })} /></label><label>Company<input aria-label="Company" placeholder="Company" value={position.company_name || ''} onChange={e => updatePosition(i, { company_name: e.target.value })} /></label><label>Start<input aria-label="Start year" placeholder="YYYY" value={position.start_date || ''} onChange={e => updatePosition(i, { start_date: e.target.value })} /></label><label>End / Present<input aria-label="End / Present" placeholder="YYYY or Present" value={position.end_date || ''} onChange={e => updatePosition(i, { end_date: e.target.value })} /></label></div><button className="icon repeat-remove" onClick={() => update({ positions: removeAt(profile.positions, i) })} aria-label="Remove position">×</button></div>)}</div>
          <div className="form-section"><div className="section-heading"><h3>Education</h3><button className="refresh" onClick={addEducation}>+ Add education</button></div>{profile.education.map((education, i) => <div className="repeat-card" key={i}><div className="repeat-grid education-grid"><label>Institution<input aria-label="Institution" placeholder="Institution" value={education.institution} onChange={e => updateEducation(i, { institution: e.target.value })} /></label><label>Degree / qualification<input aria-label="Degree" placeholder="Degree / qualification" value={education.degree || ''} onChange={e => updateEducation(i, { degree: e.target.value })} />{education.review_suggested && <span className="review-warning">REVIEW SUGGESTED · extracted text looks corrupted</span>}</label><label>Field of study<input aria-label="Field" placeholder="Field" value={education.field || ''} onChange={e => updateEducation(i, { field: e.target.value })} /></label></div><button className="icon repeat-remove" onClick={() => update({ education: removeAt(profile.education, i) })} aria-label="Remove education">×</button></div>)}</div>
          <div className="form-section"><div className="section-heading"><h3>Projects, publications &amp; patents</h3><div className="compact-actions"><button className="refresh" onClick={() => addWork('PROJECT')}>+ Project</button><button className="refresh" onClick={() => addWork('PUBLICATION')}>+ Publication</button><button className="refresh" onClick={() => addWork('PATENT')}>+ Patent</button></div></div>{profile.works.map((work, i) => <div className="repeat-card" key={i}><div className="repeat-grid work-grid"><label>Title<input aria-label="Work title" placeholder="Title" value={work.title} onChange={e => updateWork(i, { title: e.target.value })} /></label><label>Type<select aria-label="Work type" value={work.work_type} onChange={e => updateWork(i, { work_type: e.target.value })}><option>PROJECT</option><option>PUBLICATION</option><option>PATENT</option><option>PROFESSIONAL_ACTIVITY</option></select></label><label>Date<input aria-label="Work date" placeholder="YYYY-MM-DD" value={work.work_date || ''} onChange={e => updateWork(i, { work_date: e.target.value })} /></label><label>URL<input aria-label="Work URL" placeholder="https://…" value={work.url || ''} onChange={e => updateWork(i, { url: e.target.value })} /></label></div><button className="icon repeat-remove" onClick={() => update({ works: removeAt(profile.works, i) })} aria-label="Remove work">×</button></div>)}</div>
          <div className="form-section"><h3>Skills &amp; certifications</h3><label>Explicit professional skills<input value={(profile.skills || []).join(', ')} onChange={e => update({ skills: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })} placeholder="Analytical development, CMC, quality…" /><span className="field-help">Only explicitly supplied professional skills are stored.</span></label><label>Certifications<textarea rows={4} value={(profile.certifications || []).map(x => x.name).join('\n')} onChange={e => update({ certifications: e.target.value.split('\n').map(name => name.trim()).filter(Boolean).map(name => ({ name, confidence: 0.7 })) })} placeholder="One certification per line" /></label></div>
          <p className="muted parser-summary">{summary}. Parser output remains user-reviewable before saving.</p></section>}
        {error && <div className="crawl-message" role="alert">{error}</div>}
      </div>
      <div className="profile-import-footer"><span className="muted">{summary}</span><div className="source-modal-actions"><button className="refresh" onClick={() => submit(false)} disabled={parsing}>Save profile only</button><button className="primary" onClick={() => submit(true)} disabled={parsing}>{parsing ? 'Saving…' : 'Save & research'}</button></div></div>
    </div>
  </div>, document.body)
}
