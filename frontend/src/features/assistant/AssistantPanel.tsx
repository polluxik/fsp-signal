import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type {
  AssistantAchievementDraft,
  AssistantPreferencesDraft,
  AssistantRoleDraft,
} from '../../types'

type Intent = 'candidate_preferences' | 'candidate_achievement' | 'employer_role'
type DraftByIntent = {
  candidate_preferences: AssistantPreferencesDraft
  candidate_achievement: AssistantAchievementDraft
  employer_role: AssistantRoleDraft
}
type Props<T extends Intent> = {
  intent: T
  testId: string
  promptLabel: string
  onApply: (draft: DraftByIntent[T]) => void
}

const endpoint: Record<Intent, string> = {
  candidate_preferences: '/assistant/candidate/preferences',
  candidate_achievement: '/assistant/candidate/achievement',
  employer_role: '/assistant/employer/role',
}

const titles: Record<Intent, string> = {
  candidate_preferences: 'Черновик предпочтений',
  candidate_achievement: 'Черновик рассказа',
  employer_role: 'Черновик вакансии',
}

const fieldLabels: Record<string, string> = {
  title: 'Название', description: 'Описание роли', salary_min_rub: 'Зарплата от', salary_max_rub: 'Зарплата до',
  allowed_work_formats: 'Формат', allowed_cities: 'Города', excluded_industries: 'Исключённые отрасли',
  preferred_stack: 'Стек', preferred_tasks: 'Интересные задачи', max_take_home_minutes: 'Тестовое задание',
  context: 'Контекст', personal_contribution: 'Ваш вклад', decision: 'Почему так', result: 'Результат',
  result_scope: 'Масштаб результата', basis: 'Основание', specialization: 'Направление', grade: 'Грейд',
  competencies: 'Компетенции', stack: 'Технологии', work_format: 'Формат', work_city: 'Город', industry: 'Отрасль',
  first_30_days: 'Первые 30 дней', interview_steps: 'Этапы', take_home_minutes: 'Дополнительное задание',
  response_sla_hours: 'Срок ответа',
}

const fieldNames: Record<string, string> = {
  salary_min_rub: 'минимальную зарплату', allowed_work_formats: 'формат работы', allowed_cities: 'города',
  excluded_industries: 'неподходящие отрасли', preferred_stack: 'технологии', preferred_tasks: 'интересные задачи',
  max_take_home_minutes: 'допустимое время тестового задания', context: 'контекст задачи',
  personal_contribution: 'ваш личный вклад', decision: 'обоснование подхода', result: 'результат',
  result_scope: 'масштаб результата', basis: 'артефакт или основание', title: 'название роли',
  description: 'задачу роли', specialization: 'направление', grade: 'грейд', competencies: 'ключевые компетенции',
  stack: 'технологии', salary_max_rub: 'максимальную зарплату', work_format: 'формат работы', work_city: 'город',
  industry: 'отрасль', first_30_days: 'результат первых 30 дней', interview_steps: 'этапы отбора',
  take_home_minutes: 'время тестового задания', response_sla_hours: 'срок ответа',
}

function displayValue(key: string, value: unknown): string {
  if (Array.isArray(value)) {
    return value.map(item => {
      if (item && typeof item === 'object' && 'title' in item) {
        const step = item as { title: string; duration_minutes: number }
        return `${step.title} · ${step.duration_minutes} мин.`
      }
      return String(item)
    }).join(', ')
  }
  if (value === null || value === '') return ''
  if (key === 'max_take_home_minutes' || key === 'take_home_minutes') {
    return value === 0 ? 'Нет' : `${String(value)} мин.`
  }
  if (key === 'response_sla_hours') return `${String(value)} ч.`
  if (typeof value === 'number' && value > 1000) return `${new Intl.NumberFormat('ru-RU').format(value)} ₽`
  if (typeof value === 'number' && value === 0) return 'Нет'
  if (value === 'individual') return 'личный'
  if (value === 'team') return 'командный'
  if (value === 'remote') return 'удалённо'
  if (value === 'hybrid') return 'гибрид'
  if (value === 'office') return 'офис'
  if (value === 'backend') return 'Backend'
  if (value === 'frontend') return 'Frontend'
  if (value === 'data_analyst') return 'Аналитика данных'
  if (value === 'qa') return 'QA'
  return String(value)
}

export default function AssistantPanel<T extends Intent>({ intent, testId, promptLabel, onApply }: Props<T>) {
  const [text, setText] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [draft, setDraft] = useState<DraftByIntent[T] | null>(null)
  const request = useRef<AbortController | null>(null)

  useEffect(() => () => request.current?.abort(), [])

  async function createDraft() {
    if (!text.trim() || !consent || busy) return
    setError('')
    setFeedback('')
    setBusy(true)
    const controller = new AbortController()
    request.current = controller
    try {
      const result = await api<DraftByIntent[T]>(endpoint[intent], 'POST', {
        text: text.trim(),
        external_ai_consent: true,
      }, { signal: controller.signal })
      setDraft(result)
      setConsent(false)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError((err as Error).message)
      setConsent(false)
    } finally {
      if (!controller.signal.aborted) setBusy(false)
      if (request.current === controller) request.current = null
    }
  }

  function applyDraft() {
    if (!draft) return
    onApply(draft)
    setDraft(null)
    setConsent(false)
    setFeedback('Черновик перенесён в форму. Проверьте и отредактируйте поля; сохранение остаётся отдельным действием.')
  }

  const output = draft as Record<string, unknown> | null
  const visibleFields = output ? Object.entries(output).filter(([key, value]) =>
    !['missing_fields', 'ambiguous_fields', 'follow_up_questions'].includes(key)
    && value !== null && value !== '' && (!Array.isArray(value) || value.length > 0)) : []
  const missingFields = output?.missing_fields as string[] | undefined
  const ambiguousFields = output?.ambiguous_fields as string[] | undefined
  const followUpQuestions = output?.follow_up_questions as string[] | undefined

  return <section className="assistant-panel" data-testid={testId} aria-labelledby={`${testId}-title`}>
    <div className="assistant-panel-heading">
      <div><p className="eyebrow">ЧЕРНОВИК С ПОМОЩЬЮ ИИ</p><h3 id={`${testId}-title`}>Собрать из короткого рассказа</h3></div>
      <span className="badge">Не сохраняет и не публикует</span>
    </div>
    <label>{promptLabel}
      <textarea rows={3} maxLength={2000} value={text} aria-describedby={`${testId}-privacy ${testId}-counter`}
        onChange={event => { setText(event.target.value); setDraft(null); setError(''); setFeedback('') }}/>
    </label>
    <p className="small muted" id={`${testId}-privacy`}>
      Перед отправкой текст уйдёт внешнему AI-провайдеру, настроенному для Signal. Отправится только этот текст;
      похожие на email и телефон контакты будут удалены. Не вставляйте пароли, документы и секретные данные.
    </p>
    <div className="assistant-panel-footer">
      <label className="assistant-consent">
        <input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/>
        <span>Понимаю: этот текст будет отправлен внешнему AI-провайдеру для подготовки черновика</span>
      </label>
      <span className="small muted" id={`${testId}-counter`}>{text.length}/2000</span>
    </div>
    <button className="button outline" type="button" onClick={() => void createDraft()}
      disabled={busy || !text.trim() || !consent}>
      {busy ? 'Готовим черновик…' : 'Составить черновик'}
    </button>
    {busy && <p className="small muted" role="status">Ответ может занять до 30 секунд. Исходный текст останется в форме; пока запрос выполняется, кнопка недоступна.</p>}
    {error && <div className="notice bad" role="alert">{error}</div>}
    {feedback && <div className="notice good" role="status">{feedback}</div>}
    {draft && <div className="assistant-draft" aria-live="polite">
      <h4>{titles[intent]}</h4>
      <p className="small muted">Проверьте предложения ниже. После переноса все поля можно изменить вручную.</p>
      {visibleFields.length > 0 && <dl className="assistant-draft-fields">
        {visibleFields.map(([key, value]) => <div key={key}><dt>{fieldLabels[key] ?? key}</dt><dd>{displayValue(key, value)}</dd></div>)}
      </dl>}
      {missingFields && missingFields.length > 0 && <p className="assistant-follow-up"><strong>Нужно уточнить:</strong> {missingFields.map(field => fieldNames[field] ?? field).join(', ')}.</p>}
      {ambiguousFields && ambiguousFields.length > 0 && <p className="assistant-follow-up"><strong>Неоднозначно:</strong> {ambiguousFields.map(field => fieldNames[field] ?? field).join(', ')}.</p>}
      {followUpQuestions && followUpQuestions.length > 0 && <ul className="assistant-questions">{followUpQuestions.map(question => <li key={question}>{question}</li>)}</ul>}
      <button className="primary" type="button" onClick={applyDraft}>Применить в форму</button>
    </div>}
  </section>
}
