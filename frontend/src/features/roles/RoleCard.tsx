import type { RoleCardOut, RoleCardPayload } from '../../types'

type Props = {
  role: Partial<RoleCardPayload> | null
  status?: RoleCardOut['publication_state']
  confirmedAt?: string | null
  recordedAt?: string
  source?: string | null
  compact?: boolean
}

const formatNames: Record<string, string> = { remote: 'Удалённо', hybrid: 'Гибрид', office: 'Офис' }
const competencyNames: Record<string, string> = {
  data_trace: 'Данные и трассировка', validation: 'Валидация', http_api: 'HTTP API',
  event_idempotency: 'Идемпотентность событий', data_integrity: 'Целостность данных',
  failure_recovery: 'Восстановление после сбоев', javascript_trace: 'JavaScript',
  ui_state: 'Состояние интерфейса', forms: 'Формы', request_races: 'Гонки запросов',
  derived_state: 'Производное состояние', error_recovery: 'Восстановление после ошибок',
}

function rubles(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value) + ' ₽'
}

function date(value?: string | null): string {
  if (!value) return 'Дата подтверждения не сохранена'
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value))
}

function statusName(status?: Props['status']): string {
  return ({ draft: 'Черновик', active: 'Опубликована', paused: 'На паузе', closed: 'Закрыта' } as Record<string, string>)[status ?? ''] ?? 'Условия роли'
}

export default function RoleCard({ role, status, confirmedAt, recordedAt, source, compact = false }: Props) {
  if (!role) return <div className="empty role-empty">Условия роли пока не заполнены.</div>
  const salaryComplete = typeof role.salary_min_rub === 'number' && role.salary_min_rub > 0
    && typeof role.salary_max_rub === 'number' && role.salary_max_rub >= role.salary_min_rub
  const location = role.work_format === 'remote' ? 'Удалённо' : role.work_city || 'Город не указан'
  const tasks = role.competencies?.map(item => competencyNames[item] ?? item) ?? []
  const sourceLabel = source === 'synthetic_demo' ? 'Синтетическая вакансия'
    : source === 'employer_declared' ? 'Заявлено работодателем'
      : source === 'legacy_import' ? 'Импортированные условия · источник не подтверждён' : null
  const sourceClass = source === 'synthetic_demo' ? 'synthetic-badge' : source === 'legacy_import' ? 'unknown-source-badge' : ''
  return <article className={`role-card ${compact ? 'compact' : ''}`}>
    <div className="role-card-topline"><span className="eyebrow">{role.specialization && role.grade ? `${role.specialization.toUpperCase()} · ${role.grade.toUpperCase()}` : 'РОЛЬ'}</span>
      <div className="role-source-badges">
        {sourceLabel && <span className={`badge ${sourceClass}`}>{sourceLabel}</span>}
        <span className={`badge ${status === 'active' ? 'green' : ''}`}>{statusName(status)}</span>
      </div></div>
    <h3>{role.title || 'Название роли не заполнено'}</h3>
    <p className="role-salary">{salaryComplete ? `${rubles(role.salary_min_rub!)} — ${rubles(role.salary_max_rub!)}` : 'Диапазон зарплаты не указан'}
      <span>в месяц · до налогов</span></p>
    <div className="role-facts">
      <div><span>Формат</span><strong>{role.work_format ? formatNames[role.work_format] ?? role.work_format : 'Не указан'}</strong></div>
      {(role.work_format === 'hybrid' || role.work_format === 'office') && <div><span>Город</span><strong>{location}</strong></div>}
      <div><span>Актуальность</span><strong>{confirmedAt ? `Подтверждена ${date(confirmedAt)}` : recordedAt ? `Зафиксирована ${date(recordedAt)}` : date(null)}</strong></div>
    </div>
    {role.description && <section className="role-detail"><h4>Задача команды</h4><p>{role.description}</p></section>}
    {role.first_30_days && <section className="role-detail"><h4>Первые 30 дней</h4><p>{role.first_30_days}</p></section>}
    {tasks.length > 0 && <section className="role-detail"><h4>На что смотрим</h4><ul className="role-task-list">{tasks.map(task => <li key={task}>{task}</li>)}</ul></section>}
    {role.stack?.length ? <p className="role-stack"><strong>Стек:</strong> {role.stack.join(', ')} <span className="muted">(указан работодателем)</span></p> : !compact && <p className="small muted">Стек не указан — это не означает, что он не требуется.</p>}
    {!compact && <div className="role-details-grid">
      <section className="role-detail"><h4>Этапы</h4>
        {role.interview_steps?.length
          ? <ol>{role.interview_steps.map((step, index) => <li key={`${step.title}-${index}`}>{step.title} · {step.duration_minutes} мин.</li>)}</ol>
          : <p className="unknown-value">Не указаны</p>}
      </section>
      <section className="role-detail"><h4>Дополнительное задание</h4>
        <p>{role.take_home_minutes === undefined ? 'Не указано' : role.take_home_minutes === 0 ? 'Нет' : `До ${role.take_home_minutes} минут`}</p>
        <h4>Ответ работодателя</h4><p>{role.response_sla_hours ? `В течение ${role.response_sla_hours} ч.` : 'Срок не указан'}</p>
      </section>
    </div>}
  </article>
}
