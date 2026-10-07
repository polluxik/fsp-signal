import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import type { AssistantPreferencesDraft, CandidatePreferences } from '../../types'
import AssistantPanel from '../assistant/AssistantPanel'

const emptyPreferences: CandidatePreferences = {
  version: 1,
  salary_min_rub: null,
  allowed_work_formats: ['remote'],
  allowed_cities: [],
  excluded_industries: [],
  preferred_stack: [],
  preferred_tasks: [],
  max_take_home_minutes: null,
  available: true,
  adult_hiring_confirmed: false,
}

function splitList(value: string): string[] {
  return [...new Set(value.split(',').map(item => item.trim()).filter(Boolean))]
}

function joinList(values: string[]): string {
  return values.join(', ')
}

export default function PreferencesPanel({ onSaved }: { onSaved?: (value: CandidatePreferences) => void }) {
  const [preferences, setPreferences] = useState<CandidatePreferences>(emptyPreferences)
  const [cities, setCities] = useState('')
  const [industries, setIndustries] = useState('')
  const [stack, setStack] = useState('')
  const [tasks, setTasks] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [conflict, setConflict] = useState(false)

  function apply(value: CandidatePreferences) {
    setPreferences(value)
    setCities(joinList(value.allowed_cities))
    setIndustries(joinList(value.excluded_industries))
    setStack(joinList(value.preferred_stack))
    setTasks(joinList(value.preferred_tasks))
  }

  useEffect(() => {
    const controller = new AbortController()
    api<CandidatePreferences>('/candidate/preferences', 'GET', undefined, { signal: controller.signal })
      .then(apply)
      .catch((err: Error) => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  function toggleFormat(format: CandidatePreferences['allowed_work_formats'][number]) {
    setPreferences(current => {
      const present = current.allowed_work_formats.includes(format)
      const next = present
        ? current.allowed_work_formats.filter(item => item !== format)
        : [...current.allowed_work_formats, format]
      return { ...current, allowed_work_formats: next }
    })
  }

  function applyAssistantDraft(draft: AssistantPreferencesDraft) {
    setPreferences(current => ({
      ...current,
      salary_min_rub: draft.salary_min_rub ?? current.salary_min_rub,
      allowed_work_formats: draft.allowed_work_formats.length ? draft.allowed_work_formats : current.allowed_work_formats,
      max_take_home_minutes: draft.max_take_home_minutes ?? current.max_take_home_minutes,
    }))
    if (draft.allowed_cities.length) setCities(joinList(draft.allowed_cities))
    if (draft.excluded_industries.length) setIndustries(joinList(draft.excluded_industries))
    if (draft.preferred_stack.length) setStack(joinList(draft.preferred_stack))
    if (draft.preferred_tasks.length) setTasks(joinList(draft.preferred_tasks))
  }

  async function reloadSaved() {
    setError('')
    try {
      const saved = await api<CandidatePreferences>('/candidate/preferences')
      apply(saved)
      onSaved?.(saved)
      setConflict(false)
      setFeedback('Загружена последняя сохранённая версия. Черновик заменён.')
    } catch (err) { setError((err as Error).message) }
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setError('')
    setFeedback('')
    setBusy(true)
    const payload = {
      ...preferences,
      expected_version: preferences.version,
      allowed_cities: splitList(cities),
      excluded_industries: splitList(industries),
      preferred_stack: splitList(stack),
      preferred_tasks: splitList(tasks),
    }
    try {
      const saved = await api<CandidatePreferences>('/candidate/preferences', 'PUT', payload)
      apply(saved)
      onSaved?.(saved)
      setConflict(false)
      setFeedback('Условия обновлены. Они фильтруют подходящие предложения и не показываются работодателям.')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PREFERENCES_VERSION_CONFLICT') setConflict(true)
      setError((err as Error).message)
    } finally { setBusy(false) }
  }

  if (loading) return <section className="card loading-panel" aria-busy="true"><div className="skeleton-line"/><div className="skeleton-line short"/><p className="muted">Загружаем ваши условия…</p></section>

  return <section className="card preferences-panel">
    <div className="section-title">
      <div><p className="eyebrow">УСЛОВИЯ ПОИСКА · ВЕРСИЯ {preferences.version}</p><h2>Сначала важное для вас</h2></div>
      <span className="badge">Не видно работодателю</span>
    </div>
    <p className="muted preference-intro">Жёсткие условия исключают неподходящие роли. Работодатель не увидит вашу минимальную зарплату, причины отказа или список ограничений.</p>
    <AssistantPanel intent="candidate_preferences" testId="assistant-candidate-preferences"
      promptLabel="Что важно в работе?" onApply={applyAssistantDraft}/>
    {error && <div className="notice bad" role="alert">{error}{conflict && <button className="text-button" type="button" onClick={reloadSaved}>Загрузить сохранённую версию</button>}</div>}
    {feedback && <div className="notice good" role="status">{feedback}</div>}
    <form className="form-grid" onSubmit={save}>
      <label>Минимум, ₽ в месяц до налогов <span className="hint">Оставьте пустым, если строгого минимума нет</span>
        <input type="number" min="1" inputMode="numeric" value={preferences.salary_min_rub ?? ''}
          onChange={event => setPreferences({ ...preferences, salary_min_rub: event.target.value ? Number(event.target.value) : null })}/>
      </label>
      <label>Дополнительное задание <span className="hint">Максимум времени; 0 — не готов(а)</span>
        <select value={preferences.max_take_home_minutes ?? 'any'} onChange={event => setPreferences({
          ...preferences, max_take_home_minutes: event.target.value === 'any' ? null : Number(event.target.value),
        })}>
          <option value="any">Нет ограничения</option><option value="0">Не готов(а) к заданию</option>
          {[30, 60, 90, 120, 180, 240].map(minutes => <option key={minutes} value={minutes}>До {minutes} минут</option>)}
        </select>
      </label>
      <fieldset className="full preference-fieldset">
        <legend>Подходящий формат <span className="hint">Выберите хотя бы один</span></legend>
        <div className="checks">
          {([['remote', 'Удалённо'], ['hybrid', 'Гибрид'], ['office', 'Офис']] as const).map(([value, label]) =>
            <label key={value}><input type="checkbox" checked={preferences.allowed_work_formats.includes(value)}
              onChange={() => toggleFormat(value)}/>{label}</label>)}
        </div>
      </fieldset>
      <label className="full">Города для гибрида и офиса <span className="hint">Через запятую</span>
        <input value={cities} onChange={event => setCities(event.target.value)} placeholder="Москва, Казань"/>
      </label>
      <label>Отрасли, которые исключить <span className="hint">Через запятую</span>
        <input value={industries} onChange={event => setIndustries(event.target.value)} placeholder="Например: азартные игры"/>
      </label>
      <label>Интересующий стек <span className="hint">Мягкое предпочтение</span>
        <input value={stack} onChange={event => setStack(event.target.value)} placeholder="Python, PostgreSQL"/>
      </label>
      <label className="full">Какие задачи интересны? <span className="hint">Мягкое предпочтение; свободный текст, через запятую</span>
        <input value={tasks} onChange={event => setTasks(event.target.value)} placeholder="Системы данных, надёжность, API"/>
      </label>
      <fieldset className="full preference-fieldset">
        <legend>Доступность</legend>
        <div className="check-list">
          <label><input type="checkbox" checked={preferences.available}
            onChange={event => setPreferences({ ...preferences, available: event.target.checked })}/>
            Готов(а) получать подходящие предложения</label>
          <label><input type="checkbox" checked={preferences.adult_hiring_confirmed}
            onChange={event => setPreferences({ ...preferences, adult_hiring_confirmed: event.target.checked })}/>
            Подтверждаю, что мне исполнилось 18 лет</label>
        </div>
        <p className="small muted">Это ваше подтверждение для найма, не внешняя проверка возраста.</p>
      </fieldset>
      {preferences.allowed_work_formats.length === 0 && <p className="field-error full" role="alert">Оставьте хотя бы один подходящий формат.</p>}
      <div className="full preference-submit"><button className="primary" disabled={busy || preferences.allowed_work_formats.length === 0}>
        {busy ? 'Сохраняем…' : 'Сохранить условия'}
      </button><span className="small muted">Сохранение версии {preferences.version} → {preferences.version + 1}</span></div>
    </form>
  </section>
}
