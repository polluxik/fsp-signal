import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import MeetingList from './MeetingList'
import { type Calendar, moment, wallTime, zonedISO } from './types'

export default function CalendarPanel() {
  const [calendar, setCalendar] = useState<Calendar | null>(null)
  const [zone, setZone] = useState('Europe/Moscow')
  const [callUrl, setCallUrl] = useState('')
  const [day, setDay] = useState(() => wallTime(new Date(Date.now() + 86400000), 'Europe/Moscow').slice(0, 10))
  const [from, setFrom] = useState('10:00')
  const [until, setUntil] = useState('16:00')
  const [duration, setDuration] = useState(30)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const settingsLoaded = useRef(false)
  async function load() {
    const result = await api<Calendar>('/employer/calendar')
    setCalendar(result)
    if (!settingsLoaded.current) {
      settingsLoaded.current = true
      setZone(result.timezone); setCallUrl(result.call_url ?? '')
    }
  }
  useEffect(() => { void load().catch(err => setError(err.message)) }, [])
  async function act(job: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setNotice('')
    try { await job(); await load(); setNotice(success) }
    catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function addRange(start: string, end: string) {
    await api('/employer/calendar/availability', 'POST', {
      starts_at: zonedISO(`${day}T${start}`, zone), ends_at: zonedISO(`${day}T${end}`, zone), duration_minutes: duration,
    })
  }
  const dailySlots = calendar?.slots.filter(slot => wallTime(new Date(slot.starts_at), zone).startsWith(day)) ?? []
  const grid = Array.from({ length: 12 * 60 / duration }, (_, index) => {
    const minutes = 8 * 60 + index * duration
    const time = `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}`
    const end = minutes + duration
    const endTime = `${Math.floor(end / 60).toString().padStart(2, '0')}:${(end % 60).toString().padStart(2, '0')}`
    const exact = dailySlots.find(slot => wallTime(new Date(slot.starts_at), zone).slice(11) === time)
    const overlap = dailySlots.some(slot => {
      const a = wallTime(new Date(slot.starts_at), zone).slice(11), b = wallTime(new Date(slot.ends_at), zone).slice(11)
      return a < endTime && b > time
    })
    return { time, endTime, exact, overlap }
  })
  return <>
    <div className="page-heading"><p className="eyebrow">ВРЕМЯ ДЛЯ ЗНАКОМСТВА</p><h1>Календарь HR</h1>
      <p>Откройте несколько часов или отдельные слоты. Кандидат с принятым приглашением выберет удобное время по вашей ссылке.</p></div>
    {error && <div className="notice bad" role="alert">{error}</div>}
    {notice && <div className="notice good" role="status">{notice}</div>}
    <section className="card calendar-settings"><h2>Ссылка на ваш календарь</h2>
      <div className="calendar-link"><input aria-label="Ссылка на календарь" readOnly value={calendar?.public_url ?? ''}/>
        <button className="button outline" disabled={!calendar} onClick={() => void navigator.clipboard.writeText(calendar?.public_url ?? '')
          .then(() => setNotice('Ссылка скопирована.')).catch(() => setNotice('Выделите и скопируйте ссылку из поля.'))}>Копировать</button></div>
      <p className="small muted">По ссылке видны только свободные слоты. Забронировать время можно после принятия приглашения.</p>
      <div className="form-grid"><label>Часовой пояс HR<select disabled={!calendar || busy} value={zone} onChange={event => setZone(event.target.value)}>
        {['Europe/Moscow', 'Europe/Berlin', 'Asia/Yekaterinburg', 'Asia/Novosibirsk', 'America/New_York', 'UTC'].map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Ссылка на созвон<input disabled={!calendar || busy} type="url" value={callUrl} onChange={event => setCallUrl(event.target.value)} placeholder="https://…"/></label></div>
      <button className="button outline" disabled={!calendar || busy} onClick={() => void act(() => api('/employer/calendar', 'PUT', { timezone: zone, call_url: callUrl }), 'Настройки календаря сохранены.')}>Сохранить календарь</button>
      <p className="small muted">Ссылка закрепляется в уже назначенной встрече. Изменение действует на новые брони.</p>
    </section>
    <section className="card"><div className="section-title"><div><p className="eyebrow">ДОСТУПНОСТЬ</p><h2>Выберите день и время</h2></div><span className="badge">{zone}</span></div>
      <div className="availability-form"><label>День<input type="date" value={day} onChange={event => setDay(event.target.value)}/></label>
        <label>Начало<input type="time" value={from} onChange={event => setFrom(event.target.value)}/></label>
        <label>Конец<input type="time" value={until} onChange={event => setUntil(event.target.value)}/></label>
        <label>Длительность<select value={duration} onChange={event => setDuration(Number(event.target.value))}><option value={20}>20 минут</option><option value={30}>30 минут</option></select></label></div>
      <button className="primary" disabled={busy || !day} onClick={() => void act(() => addRange(from, until), 'Свободные слоты добавлены.')}>Открыть диапазон</button>
      <p className="small muted">Или отмечайте отдельные слоты ниже. Повторный выбор свободного слота убирает его.</p>
      <div className="availability-grid" aria-label="Слоты выбранного дня">{grid.map(({ time, endTime, exact, overlap }) => <button key={time}
        className={`time-cell${exact ? exact.booked ? ' booked' : ' available' : ''}`} disabled={busy || !day || !!exact?.booked || (!exact && overlap)}
        aria-label={`${exact ? 'Убрать' : 'Добавить'} слот ${time}`} aria-pressed={!!exact}
        onClick={() => void act(() => exact ? api(`/employer/calendar/slots/${exact.id}`, 'DELETE') : addRange(time, endTime), exact ? 'Слот убран.' : 'Слот открыт.')}>
        {time}<small>{exact?.booked ? 'Занято' : exact ? 'Открыт' : overlap ? 'Пересечение' : `+ ${duration} мин`}</small></button>)}</div>
      {dailySlots.length > 0 && <div className="slot-list">{dailySlots.map(slot => <div key={slot.id}><span>{moment(slot.starts_at, zone)} — {new Date(slot.ends_at).toLocaleTimeString('ru-RU', { timeZone: zone, hour: '2-digit', minute: '2-digit' })}</span>
        {slot.booked ? <span className="badge">Забронирован</span> : <button className="text-button" disabled={busy} onClick={() => void act(() => api(`/employer/calendar/slots/${slot.id}`, 'DELETE'), 'Слот убран.')}>Убрать</button>}</div>)}</div>}
    </section>
    <MeetingList viewer="employer" onChanged={() => void load()}/>
  </>
}
