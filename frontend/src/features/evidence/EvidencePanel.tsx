import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { EvidenceCard } from '../../types'

type Props = {
  candidateId?: string
  mode?: 'self' | 'select'
  selectedIds?: string[]
  onSelectedIdsChange?: (ids: string[]) => void
  externalCards?: EvidenceCard[]
  externalLoading?: boolean
}

const levelNames: Record<EvidenceCard['verification_level'], string> = {
  verified_action: 'Действие проверено заданием',
  verified_credential: 'Проверено по данным ФСП',
  declared: 'Заявлено кандидатом',
  aggregate: 'Подтверждена категория, без сохранённого действия',
  synthetic_fixture: 'Синтетическая демонстрация',
}

const sourceNames: Record<EvidenceCard['source_type'], string> = {
  assessment_attempt: 'Практическая проверка',
  fsp_achievement: 'Достижение ФСП',
  achievement_story: 'История достижения',
  skill_claim: 'Навык из профиля',
  legacy_aggregate: 'Ранее сохранённая категория',
}

export default function EvidencePanel({ candidateId, mode = 'self', selectedIds = [], onSelectedIdsChange,
  externalCards, externalLoading = false }: Props) {
  const [cards, setCards] = useState<EvidenceCard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const selectable = mode === 'select'

  useEffect(() => {
    const controller = new AbortController()
    if (externalCards) {
      setCards(externalCards)
      setLoading(externalLoading)
      return () => controller.abort()
    }
    if (selectable && !candidateId) {
      setError('Не выбран кандидат.')
      setLoading(false)
      return () => controller.abort()
    }
    setLoading(true)
    setError('')
    const path = selectable ? `/employer/candidates/${candidateId}/evidence` : '/candidate/evidence'
    api<EvidenceCard[]>(path, 'GET', undefined, { signal: controller.signal })
      .then(setCards)
      .catch((err: Error) => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [candidateId, selectable, externalCards, externalLoading])

  function toggle(id: string) {
    if (!onSelectedIdsChange) return
    onSelectedIdsChange(selectedIds.includes(id)
      ? selectedIds.filter(current => current !== id)
      : [...selectedIds, id])
  }

  return <section className={`evidence-panel ${selectable ? 'selectable-evidence' : ''}`} aria-busy={loading}>
    <div className="section-title"><div><p className="eyebrow">ИСТОЧНИКИ И ОГРАНИЧЕНИЯ</p>
      <h2>{selectable ? 'На каких фактах основано приглашение?' : 'Что именно подтверждает ваш профиль?'}</h2></div>
      {selectable && <span className="badge">Выбрано: {selectedIds.length}</span>}
    </div>
    <p className="muted">Проверенное действие, агрегированный результат и заявление кандидата показаны отдельно. Отсутствие данных не означает отсутствие навыка.</p>
    {loading && <div className="evidence-loading"><div className="skeleton-line"/><div className="skeleton-line short"/><span className="small muted">Загружаем источники…</span></div>}
    {error && <div className="notice bad" role="alert">{error}</div>}
    {!loading && !error && cards.length === 0 && <div className="empty evidence-empty">Пока нет сохранённых источников. Резюме и заявленные навыки можно добавить в профиле.</div>}
    {!loading && !error && cards.length > 0 && <div className="evidence-list">
      {cards.map(card => <article className="evidence-item" key={card.id}>
        <div className="evidence-item-heading">
          {selectable && <input type="checkbox" aria-label={`Добавить: ${sourceNames[card.source_type]}`}
            checked={selectedIds.includes(card.id)} onChange={() => toggle(card.id)}/>}
          <div><span className="badge">{sourceNames[card.source_type]}</span>
            <span className={`badge ${['verified_action', 'verified_credential'].includes(card.verification_level) ? 'green' : ''}`}>{levelNames[card.verification_level]}</span></div>
        </div>
        <p className="evidence-action">{card.action}</p>
        {card.competency && <p className="small muted">Компетенция: {card.competency}</p>}
        <ul className="evidence-limitations">{card.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
        {card.data_mode === 'synthetic' && <p className="small synthetic-note">Синтетические демонстрационные данные — не реальный результат кандидата.</p>}
      </article>)}
    </div>}
  </section>
}
