import { useEffect, useState } from 'react'
import { api } from '../../api'

type Report = {
  category: string; blueprint_version: string; submitted_at: string | null; outcome: string; score: number
  score_gate: boolean; competency_gate: boolean; changed_condition_gate: boolean
  competencies: { id: string; label: string; points: number; max_points: number; percent: number; meets_minimum: boolean; practice: string | null }[]
  next_action: string; limitations: string
}

export default function AssessmentReport({ attemptId }: { attemptId: string }) {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setReport(null); setError('')
    api<Report>(`/candidate/assessment-attempts/${attemptId}/report`, 'GET', undefined, { signal: controller.signal })
      .then(setReport).catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [attemptId, retry])
  return <section className="card assessment-report" data-testid="assessment-report">
    <h2>Разбор навыков и план подготовки</h2>
    {error ? <p role="alert">{error} <button className="button subtle" onClick={() => setRetry(value => value + 1)}>Повторить</button></p>
      : !report ? <p role="status">Готовим разбор попытки…</p> : <>
        <p><strong>{report.category} · {report.score}/100</strong> · {report.outcome === 'passed' ? 'Пройден' : 'Не пройден'}</p>
        <p className="small muted">{report.submitted_at && new Date(report.submitted_at).toLocaleString('ru-RU')} · версия {report.blueprint_version}</p>
        <ul className="assessment-gates">
          {[['Не менее 70 баллов', report.score_gate], ['Не менее половины баллов в каждой группе', report.competency_gate], ['Проверка изменившегося условия', report.changed_condition_gate]].map(([label, done]) =>
            <li key={String(label)}>{done ? '✓' : '○'} {label}: {done ? 'выполнено' : 'не выполнено'}</li>)}
        </ul>
        <div className="competency-results">{report.competencies.map(topic => <div key={topic.id} className="competency-result">
          <div><strong>{topic.label}</strong><span>{topic.points} из {topic.max_points} баллов · {topic.percent}%</span></div>
          <progress aria-label={topic.label} value={topic.percent} max={100}/>
          <p className="small muted">{topic.meets_minimum ? 'Минимум группы выполнен' : 'Минимум группы пока не выполнен'}</p>
        </div>)}</div>
        {report.competencies.some(topic => topic.practice) && <><h3>Попробуйте на практике</h3><ol className="practice-plan">{[...report.competencies].sort((a, b) => a.percent - b.percent).filter(topic => topic.practice).map(topic =>
          <li key={topic.id}><strong>{topic.label}.</strong> {topic.practice}</li>)}</ol></>}
        <p>{report.next_action}</p><p className="small muted">{report.limitations}</p>
      </>}
  </section>
}
