import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../../api'
import { displayText } from '../../presentation'
import type { Invite, User } from '../../types'
import { type Calendar, type Meeting, type Slot, moment } from './types'

export default function PublicCalendar({ me, auth }: { me: User | null; auth: ReactNode }) {
  const token = location.pathname.split('/')[2]
  const [calendar, setCalendar] = useState<Calendar | null>(null)
  const [options, setOptions] = useState<Invite[]>([])
  const [invitationId, setInvitationId] = useState('')
  const [selected, setSelected] = useState<Slot | null>(null)
  const [week, setWeek] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [login, setLogin] = useState(false)
  const [booked, setBooked] = useState<Meeting | null>(null)
  const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone
  async function load() { setCalendar(await api<Calendar>(`/calendars/${token}`)) }
  useEffect(() => { void load().catch(err => setError(err.message)) }, [token])
  useEffect(() => {
    if (me?.role !== 'candidate') return
    api<Invite[]>('/candidate/invitations').then(async invitations => {
      const choices = await Promise.all(invitations.filter(invite => invite.state === 'accepted').map(async invite => {
        try {
          const link = await api<{ url: string }>(`/invitations/${invite.id}/calendar`)
          return new URL(link.url).pathname === location.pathname ? invite : null
        } catch { return null }
      }))
      const matching = choices.filter((invite): invite is Invite => invite !== null)
      setOptions(matching); setInvitationId(matching[0]?.id ?? '')
    }).catch(err => setError(err.message))
  }, [me?.id, token])
  async function book() {
    if (!selected || !invitationId) return
    setBusy(true); setError('')
    try { setBooked(await api<Meeting>(`/calendars/${token}/book`, 'POST', { slot_id: selected.id, invitation_id: invitationId })); await load() }
    catch (err) { setError((err as Error).message); await load(); setSelected(null) }
    finally { setBusy(false) }
  }
  if (login && !me) return <>{auth}<div className="calendar-login-back"><button className="text-button" onClick={() => setLogin(false)}>Вернуться к календарю</button></div></>
  const start = new Date(); start.setHours(0, 0, 0, 0); start.setDate(start.getDate() + week * 7)
  const end = new Date(start); end.setDate(end.getDate() + 7)
  const slots = calendar?.slots.filter(slot => new Date(slot.starts_at) >= start && new Date(slot.starts_at) < end) ?? []
  const days = [...new Set(slots.map(slot => new Date(slot.starts_at).toLocaleDateString('ru-RU')))]
  return <main className="booking-page"><a href="/" className="logo">ФСП <strong>СИГНАЛ</strong></a>
    <div className="page-heading"><p className="eyebrow">ДАВАЙТЕ ПОЗНАКОМИМСЯ</p><h1>Выберите время созвона</h1>
      <p>{calendar?.company_name ? displayText(calendar.company_name) : 'Загружаем календарь…'}</p></div>
    {error && <div className="notice bad" role="alert">{error}</div>}
    {booked ? <section className="card booking-success"><span className="badge green">Встреча назначена</span><h2>{moment(booked.starts_at)}</h2>
      <p>Оба участника получат уведомление. Время показано в {localZone}.</p>
      {booked.call_url ? <a className="button primary" href={booked.call_url} target="_blank" rel="noreferrer">Открыть созвон</a> : <p>Работодатель передаст ссылку на созвон отдельно.</p>}
      <a className="button outline" href={`/api/v1/meetings/${booked.id}/calendar.ics`}>Добавить в свой календарь</a><a href="/" className="button subtle">В кабинет</a>
    </section> : <>
      <div className="booking-week"><button className="button outline" disabled={!week} onClick={() => { setWeek(value => value - 1); setSelected(null) }}>← Предыдущая</button>
        <strong>{start.toLocaleDateString('ru-RU')} — {new Date(end.getTime() - 1).toLocaleDateString('ru-RU')}</strong>
        <button className="button outline" disabled={week >= 12} onClick={() => { setWeek(value => value + 1); setSelected(null) }}>Следующая →</button></div>
      <p className="small muted">Ваш часовой пояс: {localZone}. Часовой пояс HR: {calendar?.timezone}. Длительность — 20 или 30 минут.</p>
      {!slots.length && calendar && <section className="empty card">На этой неделе свободных слотов нет. Посмотрите следующую.</section>}
      <div className="booking-days">{days.map(day => <section className="card" key={day}><h2>{day}</h2><div className="booking-slots">
        {slots.filter(slot => new Date(slot.starts_at).toLocaleDateString('ru-RU') === day).map(slot => <button key={slot.id}
          className={`button ${selected?.id === slot.id ? 'primary' : 'outline'}`} aria-pressed={selected?.id === slot.id}
          onClick={() => setSelected(slot)}>{new Date(slot.starts_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
          <small>{Math.round((Date.parse(slot.ends_at) - Date.parse(slot.starts_at)) / 60000)} мин</small></button>)}
      </div></section>)}</div>
      {selected && <section className="card booking-confirm"><h2>{moment(selected.starts_at)}</h2>
        {!me ? <><p>Войдите как кандидат, чтобы связать встречу с вашим принятым приглашением.</p><button className="primary" onClick={() => setLogin(true)}>Войти и выбрать время</button></>
          : me.role !== 'candidate' ? <p>Это календарь для бронирования кандидатом. Управляйте слотами в кабинете HR.</p>
          : !options.length ? <p>Сначала примите приглашение этой компании в своём кабинете.</p>
          : <><label>Приглашение<select value={invitationId} onChange={event => setInvitationId(event.target.value)}>{options.map(invite => <option key={invite.id} value={invite.id}>{invite.offer_text.slice(0, 80)}</option>)}</select></label>
            <button className="primary" disabled={busy} onClick={() => void book()}>{busy ? 'Бронируем…' : 'Подтвердить время'}</button></>}
      </section>}
    </>}
  </main>
}
