import { useRef, useState } from 'react'
import type { CandidateRoleDecision, CandidateRoleFeedItem } from '../../types'
import RoleCard from './RoleCard'
import MatchDetails from './MatchDetails'

export default function TwinDeck({ items, busy, decide }: { items: CandidateRoleFeedItem[]; busy: boolean;
  decide: (item: CandidateRoleFeedItem, action: CandidateRoleDecision) => Promise<boolean> }) {
  const [index, setIndex] = useState(0)
  const [drag, setDrag] = useState(0)
  const start = useRef<number | null>(null)
  const item = items[index]
  async function choose(action: CandidateRoleDecision) {
    if (!item || busy) return
    const success = await decide(item, action)
    if (success && action !== 'hidden') setIndex(value => value + 1)
    setDrag(0)
  }
  if (!item) return <section className="card empty"><h2>Подборка просмотрена</h2><p>Сохранённые роли остались в вашем списке. Можно загрузить следующую страницу или начать просмотр заново.</p><button className="button outline" onClick={() => setIndex(0)}>Смотреть заново</button></section>
  return <section className="twin-deck" aria-label="Карточки ролей"><p className="small muted">{index + 1} из {items.length} · вправо — интересно, влево — пропустить</p>
    <article className="card twin-card" tabIndex={0} data-testid="twin-card" style={{ transform: `translateX(${drag / 3}px) rotate(${drag / 45}deg)` }}
      onKeyDown={event => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowRight') void choose('saved'); if (event.key === 'ArrowLeft') void choose('hidden') }}
      onPointerDown={event => { if (busy || (event.target as HTMLElement).closest('button,a,summary,input')) return; start.current = event.clientX }}
      onPointerMove={event => { if (start.current !== null) setDrag(event.clientX - start.current) }}
      onPointerCancel={() => { start.current = null; setDrag(0) }}
      onPointerUp={() => { if (drag > 90) void choose('saved'); else if (drag < -90) void choose('hidden'); start.current = null; setDrag(0) }}>
      <div className="twin-company"><span>{item.company_name}</span>{item.data_mode === 'synthetic' && <span className="badge synthetic-badge">Демо-данные</span>}</div>
      <h2>{item.role.title}</h2><div className="twin-tags"><span className="badge">{item.role.specialization} · {item.role.grade}</span><span className="badge">{{ remote: 'Удалённо', hybrid: 'Гибрид', office: 'Офис' }[item.role.work_format]}</span></div>
      <div className="salary">{item.role.salary_min_rub.toLocaleString('ru-RU')} — {item.role.salary_max_rub.toLocaleString('ru-RU')} ₽<small>в месяц · до налогов</small></div>
      <MatchDetails item={item}/><p className="twin-description">{item.role.description}</p><div className="twin-first-days"><strong>Первые 30 дней</strong><p>{item.role.first_30_days}</p></div>
      {item.match_state !== 'compatible' && <p className="notice">{item.match_state === 'needs_clarification' ? 'Часть условий или категория требуют уточнения.' : 'Подтверждённой категории пока нет.'}</p>}
      <details className="twin-details"><summary>Все условия роли</summary><RoleCard role={item.role} status="active" confirmedAt={item.confirmed_at}/></details>
      <div className="twin-actions"><button className="button outline" disabled={busy} onClick={() => void choose('hidden')}>← Пропустить роль</button><button className="primary" disabled={busy} onClick={() => void choose('saved')}>Интересно — сохранить ♥</button></div>
      <p className="small muted">Сохранение приватно. Первое приглашение отправляет компания.</p>
    </article>
  </section>
}
