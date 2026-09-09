import React, { useMemo, useState } from 'react'
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

  const parse = (text: string, file = '') => {
    const extracted = extractProfessionalProfile(text, fullName || contactName)
    setRaw(text); setFilename(file); setProfile(extracted); setError('')
    setTab('FORM')
  }

  const chooseFile = () => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown'
    input.onchange = () => { const selected = input.files?.[0]; if (!selected) return; setParsing(true); const reader = new FileReader(); reader.onload = () => { const content = selected.type === 'application/pdf' ? extractPdfText(reader.result as ArrayBuffer) : String(reader.result || ''); parse(content, selected.name); setParsing(false) }; reader.onerror = () => { setError('The selected file could not be read.'); setParsing(false) }; selected.type === 'application/pdf' ? reader.readAsArrayBuffer(selected) : reader.readAsText(selected) }
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
  const submit = async (research: boolean) => { if (!profile.currentTitle && !profile.currentCompany && !profile.about && !profile.positions.length) { setError('Add profile text or at least one structured professional field.'); return }; setParsing(true); await onSave({ name: fullName || contactName, raw, url, kind: 'PROFESSIONAL_PROFILE', filename, profile, research }); setParsing(false) }
  const summary = useMemo(() => `${profile.positions.length} positions · ${profile.education.length} education records · ${profile.works.length} works · ${(profile.certifications || []).length} certifications`, [profile])

  return <div className="source-modal-backdrop" role="dialog" aria-modal="true"><div className="profile-import-modal">
    <div className="panelhead"><div><span className="eyebrow">CONTACT 360 / PROFILE INGESTION</span><h2>Import professional profile</h2><p className="muted">Supply the profile once. PDF, pasted text and manual entries use the same normalized intelligence model.</p></div><button className="icon" onClick={onClose} aria-label="Close">×</button></div>
    <div className="profile-import-tabs">{([['PDF','Upload LinkedIn PDF'],['TEXT','Paste LinkedIn Text'],['FORM','Fill Profile']] as const).map(([value,label]) => <button key={value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{label}</button>)}</div>
    {tab === 'PDF' && <section className="import-pane"><div className="upload-drop" onClick={chooseFile}><strong>{parsing ? 'Reading profile…' : 'Drop a LinkedIn profile PDF here'}</strong><span>or choose a PDF, TXT, Markdown or profile export</span><button type="button" className="refresh">Choose file</button></div><label>Optional LinkedIn/profile URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.linkedin.com/in/…" /></label><p className="muted">The supplied PDF is useful even when LinkedIn itself requires authentication.</p></section>}
    {tab === 'TEXT' && <section className="import-pane"><label>Optional LinkedIn/profile URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.linkedin.com/in/…" /></label><label>Paste the complete visible professional profile<textarea rows={16} value={raw} onChange={e => setRaw(e.target.value)} placeholder="Name\nHeadline\nAbout\nExperience\nEducation\nCertifications\nProjects\nPublications\nSkills\nActivity…" /></label><button className="refresh" onClick={() => parse(raw)} disabled={!raw.trim()}>Parse profile</button></section>}
    {tab === 'FORM' && <section className="import-pane profile-form"><div className="form-grid"><label>Full name<input value={fullName} onChange={e => setFullName(e.target.value)} /></label><label>Professional headline<input value={profile.headline || ''} onChange={e => update({ headline: e.target.value })} /></label><label>Current job title<input value={profile.currentTitle || ''} onChange={e => update({ currentTitle: e.target.value })} /></label><label>Current company<input value={profile.currentCompany || ''} onChange={e => update({ currentCompany: e.target.value })} /></label><label>Business location<input value={profile.location || ''} onChange={e => update({ location: e.target.value })} /></label><label>LinkedIn/profile URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" /></label></div><label>Professional summary / About<textarea rows={5} value={profile.about || ''} onChange={e => update({ about: e.target.value })} /></label>
      <div className="form-section"><div className="panelhead"><h3>Experience</h3><button className="refresh" onClick={addPosition}>+ Add position</button></div>{profile.positions.map((position, i) => <div className="repeat-row" key={i}><input aria-label="Job title" placeholder="Job title" value={position.title} onChange={e => updatePosition(i, { title: e.target.value })} /><input aria-label="Company" placeholder="Company" value={position.company_name || ''} onChange={e => updatePosition(i, { company_name: e.target.value })} /><input aria-label="Start year" placeholder="Start year" value={position.start_date || ''} onChange={e => updatePosition(i, { start_date: e.target.value })} /><input aria-label="End year" placeholder="End / Present" value={position.end_date || ''} onChange={e => updatePosition(i, { end_date: e.target.value })} /><button className="icon" onClick={() => update({ positions: removeAt(profile.positions, i) })} aria-label="Remove position">×</button></div>)}</div>
      <div className="form-section"><div className="panelhead"><h3>Education</h3><button className="refresh" onClick={addEducation}>+ Add education</button></div>{profile.education.map((education, i) => <div className="repeat-row" key={i}><input aria-label="Institution" placeholder="Institution" value={education.institution} onChange={e => updateEducation(i, { institution: e.target.value })} /><input aria-label="Degree" placeholder="Degree / qualification" value={education.degree || ''} onChange={e => updateEducation(i, { degree: e.target.value })} /><input aria-label="Field" placeholder="Field" value={education.field || ''} onChange={e => updateEducation(i, { field: e.target.value })} /><button className="icon" onClick={() => update({ education: removeAt(profile.education, i) })} aria-label="Remove education">×</button></div>)}</div>
      <div className="form-section"><div className="panelhead"><h3>Projects, publications and patents</h3><div><button className="refresh" onClick={() => addWork('PROJECT')}>+ Project</button> <button className="refresh" onClick={() => addWork('PUBLICATION')}>+ Publication</button> <button className="refresh" onClick={() => addWork('PATENT')}>+ Patent</button></div></div>{profile.works.map((work, i) => <div className="repeat-row work-row" key={i}><input aria-label="Work title" placeholder="Title" value={work.title} onChange={e => updateWork(i, { title: e.target.value })} /><select aria-label="Work type" value={work.work_type} onChange={e => updateWork(i, { work_type: e.target.value })}><option>PROJECT</option><option>PUBLICATION</option><option>PATENT</option><option>PROFESSIONAL_ACTIVITY</option></select><input aria-label="Work date" placeholder="Date" value={work.work_date || ''} onChange={e => updateWork(i, { work_date: e.target.value })} /><input aria-label="Work URL" placeholder="URL" value={work.url || ''} onChange={e => updateWork(i, { url: e.target.value })} /><button className="icon" onClick={() => update({ works: removeAt(profile.works, i) })} aria-label="Remove work">×</button></div>)}</div>
      <div className="form-section"><h3>Skills and certifications</h3><label>Explicit professional skills<input value={(profile.skills || []).join(', ')} onChange={e => update({ skills: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })} placeholder="Analytical development, CMC, quality…" /></label><label>Certifications<textarea rows={3} value={(profile.certifications || []).map(x => x.name).join('\n')} onChange={e => update({ certifications: e.target.value.split('\n').map(name => name.trim()).filter(Boolean).map(name => ({ name, confidence: 0.7 })) })} placeholder="One certification per line" /></label></div>
      <p className="muted">{summary}. Parser output remains user-reviewable before saving.</p></section>}
    {error && <div className="crawl-message" role="alert">{error}</div>}
    <div className="source-modal-actions"><button className="refresh" onClick={() => submit(false)} disabled={parsing}>Save profile only</button><button className="primary" onClick={() => submit(true)} disabled={parsing}>{parsing ? 'Saving…' : 'Save & research'}</button></div>
  </div></div>
}
