import { useEffect, useState } from 'react'
import { api } from '../../api'

type Category = { specialization: string; grade: string; label: string; competencies: { id: string; label: string }[] }

export default function AssessmentPlan({ specialization, grade }: { specialization: string; grade: string }) {
  const [categories, setCategories] = useState<Category[]>([])
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    api<Category[]>('/taxonomy/categories', 'GET', undefined, { signal: controller.signal }).then(setCategories)
      .catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [retry])
  const category = categories.find(item => item.specialization === specialization && item.grade === grade)
  return <div className="assessment-plan" data-testid="assessment-plan">
    <h3>Что проверим: {category?.label ?? 'выбранная категория'}</h3>
    {error ? <p role="alert">{error} <button className="button subtle" onClick={() => setRetry(value => value + 1)}>Повторить</button></p>
      : category ? <ul>{category.competencies.map(topic => <li key={topic.id}>{topic.label}</li>)}</ul> : <p role="status">Загружаем план теста…</p>}
    <p className="small muted">20 минут на два этапа с момента старта. На втором изменится условие; ответы первого фиксируются. Сохраняйте ответы кнопкой перехода между этапами. Повтор той же категории — через 72 часа; до 3 попыток за 7 дней. Смену подтверждённой категории ограничивает период 30 дней, кроме перехода ниже после неудачного теста.</p>
  </div>
}
