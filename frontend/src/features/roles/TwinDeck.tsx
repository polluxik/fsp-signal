import { useRef, useState, type PointerEvent } from 'react'
import { displayText } from '../../presentation'
import type { CandidateRoleDecision, CandidateRoleFeedItem } from '../../types'
import RoleCard from './RoleCard'
import MatchDetails from './MatchDetails'
import './twin.css'

const identity = (item: CandidateRoleFeedItem) => `${item.need_id}:${item.role_version_id}`
const formats = { remote: 'Удалённо', hybrid: 'Гибрид', office: 'Офис' }
const categories = { backend: 'Backend', frontend: 'Frontend', qa: 'QA', data_analyst: 'Аналитика данных' }

export default function TwinDeck({ items, busy, decide }: { items: CandidateRoleFeedItem[]; busy: boolean;
  decide: (item: CandidateRoleFeedItem, action: CandidateRoleDecision) => Promise<boolean> }) {
  const [seen, setSeen] = useState<Set<string>>(new Set())
  const [drag, setDrag] = useState(0)
  const [pending, setPending] = useState(false)
  const locked = useRef(false)
  const gesture = useRef<{ id: number; x: number; y: number; horizontal: boolean } | null>(null)
  const remaining = items.filter(candidate => !seen.has(identity(candidate)))
  const item = remaining[0]
  const disabled = busy || pending

  async function choose(action: CandidateRoleDecision) {
    if (!item || busy || locked.current) return
    locked.current = true
    setPending(true)
    setDrag(0)
    gesture.current = null
    try {
      const success = await decide(item, action)
      // Hidden items are removed by RoleFeed; undo restores them to this deck.
      if (success && action === 'saved') setSeen(current => new Set(current).add(identity(item)))
    } finally {
      locked.current = false
      setPending(false)
    }
  }

  function finishGesture(event: PointerEvent<HTMLElement>, cancelled = false) {
    const current = gesture.current
    gesture.current = null
    setDrag(0)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (!current || current.id !== event.pointerId || cancelled || !current.horizontal) return
    const distance = event.clientX - current.x
    if (distance > 90) void choose('saved')
    else if (distance < -90) void choose('hidden')
  }

  if (!item) return <section className="card empty twin-finished" aria-live="polite"><span className="twin-finished-icon" aria-hidden="true">♥</span><h2>Подборка просмотрена</h2><p>Интересные роли остались в сохранённых. Можно загрузить следующую страницу или начать просмотр заново.</p><button className="button outline" onClick={() => setSeen(new Set())}>Смотреть заново</button></section>
  const company = displayText(item.company_name)
  const initials = company.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase() || 'ФС'
  const count = remaining.length
  const noun = count % 100 >= 11 && count % 100 <= 14 ? 'ролей' : count % 10 === 1 ? 'роль' : count % 10 >= 2 && count % 10 <= 4 ? 'роли' : 'ролей'
  return <section className="twin-deck twin-deck-v2" aria-label="Карточки ролей">
    <div className="twin-progress"><span aria-live="polite">В подборке ещё {count} {noun}</span><span>← пропустить · сохранить →</span></div>
    <div className="twin-stage"><div className="twin-back twin-back-far" aria-hidden="true"/><div className="twin-back" aria-hidden="true"/>
    <article className={`card twin-card${disabled ? ' twin-pending' : ''}`} tabIndex={0} data-testid="twin-card" data-need-id={item.need_id} aria-busy={disabled}
      style={{ transform: `translateX(${drag / 3}px) rotate(${drag / 45}deg)` }}
      onKeyDown={event => { if (event.target !== event.currentTarget || event.repeat) return; if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); void choose(event.key === 'ArrowRight' ? 'saved' : 'hidden') } }}
      onPointerDown={event => {
        if (disabled || !event.isPrimary || event.button !== 0 || (event.target as Element).closest('button,a,summary,input,textarea,select,label,[contenteditable]')) return
        gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, horizontal: false }
      }}
      onPointerMove={event => {
        const current = gesture.current
        if (!current || current.id !== event.pointerId) return
        const dx = event.clientX - current.x, dy = event.clientY - current.y
        if (!current.horizontal && Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.3) {
          current.horizontal = true
          event.currentTarget.setPointerCapture(event.pointerId)
        }
        if (current.horizontal) setDrag(Math.max(-150, Math.min(150, dx)))
      }}
      onPointerCancel={event => finishGesture(event, true)}
      onLostPointerCapture={() => { gesture.current = null; setDrag(0) }}
      onPointerUp={event => finishGesture(event)}>
      {Math.abs(drag) > 35 && <span className={`twin-stamp ${drag > 0 ? 'save' : 'skip'}`} aria-hidden="true">{drag > 0 ? 'ИНТЕРЕСНО ♥' : 'ПРОПУСТИТЬ'}</span>}
      <div className="twin-brand"><span className="twin-avatar" aria-hidden="true">{initials}</span><div><p className="twin-company">{company}</p><span className="small muted">Актуальная роль · v{item.role_version}</span></div>{item.decision === 'saved' && <span className="badge">♥ Сохранено</span>}</div>
      <h2>{displayText(item.role.title)}</h2>
      <div className="twin-tags"><span className="badge">{categories[item.role.specialization]} · {item.role.grade}</span><span className="badge">{formats[item.role.work_format]}{item.role.work_city && ` · ${item.role.work_city}`}</span></div>
      <div className="salary">{item.role.salary_min_rub.toLocaleString('ru-RU')} — {item.role.salary_max_rub.toLocaleString('ru-RU')} ₽<small>в месяц · до налогов</small></div>
      <MatchDetails item={item}/>
      {item.role.stack.length > 0 && <div className="twin-stack" aria-label="Технологии роли">{item.role.stack.slice(0, 6).map(skill => <span key={skill}>{skill}</span>)}{item.role.stack.length > 6 && <span>+{item.role.stack.length - 6}</span>}</div>}
      <p className="twin-description">{displayText(item.role.description)}</p><div className="twin-first-days"><strong>Ваши первые 30 дней</strong><p>{displayText(item.role.first_30_days)}</p></div>
      {item.match_state !== 'compatible' && <p className="notice">{item.match_state === 'needs_clarification' ? 'Часть условий или категория требуют уточнения.' : 'Подтверждённой категории пока нет.'}</p>}
      <details className="twin-details"><summary>Все условия роли</summary><RoleCard role={item.role} status="active" confirmedAt={item.confirmed_at}/></details>
      <div className="twin-actions"><button className="button outline twin-skip" disabled={disabled} onClick={() => void choose('hidden')}>← Пропустить роль</button><button className="primary twin-save" disabled={disabled} onClick={() => void choose('saved')}>Интересно — сохранить ♥</button></div>
      <p className="small muted twin-privacy">Сохранение приватно. Первое приглашение отправляет компания.</p>
    </article></div>
  </section>
}
