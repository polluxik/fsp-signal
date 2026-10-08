import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import type { AssistantRoleDraft, DemoPromotion, Need, RoleCardOut, RoleCardPayload } from '../../types'
import AssistantPanel from '../assistant/AssistantPanel'
import RoleCard from './RoleCard'

type StepDraft = { title: string; duration_minutes: string }
type RoleDraft = {
  title: string
  description: string
  specialization: 'backend' | 'frontend' | 'qa' | 'data_analyst'
  grade: 'junior' | 'middle'
  competencies: string[]
  stack: string
  salary_min_rub: string
  salary_max_rub: string
  work_format: '' | 'remote' | 'hybrid' | 'office'
  work_city: string
  industry: string
  first_30_days: string
  interview_steps: StepDraft[]
  take_home_minutes: string
  response_sla_hours: '' | '24' | '48' | '72'
  employer_contact: string
  active_headcount_attested: boolean
}

const competencyOptions: Record<string, { id: string; label: string }[]> = {
  'backend:junior': [
    { id: 'data_trace', label: 'Данные и трассировка' }, { id: 'validation', label: 'Валидация' }, { id: 'http_api', label: 'HTTP API' },
  ],
  'backend:middle': [
    { id: 'event_idempotency', label: 'Идемпотентность событий' }, { id: 'data_integrity', label: 'Целостность данных' }, { id: 'failure_recovery', label: 'Восстановление после сбоев' },
  ],
  'frontend:junior': [
    { id: 'javascript_trace', label: 'JavaScript' }, { id: 'ui_state', label: 'Состояние интерфейса' }, { id: 'forms', label: 'Формы' },
  ],
  'frontend:middle': [
    { id: 'request_races', label: 'Гонки запросов' }, { id: 'derived_state', label: 'Производное состояние' }, { id: 'error_recovery', label: 'Восстановление после ошибок' },
  ],
  'qa:junior': [
    { id: 'test_design', label: 'Проектирование проверок' }, { id: 'bug_reporting', label: 'Воспроизводимый баг-репорт' }, { id: 'api_testing', label: 'Проверка API' },
  ],
  'qa:middle': [
    { id: 'risk_based_testing', label: 'Приоритизация рисков' }, { id: 'automation_design', label: 'Проектирование автотестов' }, { id: 'reliability_testing', label: 'Надёжность и отказоустойчивость' },
  ],
  'data_analyst:junior': [
    { id: 'sql_querying', label: 'SQL-запросы' }, { id: 'data_quality', label: 'Качество данных' }, { id: 'metric_definition', label: 'Определение метрик' },
  ],
  'data_analyst:middle': [
    { id: 'experiment_analysis', label: 'Анализ эксперимента' }, { id: 'metric_integrity', label: 'Целостность метрик' }, { id: 'data_validation', label: 'Валидация данных' },
  ],
}

function newDraft(need: Need, contact: string): RoleDraft {
  return {
    title: need.title,
    description: need.description,
    specialization: need.specialization as RoleDraft['specialization'],
    grade: need.grade as RoleDraft['grade'],
    competencies: [...need.competencies],
    stack: (need.stack ?? []).join(', '),
    salary_min_rub: String(need.salary_min_rub || ''),
    salary_max_rub: String(need.salary_max_rub || ''),
    work_format: need.work_format === 'any' ? '' : need.work_format as RoleDraft['work_format'],
    work_city: '', industry: '', first_30_days: '', interview_steps: [],
    take_home_minutes: '', response_sla_hours: '', employer_contact: contact,
    active_headcount_attested: false,
  }
}

function draftFrom(role: Partial<RoleCardPayload>, need: Need, contact: string): RoleDraft {
  const base = newDraft(need, contact)
  return {
    ...base,
    ...role,
    specialization: role.specialization ?? base.specialization,
    grade: role.grade ?? base.grade,
    competencies: role.competencies ?? base.competencies,
    stack: (role.stack ?? need.stack ?? []).join(', '),
    salary_min_rub: role.salary_min_rub == null ? base.salary_min_rub : String(role.salary_min_rub),
    salary_max_rub: role.salary_max_rub == null ? base.salary_max_rub : String(role.salary_max_rub),
    work_format: role.work_format === 'remote' || role.work_format === 'hybrid' || role.work_format === 'office'
      ? role.work_format : base.work_format,
    work_city: role.work_city ?? '',
    industry: role.industry ?? '',
    interview_steps: (role.interview_steps ?? []).map(step => ({ title: step.title, duration_minutes: String(step.duration_minutes) })),
    take_home_minutes: role.take_home_minutes == null ? '' : String(role.take_home_minutes),
    response_sla_hours: role.response_sla_hours == null ? '' : String(role.response_sla_hours) as RoleDraft['response_sla_hours'],
    employer_contact: role.employer_contact ?? contact,
    active_headcount_attested: role.active_headcount_attested ?? false,
  }
}

function payloadFrom(draft: RoleDraft): RoleCardPayload {
  return {
    title: draft.title.trim(), description: draft.description.trim(),
    specialization: draft.specialization, grade: draft.grade,
    competencies: draft.competencies,
    stack: [...new Set(draft.stack.split(',').map(item => item.trim()).filter(Boolean))],
    salary_min_rub: Number(draft.salary_min_rub), salary_max_rub: Number(draft.salary_max_rub),
    work_format: draft.work_format as RoleCardPayload['work_format'], work_city: draft.work_city.trim() || null,
    industry: draft.industry.trim() || null, first_30_days: draft.first_30_days.trim(),
    interview_steps: draft.interview_steps.map(step => ({
      title: step.title.trim(), duration_minutes: Number(step.duration_minutes),
    })),
    take_home_minutes: Number(draft.take_home_minutes),
    response_sla_hours: Number(draft.response_sla_hours) as RoleCardPayload['response_sla_hours'],
    employer_contact: draft.employer_contact.trim(),
    active_headcount_attested: draft.active_headcount_attested,
  }
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function initialRoleValue(payload: Partial<RoleCardPayload> | null): string {
  return payload ? stable(payload) : ''
}

type Props = { need: Need; companyContact: string; onSaved: (card: RoleCardOut) => void }

export default function RoleEditor({ need, companyContact, onSaved }: Props) {
  const [role, setRole] = useState<RoleCardOut | null>(null)
  const [promotion, setPromotion] = useState<DemoPromotion | null>(null)
  const [draft, setDraft] = useState<RoleDraft>(() => newDraft(need, companyContact))
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [promotionError, setPromotionError] = useState('')
  const [promotionBusy, setPromotionBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [loadRevision, setLoadRevision] = useState(0)
  const formRef = useRef<HTMLFormElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setConflict(false)
    setPromotion(null)
    setPromotionError('')
    api<RoleCardOut>(`/employer/needs/${need.id}/role-card`, 'GET', undefined, { signal: controller.signal })
      .then(card => {
        setRole(card)
        setDraft(draftFrom(card.payload, need, companyContact))
      })
      .catch((err: Error) => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    api<DemoPromotion | null>(`/employer/needs/${need.id}/promotion/demo`, 'GET', undefined, { signal: controller.signal })
      .then(setPromotion)
      .catch((err: Error) => { if (err.name !== 'AbortError') setPromotionError(err.message) })
    return () => controller.abort()
  }, [need.id, companyContact, loadRevision])

  const currentPayload = useMemo(() => payloadFrom(draft), [draft])
  const previewPayload: Partial<RoleCardPayload> = {
    ...currentPayload,
    work_format: draft.work_format || undefined,
    salary_min_rub: draft.salary_min_rub ? Number(draft.salary_min_rub) : undefined,
    salary_max_rub: draft.salary_max_rub ? Number(draft.salary_max_rub) : undefined,
    take_home_minutes: draft.take_home_minutes === '' ? undefined : Number(draft.take_home_minutes),
    response_sla_hours: draft.response_sla_hours ? Number(draft.response_sla_hours) as RoleCardPayload['response_sla_hours'] : undefined,
    interview_steps: draft.interview_steps.map(step => ({
      title: step.title,
      duration_minutes: step.duration_minutes ? Number(step.duration_minutes) : 0,
    })),
  }
  const savedPayload = role?.payload ?? null
  const dirty = Boolean(role && stable(currentPayload) !== initialRoleValue(savedPayload))
  const availableCompetencies = competencyOptions[`${draft.specialization}:${draft.grade}`] ?? []

  function patch(patchValue: Partial<RoleDraft>) {
    setDraft(current => ({ ...current, ...patchValue }))
    setFeedback('')
  }

  function applyAssistantDraft(value: AssistantRoleDraft) {
    const classificationChanged = (value.specialization != null && value.specialization !== draft.specialization)
      || (value.grade != null && value.grade !== draft.grade)
    patch({
      title: value.title ?? draft.title,
      description: value.description ?? draft.description,
      specialization: value.specialization ?? draft.specialization,
      grade: value.grade ?? draft.grade,
      competencies: value.competencies.length ? value.competencies : classificationChanged ? [] : draft.competencies,
      stack: value.stack.length ? value.stack.join(', ') : draft.stack,
      salary_min_rub: value.salary_min_rub == null ? draft.salary_min_rub : String(value.salary_min_rub),
      salary_max_rub: value.salary_max_rub == null ? draft.salary_max_rub : String(value.salary_max_rub),
      work_format: value.work_format ?? draft.work_format,
      work_city: value.work_city ?? draft.work_city,
      industry: value.industry ?? draft.industry,
      first_30_days: value.first_30_days ?? draft.first_30_days,
      interview_steps: value.interview_steps.length
        ? value.interview_steps.map(step => ({ title: step.title, duration_minutes: String(step.duration_minutes) }))
        : draft.interview_steps,
      take_home_minutes: value.take_home_minutes == null ? draft.take_home_minutes : String(value.take_home_minutes),
      response_sla_hours: value.response_sla_hours == null ? draft.response_sla_hours : String(value.response_sla_hours) as RoleDraft['response_sla_hours'],
    })
  }

  async function persist(): Promise<RoleCardOut> {
    if (!role || role.current_role_version < 1) throw new Error('Не найдена версия черновика роли.')
    if (draft.competencies.length === 0 || draft.interview_steps.length === 0) {
      throw new Error('Выберите хотя бы одну компетенцию и добавьте минимум один этап отбора.')
    }
    const saved = await api<RoleCardOut>(`/employer/needs/${need.id}/versions`, 'POST', {
      expected_version: role.current_role_version,
      card: currentPayload,
    })
    setRole(saved)
    setDraft(draftFrom(saved.payload, need, companyContact))
    setPromotion(null)
    onSaved(saved)
    return saved
  }

  async function saveDraft(event?: FormEvent) {
    event?.preventDefault()
    setError('')
    setFeedback('')
    if (!dirty) {
      setFeedback('Изменений нет — новая версия не создавалась.')
      return
    }
    setBusy(true)
    setConflict(false)
    try {
      const saved = await persist()
      setFeedback(`Условия сохранены как версия ${saved.current_role_version}. Публикация — отдельное действие.`)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'ROLE_VERSION_CONFLICT') {
        setConflict(true)
        setFeedback('Ваша форма сохранена. Проверьте свежую версию роли перед повторным сохранением.')
      }
      setError((err as Error).message)
    } finally { setBusy(false) }
  }

  async function publish() {
    setError('')
    setFeedback('')
    if (!draft.active_headcount_attested) {
      setError('Подтвердите, что у команды есть актуальная потребность и бюджет.')
      return
    }
    if (draft.competencies.length === 0 || draft.interview_steps.length === 0) {
      setError('Выберите хотя бы одну компетенцию и добавьте минимум один этап отбора.')
      return
    }
    if (!formRef.current?.reportValidity()) return
    setBusy(true)
    try {
      let current = role
      if (!current) throw new Error('Дождитесь загрузки версии роли.')
      if (dirty) current = await persist()
      const path = current.publication_state === 'active' ? 'reconfirm' : 'publish'
      const result = await api<RoleCardOut>(`/employer/needs/${need.id}/${path}`, 'POST', {
        expected_version: current.current_role_version,
        active_headcount_attested: true,
        ...(path === 'publish' ? { discoverable: true } : {}),
      })
      setRole(result)
      onSaved(result)
      void refreshPromotion()
      setFeedback(result.fresh ? 'Роль опубликована и подтверждена на ближайшие 14 дней.' : 'Статус роли обновлён.')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'ROLE_VERSION_CONFLICT') {
        setConflict(true)
        setFeedback('Ваша форма не была заменена. Проверьте свежую версию роли перед повторным сохранением.')
      }
      setError((err as Error).message)
    } finally { setBusy(false) }
  }

  async function changeState(action: 'pause' | 'close') {
    if (!role) return
    if (action === 'close' && !window.confirm('Закрыть роль? Новые приглашения по ней отправить не получится.')) return
    setBusy(true)
    setError('')
    setFeedback('')
    try {
      const result = await api<RoleCardOut>(`/employer/needs/${need.id}/${action}`, 'POST', {
        expected_version: role.current_role_version,
      })
      setRole(result)
      setPromotion(null)
      onSaved(result)
      setFeedback(action === 'pause' ? 'Роль поставлена на паузу.' : 'Роль закрыта.')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'ROLE_VERSION_CONFLICT') {
        setConflict(true)
        setFeedback('Ваша форма сохранена. Проверьте свежую версию роли перед повторным действием.')
      }
      setError((err as Error).message)
    } finally { setBusy(false) }
  }

  async function refreshPromotion() {
    try {
      setPromotion(await api<DemoPromotion | null>(`/employer/needs/${need.id}/promotion/demo`))
      setPromotionError('')
    } catch (err) {
      setPromotionError((err as Error).message)
    }
  }

  async function activatePromotion() {
    setPromotionBusy(true)
    setPromotionError('')
    setFeedback('')
    try {
      const active = await api<DemoPromotion>(`/employer/needs/${need.id}/promotion/demo`, 'POST')
      setPromotion(active)
      setFeedback('')
    } catch (err) {
      setPromotionError((err as Error).message)
    } finally { setPromotionBusy(false) }
  }

  function promotionEndDate(value: string): string {
    return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })
      .format(new Date(value))
  }

  if (loading) return <section className="card loading-panel" aria-busy="true"><div className="skeleton-line"/><div className="skeleton-line short"/><p className="muted">Загружаем сохранённые условия…</p></section>

  return <div className="role-editor-grid">
    <section className="card role-editor">
      <div className="section-title"><div><p className="eyebrow">ВЕРСИЯ {role?.current_role_version ?? '—'} · {role?.fresh ? 'АКТУАЛЬНАЯ' : 'ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ'}</p>
        <h2>Опишите реальную работу</h2></div><span className={`badge ${role?.publication_state === 'active' ? 'green' : ''}`}>{role?.publication_state ?? 'draft'}</span></div>
      <p className="muted">Короткая задача за минуту — но кандидату нужны конкретные первые задачи, этапы и честный срок ответа. Неизвестное оставьте пустым: ничего не подставляется за вас.</p>
      {error && <div className="notice bad" role="alert">{error}{conflict && <button className="text-button" type="button" onClick={() => setLoadRevision(value => value + 1)}>Я понимаю: заменить черновик данными сервера</button>}</div>}
      {feedback && <div className="notice good" role="status">{feedback}</div>}
      {role?.missing_fields?.length ? <p className="field-error">Не заполнено: {role.missing_fields.join(', ')}</p> : null}
      <AssistantPanel intent="employer_role" testId="assistant-employer-role"
        promptLabel="Опишите роль своими словами" onApply={applyAssistantDraft}/>
      <form className="form-grid" ref={formRef} onSubmit={saveDraft}>
        <label>Название роли<input required minLength={3} maxLength={180} value={draft.title} onChange={event => patch({ title: event.target.value })}/></label>
        <label>Направление<select value={draft.specialization} onChange={event => patch({ specialization: event.target.value as RoleDraft['specialization'], competencies: [] })}><option value="backend">Backend</option><option value="frontend">Frontend</option><option value="qa">QA</option><option value="data_analyst">Аналитика данных</option></select></label>
        <label>Грейд<select value={draft.grade} onChange={event => patch({ grade: event.target.value as RoleDraft['grade'], competencies: [] })}><option value="junior">Junior</option><option value="middle">Middle</option></select></label>
        <label>Формат<select required value={draft.work_format} onChange={event => patch({ work_format: event.target.value as RoleDraft['work_format'] })}><option value="">Выберите формат</option><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option></select></label>
        {(draft.work_format === 'hybrid' || draft.work_format === 'office') && <label>Город<input required maxLength={120} value={draft.work_city} onChange={event => patch({ work_city: event.target.value })} placeholder="Город работы"/></label>}
        <label>Зарплата от, ₽/мес. до налогов<input required type="number" min="1" inputMode="numeric" value={draft.salary_min_rub} onChange={event => patch({ salary_min_rub: event.target.value })}/></label>
        <label>Зарплата до, ₽/мес. до налогов<input required type="number" min="1" inputMode="numeric" value={draft.salary_max_rub} onChange={event => patch({ salary_max_rub: event.target.value })}/></label>
        <label className="full">Чем будет заниматься специалист?<span className="hint">10–2 000 символов</span><textarea rows={3} minLength={10} maxLength={2000} required value={draft.description} onChange={event => patch({ description: event.target.value })}/></label>
        <label className="full">Результат первых 30 дней<span className="hint">Что человек реально сделает или поймёт за первый месяц?</span><textarea rows={3} minLength={10} maxLength={2000} required value={draft.first_30_days} onChange={event => patch({ first_30_days: event.target.value })} placeholder="Пока не указано"/></label>
        <fieldset className="full preference-fieldset">
          <legend>Какие действия будут важны в работе?</legend>
          <div className="checks">{availableCompetencies.map(item => <label key={item.id}><input type="checkbox" checked={draft.competencies.includes(item.id)}
            onChange={event => patch({ competencies: event.target.checked ? [...draft.competencies, item.id] : draft.competencies.filter(id => id !== item.id) })}/>{item.label}</label>)}</div>
        </fieldset>
        <label>Технологии, которые используете<span className="hint">Через запятую; указаны работодателем</span><input value={draft.stack} onChange={event => patch({ stack: event.target.value })} placeholder="Python, PostgreSQL"/></label>
        <label>Отрасль команды <span className="hint">Необязательно</span><input maxLength={120} value={draft.industry} onChange={event => patch({ industry: event.target.value })}/></label>
        <div className="full interview-steps">
          <div className="section-title"><div><h3>Этапы отбора</h3><p className="small muted">Кандидат увидит число встреч, содержание и длительность.</p></div>
            <button className="button subtle" type="button" disabled={draft.interview_steps.length >= 5} onClick={() => patch({ interview_steps: [...draft.interview_steps, { title: '', duration_minutes: '' }] })}>Добавить этап</button></div>
          {draft.interview_steps.map((step, index) => <div className="interview-step-row" key={index}>
            <label>Этап {index + 1}<input required minLength={3} maxLength={120} value={step.title}
              onChange={event => patch({ interview_steps: draft.interview_steps.map((item, at) => at === index ? { ...item, title: event.target.value } : item) })}/></label>
            <label>Минут<input required type="number" min="1" max="240" value={step.duration_minutes}
              onChange={event => patch({ interview_steps: draft.interview_steps.map((item, at) => at === index ? { ...item, duration_minutes: event.target.value } : item) })}/></label>
            <button className="text-button remove-step" type="button" aria-label={`Удалить этап ${index + 1}`} onClick={() => patch({ interview_steps: draft.interview_steps.filter((_, at) => at !== index) })}>Удалить</button>
          </div>)}
          {draft.interview_steps.length === 0 && <p className="unknown-value">Этапы не указаны — добавьте хотя бы один, чтобы кандидат понимал процесс.</p>}
        </div>
        <label>Дополнительное задание<span className="hint">Минут; 0 — задания нет, пусто — ещё не решили</span><input required type="number" min="0" max="240" value={draft.take_home_minutes} onChange={event => patch({ take_home_minutes: event.target.value })}/></label>
        <label>Срок ответа после первого разговора<select required value={draft.response_sla_hours} onChange={event => patch({ response_sla_hours: event.target.value as RoleDraft['response_sla_hours'] })}><option value="">Выберите срок</option><option value="24">24 часа</option><option value="48">48 часов</option><option value="72">72 часа</option></select></label>
        <label className="full">Контакт ответственного работодателя<input required type="email" value={draft.employer_contact} onChange={event => patch({ employer_contact: event.target.value })}/></label>
        <label className="full attestation-label"><input type="checkbox" checked={draft.active_headcount_attested} onChange={event => patch({ active_headcount_attested: event.target.checked })}/>
          Подтверждаю, что это актуальная потребность команды с согласованным бюджетом</label>
        <div className="full role-editor-actions"><button className="button outline" type="submit" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить черновик'}</button>
          <button className="primary" type="button" onClick={publish} disabled={busy}>{busy ? 'Обновляем…' : role?.publication_state === 'active' && !dirty ? 'Подтвердить актуальность' : 'Сохранить и опубликовать'}</button>
          {role?.publication_state === 'active' && <button className="button subtle" type="button" disabled={busy} onClick={() => changeState('pause')}>Пауза</button>}
          {role?.publication_state !== 'closed' && <button className="text-button" type="button" disabled={busy} onClick={() => changeState('close')}>Закрыть роль</button>}
        </div>
        {role?.publication_state === 'active' && role.discoverable && role.fresh && <section className="full role-promotion-control" aria-label="Продвижение вакансии">
          <div>
            <p className="eyebrow">ОТДЕЛЬНАЯ ПОЛКА · БЕЗ ВЛИЯНИЯ НА MATCHING</p>
            {promotion
              ? <p className="promotion-status" role="status">Продвижение активно до {promotionEndDate(promotion.active_until)}. Оплаты нет, выручка — ₽0.</p>
              : <p className="muted">Покажем актуальную роль в отдельном блоке подходящим кандидатам на 14 дней. На органическую выдачу и условия роли это не влияет.</p>}
            <p className="promotion-no-charge">Без оплаты</p>
          </div>
          {!promotion && <button className="button promotion-button" type="button" disabled={promotionBusy}
            onClick={() => void activatePromotion()}>
            {promotionBusy ? 'Включаем…' : 'Включить продвижение'}
          </button>}
          {promotionError && <p className="notice bad promotion-error" role="alert">{promotionError}</p>}
        </section>}
      </form>
    </section>
    <aside className="role-preview"><p className="eyebrow">ТАК УСЛОВИЯ УВИДИТ КАНДИДАТ</p>
      <RoleCard role={previewPayload} status={role?.publication_state} confirmedAt={role?.confirmed_at} source={role?.source}/>
      <p className="small muted">Опубликованные условия версионируются. При изменении кандидат заново решает, подходит ли ему новая версия.</p>
    </aside>
  </div>
}
