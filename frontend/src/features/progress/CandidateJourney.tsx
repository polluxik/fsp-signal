import { useEffect, useState } from 'react'
import { api } from '../../api'

type Step = { id: string; label: string; done: boolean; tab: string }
type Journey = {
  visible_to_employers: boolean; steps: Step[]; blockers: string[]; next_step: Step | null
  active_attempt: { id: string; expires_at: string } | null; fsp_status: string
}

export default function CandidateJourney({ onNavigate, onResume }: {
  onNavigate: (tab: string) => void; onResume: (id: string) => void
}) {
  const [journey, setJourney] = useState<Journey | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    api<Journey>('/candidate/journey', 'GET', undefined, { signal: controller.signal })
      .then(setJourney).catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [retry])
  return <section className="card candidate-journey" data-testid="candidate-journey">
    <div className="section-title"><div><p className="eyebrow">ВАШ СЛЕДУЮЩИЙ ШАГ</p><h2>Маршрут к приглашению</h2></div>
      {journey && <span className={`badge ${journey.visible_to_employers ? 'green' : ''}`}>{journey.visible_to_employers ? 'Профиль виден в подборе' : 'Профиль пока скрыт'}</span>}
    </div>
    {error ? <p role="alert">{error} <button className="button subtle" onClick={() => setRetry(value => value + 1)}>Повторить</button></p>
      : !journey ? <p role="status">Проверяем сохранённый профиль…</p> : <>
        <ol className="journey-steps">{journey.steps.map(step => <li key={step.id}>
          <button onClick={() => onNavigate(step.tab)}><span aria-hidden="true">{step.done ? '✓' : '○'}</span> <span>{step.label}</span><small>{step.done ? 'Готово' : 'Нужно сделать'}</small></button>
        </li>)}</ol>
        {journey.next_step ? <button className="primary" onClick={() => onNavigate(journey.next_step!.tab)}>{journey.next_step.label}</button>
          : <p>Всё готово. Приглашения придут с зарплатой и условиями; время встречи выберете после принятия.</p>}
        {journey.active_attempt && <p><button className="button subtle" onClick={() => onResume(journey.active_attempt!.id)}>Продолжить незавершённый тест</button></p>}
        <p className="small muted">Учитываются только сохранённые данные. Компании подбирают по категории и вашим условиям. ФСП ID необязателен.</p>
      </>}
  </section>
}
