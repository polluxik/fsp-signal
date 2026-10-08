import { useEffect, useState } from 'react'
import { api } from '../../api'
import './market.css'

type Card = { id: string; kind: 'profile' | 'vacancy'; title: string; family_id: string; family_name: string;
  level: string; city: string | null; work_formats: string[]; skills: string[]; summary: string; salary_min: number | null; salary_max: number | null }
type Catalog = { profiles: number; vacancies: number; families: { id: string; name: string; profile_count: number; vacancy_count: number }[] }
type MarketPage = { items: Card[]; total: number; offset: number; limit: number }
type Claim = { title: string; period?: { from: string; to: string }; organization?: string; work_summary?: string;
  declared_actions?: string[]; result?: string; result_scope?: string; problem?: string; actions?: string[]; stack?: string[]; my_role?: string }
type Details = { display_name?: string; summary?: string; experience_months_declared?: number; work_history?: Claim[]; projects?: Claim[];
  education?: { institution: string; program: string; period: string }[]; languages?: { language: string; level: string }[];
  certificates?: { title?: string; name?: string; issuer?: string }[];
  achievement_story?: { context: string; personal_contribution: string; decision: string; outcome: string; result_scope: string; basis: string; metric_notice: string | null };
  description?: string; team_context?: string; responsibilities?: string[]; expected_results?: string[]; first_30_days?: string;
  interview_stages?: { name: string; duration_minutes: number }[]; take_home_minutes?: number; response_sla_hours?: number }
type Detail = { card: Card; details: Details }
type Comparison = { status: string; checks: { field: string; label: string; passed: boolean | null; explanation: string }[];
  matched_skills: string[]; missing_skills: string[]; notice: string }
type Filters = { family: string; level: string; format: string; q: string }
const empty: Filters = { family: '', level: '', format: '', q: '' }
const levels: Record<string, string> = { junior: 'Junior', middle: 'Middle', senior: 'Senior', lead: 'Lead' }
const formats: Record<string, string> = { remote: 'Удалённо', hybrid: 'Гибрид', office: 'Офис' }
const money = (value: number | null) => value === null ? 'не указано' : `${value.toLocaleString('ru-RU')} ₽`

function Resume({ details: d }: { details: Details }) {
  return <div className="market-resume" data-testid="market-resume">
    <h3>{d.display_name}</h3><p>{d.summary}</p><p>Заявленный опыт: {d.experience_months_declared} мес. Стаж не определяет грейд.</p>
    <h3>История работы · со слов персонажа</h3>
    {d.work_history?.length ? d.work_history.map((job, i) => <section className="market-history" key={i}>
      <h4>{job.title} · {job.organization}</h4><p className="small muted">{job.period?.from} — {job.period?.to}</p><p>{job.work_summary}</p>
      <ul>{job.declared_actions?.map((action, n) => <li key={n}>{action}</li>)}</ul><p>{job.result}</p>
      <p className="small muted">{job.result_scope === 'team' ? 'Результат команды' : 'Индивидуальный результат'} · не проверен</p></section>) : <p>История не указана; отсутствие данных не означает отсутствие опыта.</p>}
    <h3>Проекты · не проверены</h3>
    {d.projects?.length ? d.projects.map((project, i) => <section className="market-history" key={i}>
      <h4>{project.title}</h4><p>{project.problem}</p><p>Роль: {project.my_role}</p><ul>{project.actions?.map((action, n) => <li key={n}>{action}</li>)}</ul>
      <p>{project.stack?.join(', ')}</p><p>{project.result}</p></section>) : <p>Проекты не указаны.</p>}
    {d.achievement_story && <><h3>Рассказ о достижении · вымышленный</h3><p>{d.achievement_story.context}</p><p>{d.achievement_story.personal_contribution}</p>
      <p>{d.achievement_story.decision}</p><p>{d.achievement_story.outcome}</p><p className="small muted">{d.achievement_story.result_scope === 'team' ? 'Результат команды' : 'Личный результат'} · {d.achievement_story.basis}</p>
      {d.achievement_story.metric_notice && <p className="notice info">{d.achievement_story.metric_notice}</p>}</>}
    <h3>Образование</h3>{d.education?.length ? d.education.map((item, i) => <p key={i}>{item.institution} · {item.program} · {item.period}</p>) : <p>Не указано, а не «образования нет».</p>}
    <h3>Языки</h3>{d.languages?.length ? <p>{d.languages.map(item => `${item.language} · ${item.level}`).join('; ')}</p> : <p>Не указаны.</p>}
    <h3>Сертификаты</h3>{d.certificates?.length ? d.certificates.map((item, i) => <p key={i}>{item.title || item.name} · {item.issuer}</p>) : <p>Не указаны; наличие не проверялось.</p>}
  </div>
}

function Vacancy({ details: d }: { details: Details }) {
  return <div data-testid="market-vacancy"><p>{d.team_context}</p><p>{d.description}</p><h3>Рабочие задачи</h3><ul>{d.responsibilities?.map((item, i) => <li key={i}>{item}</li>)}</ul>
    <h3>Ожидаемый результат · пример</h3><ul>{d.expected_results?.map((item, i) => <li key={i}>{item}</li>)}</ul><h3>Первые 30 дней</h3><p>{d.first_30_days}</p>
    <h3>Этапы общения</h3><ul>{d.interview_stages?.map((item, i) => <li key={i}>{item.name} · {item.duration_minutes} мин.</li>)}</ul>
    <p>Тестовое: {d.take_home_minutes} мин. · Ответ: в течение {d.response_sla_hours} ч.</p></div>
}

export default function DemoMarket({ viewer }: { viewer: 'candidate' | 'employer' }) {
  const initial = new URLSearchParams(location.search)
  const [kind, setKind] = useState<'profile' | 'vacancy'>(viewer === 'employer' && initial.get('demo_market') !== 'vacancies' ? 'profile' : 'vacancy')
  const [filters, setFilters] = useState<Filters>(() => ({ family: initial.get('market_family')?.slice(0, 64) || '',
    level: levels[initial.get('market_level') || ''] ? initial.get('market_level')! : '',
    format: formats[initial.get('market_format') || ''] ? initial.get('market_format')! : '', q: initial.get('market_q')?.slice(0, 120) || '' }))
  const [draft, setDraft] = useState(filters)
  const [offset, setOffset] = useState(() => Math.min(100000, Math.max(0, Math.floor(Number(initial.get('market_offset')) || 0))))
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [page, setPage] = useState<MarketPage | null>(null)
  const [selected, setSelected] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [roleOptions, setRoleOptions] = useState<Card[]>([])
  const [vacancyId, setVacancyId] = useState('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [retry, setRetry] = useState(0)
  const collection = kind === 'profile' ? 'profiles' : 'vacancies'
  const query = new URLSearchParams({ ...(filters.family ? { family: filters.family } : {}), ...(filters.level ? { level: filters.level } : {}),
    ...(filters.format ? { work_format: filters.format } : {}), q: filters.q, offset: String(offset), limit: '20' }).toString()
  useEffect(() => {
    const controller = new AbortController()
    api<Catalog>('/demo-market/catalog', 'GET', undefined, { signal: controller.signal }).then(setCatalog)
      .catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [retry])
  useEffect(() => {
    const url = new URL(location.href)
    url.searchParams.set('demo_market', collection)
    for (const [key, value] of Object.entries({ family: filters.family, level: filters.level, format: filters.format, q: filters.q, offset: offset ? String(offset) : '' })) {
      if (value) url.searchParams.set(`market_${key}`, value); else url.searchParams.delete(`market_${key}`)
    }
    history.replaceState(null, '', url)
    const controller = new AbortController()
    setPage(null); setError('')
    api<MarketPage>(`/demo-market/${collection}?${query}`, 'GET', undefined, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return
        if (offset && offset >= data.total) setOffset(data.total ? Math.floor((data.total - 1) / 20) * 20 : 0)
        else setPage(data)
      }).catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [collection, query, retry])
  useEffect(() => {
    const controller = new AbortController()
    setDetail(null); setDetailError(''); setRoleOptions([]); setVacancyId(''); setComparison(null)
    if (selected) api<Detail>(`/demo-market/${collection}/${selected}`, 'GET', undefined, { signal: controller.signal })
      .then(async result => {
        if (controller.signal.aborted) return
        setDetail(result)
        if (kind === 'profile') {
          const roles = await api<MarketPage>(`/demo-market/vacancies?family=${encodeURIComponent(result.card.family_id)}&limit=40`, 'GET', undefined, { signal: controller.signal })
          if (!controller.signal.aborted) setRoleOptions(roles.items)
        }
      }).catch(err => { if (!controller.signal.aborted) setDetailError(err.message) })
    return () => controller.abort()
  }, [selected, collection, retry])
  useEffect(() => {
    const controller = new AbortController()
    setComparison(null)
    if (selected && vacancyId) api<Comparison>(`/demo-market/vacancies/${vacancyId}/compare/${selected}`, 'GET', undefined, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setComparison(data) }).catch(err => { if (!controller.signal.aborted) setDetailError(err.message) })
    return () => controller.abort()
  }, [selected, vacancyId])
  useEffect(() => {
    if (!selected) return
    const onEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelected('') }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [selected])
  return <div data-testid="demo-market">
    <div className="page-heading"><p className="eyebrow">ВЫМЫШЛЕННЫЙ IT-РЫНОК</p><h1>Рынок · демо</h1><p>{catalog ? `${catalog.profiles} резюме · ${catalog.vacancies} вакансий · ${catalog.families.length} направлений` : 'Загружаем каталог…'}</p></div>
    <div className="notice info">Все персонажи, компании, достижения и зарплаты вымышлены. Навыки и уровни заявлены, тест не пройден. Здесь нет реальных вакансий и контактов.</div>
    {viewer === 'employer' && <div className="segmented market-kind"><button aria-pressed={kind === 'profile'} className={kind === 'profile' ? 'active' : ''} onClick={() => { setKind('profile'); setOffset(0); setSelected('') }}>Резюме</button>
      <button aria-pressed={kind === 'vacancy'} className={kind === 'vacancy' ? 'active' : ''} onClick={() => { setKind('vacancy'); setOffset(0); setSelected('') }}>Демо-вакансии</button></div>}
    <form className="card market-filters" onSubmit={event => { event.preventDefault(); setFilters(draft); setOffset(0); setSelected('') }}>
      <label>Направление рынка<select value={draft.family} onChange={event => setDraft({ ...draft, family: event.target.value })}><option value="">Все направления</option>
        {catalog?.families.map(family => <option key={family.id} value={family.id}>{family.name}</option>)}</select></label>
      <label>Заявленный уровень<select value={draft.level} onChange={event => setDraft({ ...draft, level: event.target.value })}><option value="">Все уровни</option>{Object.entries(levels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label>Формат в примере<select value={draft.format} onChange={event => setDraft({ ...draft, format: event.target.value })}><option value="">Любой формат</option>{Object.entries(formats).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label>Навык или текст<input value={draft.q} maxLength={120} onChange={event => setDraft({ ...draft, q: event.target.value })} placeholder="Python, Kafka, контроль качества"/></label>
      <button className="primary">Применить фильтры</button><button className="button subtle" type="button" onClick={() => { setDraft(empty); setFilters(empty); setOffset(0); setSelected('') }}>Сбросить фильтры</button>
    </form>
    {error ? <div className="notice bad" role="alert">{error} <button className="button subtle" onClick={() => setRetry(value => value + 1)}>Повторить загрузку</button></div> : !page ? <p role="status">Загружаем примеры…</p> : <>
      <p className="muted" data-testid="market-count">Найдено: {page.total}. Показаны {page.total ? offset + 1 : 0}–{Math.min(offset + page.items.length, page.total)}.</p>
      {page.items.length ? <div className="candidate-grid">{page.items.map(card => <article className="card market-card" data-testid="market-card" data-record-id={card.id} key={card.id}>
        <p className="eyebrow">СИНТЕТИКА · НЕ ПРОВЕРЕНО</p><h2>{card.title}</h2><p className="small muted">{card.family_name} · {levels[card.level]} — {card.kind === 'profile' ? 'самоописание' : 'требование в примере'}</p>
        <p>{card.work_formats.map(format => formats[format]).join(' / ')}{card.city && ` · ${card.city}`}</p><p>{money(card.salary_min)} — {money(card.salary_max)} <small>в месяц · до налогов · вымышлено</small></p>
        <p>{card.summary}</p><p className="small muted">Навыки {card.kind === 'profile' ? 'заявлены' : 'требуются в примере'}: {card.skills.join(', ')}</p>
        <button className="button outline" onClick={() => setSelected(card.id)}>{card.kind === 'profile' ? 'Читать резюме' : 'Условия демо-вакансии'}</button></article>)}</div>
        : <div className="empty card">Таких примеров нет. Сбросьте фильтры или выберите другое направление.</div>}
      <nav className="market-pages" aria-label="Страницы демо-рынка"><button className="button outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Предыдущие примеры</button>
        <button className="button outline" disabled={offset + page.limit >= page.total} onClick={() => setOffset(offset + 20)}>Следующие примеры</button></nav>
    </>}
    {selected && <div className="modal-backdrop" onClick={() => setSelected('')}><section className="modal card market-modal" role="dialog" aria-modal="true" aria-labelledby="market-detail-title" onClick={event => event.stopPropagation()}>
      <button className="close" autoFocus aria-label="Закрыть пример" onClick={() => setSelected('')}>×</button><p className="eyebrow">СИНТЕТИЧЕСКИЙ ПРИМЕР · НЕ ПРОВЕРЕНО</p><h2 id="market-detail-title">{detail?.card.title || 'Загрузка примера…'}</h2>
      {detailError && <p role="alert">{detailError}</p>}
      {detail && <><p className="notice info">Только учебный пример. Контакты отсутствуют; тестовый грейд не присвоен.</p>
        <p>{detail.card.family_name} · {levels[detail.card.level]} · {detail.card.work_formats.map(format => formats[format]).join(' / ')} {detail.card.city}</p>
        <p>Заявленный диапазон: {money(detail.card.salary_min)} — {money(detail.card.salary_max)} · вымышленный</p><p>Навыки: {detail.card.skills.join(', ')}</p>
        {detail.card.kind === 'profile' ? <><Resume details={detail.details}/><section className="market-comparison"><h3>Сравнить заявленные условия</h3>
          <label>Демо-вакансия для сравнения<select value={vacancyId} onChange={event => setVacancyId(event.target.value)}><option value="">Выберите пример</option>{roleOptions.map(role => <option key={role.id} value={role.id}>{role.title}</option>)}</select></label>
          {comparison && <div data-testid="market-comparison"><p>{comparison.notice}</p><strong>{comparison.status === 'compatible' ? 'Заявленные условия совпадают' : comparison.status === 'incompatible' ? 'Есть расхождения в заявленных условиях' : 'Недостаточно данных'}</strong>
            <ul>{comparison.checks.map(check => <li key={check.field}><strong>{check.passed === null ? 'Неизвестно' : check.passed ? 'Совпадает' : 'Расходится'}: {check.label}</strong><p className="small muted">{check.explanation}</p></li>)}</ul>
            <p>Перечислены в резюме: {comparison.matched_skills.join(', ') || 'нет данных'}</p><p>Не указаны: {comparison.missing_skills.join(', ') || 'все перечислены'}</p></div>}
        </section></> : <Vacancy details={detail.details}/>}</>}
    </section></div>}
  </div>
}
