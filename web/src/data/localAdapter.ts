export async function loadLocalData() {
  const response = await fetch('/data.json', { cache: 'no-store' })
  if (!response.ok) throw new Error(`local_data_${response.status}`)
  const data = await response.json()
  try {
    const supplementalResponse = await fetch('/supplemental_contacts.json', { cache: 'no-store' })
    if (supplementalResponse.ok) {
      const supplemental = await supplementalResponse.json()
      const byCompany = new Map((supplemental ?? []).map((item: any) => [String(item.company).toLowerCase(), item.contacts ?? []]))
      data.leads = (data.leads ?? []).map((lead: any) => {
        const extra = byCompany.get(String(lead.account?.company ?? '').toLowerCase()) ?? []
        const existing = new Set((lead.contacts ?? []).map((contact: any) => String(contact.name).toLowerCase()))
        return { ...lead, contacts: [...(lead.contacts ?? []), ...extra.filter((contact: any) => !existing.has(String(contact.name).toLowerCase()))] }
      })
    }
  } catch { /* supplemental local intelligence is optional */ }
  return data
}
