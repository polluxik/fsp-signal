export type Slot = { id: string; starts_at: string; ends_at: string; booked: boolean }
export type Calendar = { company_name: string; timezone: string; slots: Slot[]; public_url?: string; call_url?: string }
export type Meeting = {
  id: string; invitation_id: string; version: number; state: 'scheduled' | 'cancelled'
  starts_at: string; ends_at: string; company_name: string; candidate_alias: string
  call_url: string; access_revoked: boolean; notes: string; transcript: string; has_recording: boolean
  candidate_recording_consent: boolean; employer_recording_consent: boolean
  summary: { summary: string; decisions: string[]; next_steps: string[]; open_questions: string[] } | null
}

export function wallTime(date: Date, zone: string): string {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, year: 'numeric', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date)
  const p = Object.fromEntries(parts.map(item => [item.type, item.value]))
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

export function zonedISO(value: string, zone: string): string {
  const target = Date.parse(value + ':00Z')
  if (!Number.isFinite(target)) throw new Error('Выберите дату и время.')
  let result = target
  for (let index = 0; index < 3; index++) {
    const rendered = Date.parse(wallTime(new Date(result), zone) + ':00Z')
    result += target - rendered
  }
  if (wallTime(new Date(result), zone) !== value) throw new Error('Это время отсутствует из-за перевода часов. Выберите другое.')
  return new Date(result).toISOString()
}

export function moment(value: string, zone?: string): string {
  return new Date(value).toLocaleString('ru-RU', { timeZone: zone, day: 'numeric', month: 'long',
    hour: '2-digit', minute: '2-digit' })
}
