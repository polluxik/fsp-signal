import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'

type User = { id: string; email: string; role: 'candidate' | 'employer'; email_verified: boolean }
type Profile = {
  full_name: string; contact_email: string; contact_phone: string; city: string; summary: string;
  skills: string[]; experience_months: number; min_salary_rub: number; work_format: string;
  consent_processing: boolean; published: boolean; available: boolean;
  verified_specialization?: string | null; verified_grade?: string | null; test_score?: number | null;
  competencies?: Record<string, number>; fsp_status?: string; fsp_result?: string | null;
  next_grade_change_at?: string | null
}
type Question = { id: string; competency: string; prompt: string; points: number; phase: number;
  type: 'choice' | 'number'; options?: { value: string; label: string }[] }
type Attempt = { id: string; phase: number; state: string; score?: number; outcome?: string;
  questions: Question[]; answers: Record<string, string | number>; verified_category?: string }
type Need = { id: string; title: string; description: string; specialization: string; grade: string;
  salary_min_rub: number; salary_max_rub: number; work_format: string; competencies: string[] }
type Match = { score: number; components: Record<string, number>; reasons: string[]; gaps: string[] }
type Candidate = { id: string; alias: string; specialization: string; grade: string; test_score: number;
  competencies: Record<string, number>; skills_declared: string[]; fsp_status: string;
  fsp_result?: string | null; bank_score?: number; match?: Match; verification_source?: string }
type SearchSummary = { id: string; need_id: string; parent_snapshot_id: string | null;
  created_at: string; result_count: number; filters: { fsp_only: boolean; stack: string[] } }
type Search = Omit<SearchSummary, 'result_count'> & { results: Candidate[]; unavailable_count: number }
type Invite = { id: string; candidate_id: string; company_name: string; offer_text: string; reason: string;
  employer_contact: string; salary_min_rub: number; salary_max_rub: number; state: string;
  expires_at: string; work_format: string }

const skillNames: Record<string, string> = {
  data_trace: 'Данные и трассировка', validation: 'Валидация', http_api: 'HTTP API',
  event_idempotency: 'Повторные события', data_integrity: 'Целостность данных',
  failure_recovery: 'Обработка отказов', javascript_trace: 'JavaScript',
  ui_state: 'Состояние интерфейса', forms: 'Формы', request_races: 'Гонки запросов',
  derived_state: 'Производное состояние', error_recovery: 'Ошибки интерфейса',
}
const skillsByCategory: Record<string, string[]> = {
  'backend:junior': ['data_trace', 'validation', 'http_api'],
  'backend:middle': ['event_idempotency', 'data_integrity', 'failure_recovery'],
  'frontend:junior': ['javascript_trace', 'ui_state', 'forms'],
  'frontend:middle': ['request_races', 'derived_state', 'error_recovery'],
}
const emptyProfile: Profile = {
  full_name: '', contact_email: '', contact_phone: '', city: '', summary: '', skills: [],
  experience_months: 0, min_salary_rub: 0, work_format: 'remote', consent_processing: false,
  published: false, available: true,
}

function csrfToken(): string {
  return document.cookie.split('; ').find(item => item.startsWith('fsp_csrf='))?.split('=')[1] ?? ''
}
async function api<T>(path: string, method = 'GET', body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const headers: Record<string, string> = { ...extraHeaders }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken()) headers['x-csrf-token'] = decodeURIComponent(csrfToken())
  const response = await fetch(`/api/v1${path}`, { method, headers, credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body) })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const messages: Record<string, string> = {
      LOGIN_REQUIRED: 'Войдите в аккаунт', EMAIL_NOT_VERIFIED: 'Сначала подтвердите email',
      INVALID_CREDENTIALS: 'Неверный email или пароль', CONSENT_REQUIRED: 'Нужно согласие на обработку данных',
      ASSESSMENT_ATTEMPT_LIMIT: 'Лимит: три попытки за семь дней',
      ASSESSMENT_RETRY_COOLDOWN: 'Повтор этого теста доступен через 72 часа',
      GRADE_CHANGE_COOLDOWN: 'Смена грейда доступна через 30 дней после предыдущей',
      ANSWERS_INCOMPLETE: 'Ответьте на все вопросы', SALARY_RANGE_INVALID: 'Проверьте зарплатный диапазон и ожидания кандидата',
      ACTIVE_INVITATION_EXISTS: 'У вашей компании уже есть активное приглашение этому кандидату',
      CONTACT_LOCKED: 'Контакты откроются после принятия приглашения',
      ORIGIN_FORBIDDEN: 'Некорректный адрес приложения; проверьте PUBLIC_BASE_URL сервера',
    }
    throw new Error(typeof detail === 'string' ? (messages[detail] ?? detail) : `Ошибка ${response.status}`)
  }
  return data as T
}
async function uploadResume(file: File): Promise<Pick<Profile, 'full_name' | 'contact_email' | 'contact_phone' | 'summary' | 'skills' | 'experience_months'> & { warnings: string[]; pages: number }> {
  const body = new FormData(); body.append('file', file)
  const response = await fetch('/api/v1/candidate/resume/preview', { method: 'POST', body,
    credentials: 'same-origin', headers: { 'x-csrf-token': decodeURIComponent(csrfToken()) } })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const messages: Record<string,string> = {
      PDF_TOO_LARGE: 'PDF больше 5 МБ', NOT_A_PDF: 'Выберите PDF-файл',
      PDF_ENCRYPTED: 'PDF защищён паролем', PDF_PAGE_LIMIT: 'Допускается PDF до 10 страниц',
      PDF_UNREADABLE: 'Не удалось прочитать PDF', PDF_TEXT_NOT_FOUND: 'В PDF нет текстового слоя. Заполните форму вручную.',
    }
    throw new Error(messages[data?.detail] ?? data?.detail ?? `Ошибка ${response.status}`)
  }
  return data
}
function rubles(value: number): string { return new Intl.NumberFormat('ru-RU').format(value) + ' ₽' }
function fmtDate(value: string): string { return new Date(value).toLocaleDateString('ru-RU') }
function fmtMoment(value: string): string { return new Date(value).toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit' }) }
function statusName(value: string): string {
  return ({ sent: 'Отправлено', viewed: 'Просмотрено', accepted: 'Принято', rejected: 'Отклонено',
    withdrawn: 'Отозвано', expired: 'Истекло' } as Record<string, string>)[value] ?? value
}
function CategoryBadge({ spec, grade }: { spec?: string | null; grade?: string | null }) {
  return <span className="badge purple">{spec && grade ? `${spec.toUpperCase()} · ${grade.toUpperCase()}` : 'Категория не подтверждена'}</span>
}
function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'bad' | 'good' }) {
  return <div className={`notice ${tone}`} role="status">{children}</div>
}

function Auth({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('register')
  const [role, setRole] = useState<'candidate' | 'employer'>('candidate')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('')
    try {
      if (mode === 'register') {
        await api('/auth/register', 'POST', { email, password, role })
        setMessage('Письмо для подтверждения отправлено. Перейдите по ссылке, затем войдите.')
        setMode('login')
      } else {
        await api('/auth/login', 'POST', { email, password }); onLogin()
      }
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <main className="landing">
    <section className="hero">
      <div className="hero-mark">ФСП <span>СИГНАЛ</span></div>
      <p className="eyebrow">ОБРАТНЫЙ НАЙМ ДЛЯ ИТ</p>
      <h1>Знания видны.<br/><em>Предложение приходит к вам.</em></h1>
      <p className="hero-copy">Проверяемые навыки вместо саморекламы. Компания показывает, почему выбрала вас, и сразу называет зарплату.</p>
      <div className="hero-steps"><span>01 Тест навыков</span><span>02 Подбор по фактам</span><span>03 Приглашение с условиями</span></div>
    </section>
    <section className="auth-card card">
      <div className="segmented"><button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Регистрация</button><button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Вход</button></div>
      <h2>{mode === 'register' ? 'Начнём знакомство' : 'С возвращением'}</h2>
      <p className="muted">{mode === 'register' ? 'Создайте профиль и подтвердите адрес почты.' : 'Продолжите работу в своём кабинете.'}</p>
      {message && <Notice tone="good">{message}</Notice>}{error && <Notice tone="bad">{error}</Notice>}
      <form onSubmit={submit}>
        {mode === 'register' && <div className="role-choice"><label><input type="radio" checked={role === 'candidate'} onChange={() => setRole('candidate')}/> Я кандидат</label><label><input type="radio" checked={role === 'employer'} onChange={() => setRole('employer')}/> Я работодатель</label></div>}
        <label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required/></label>
        <label>Пароль<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={10} required/></label>
        <button className="primary wide" disabled={busy}>{busy ? 'Подождите…' : mode === 'register' ? 'Создать профиль' : 'Войти'}</button>
      </form>
      <p className="small muted">Локальная демонстрация использует синтетические данные ФСП.</p>
    </section>
  </main>
}

function Verify({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState('Проверяем ссылку…')
  const invoked = useRef(false)
  useEffect(() => {
    if (invoked.current) return
    invoked.current = true
    const token = new URLSearchParams(location.search).get('token')
    if (!token) { setStatus('Ссылка не содержит токен.'); return }
    api('/auth/verify-email', 'POST', { token }).then(() => setStatus('Адрес подтверждён. Теперь войдите.'))
      .catch(error => setStatus(`Не удалось подтвердить адрес: ${error.message}`))
  }, [])
  return <div className="centered card"><div className="logo">ФСП СИГНАЛ</div><h1>Подтверждение почты</h1><Notice>{status}</Notice><button className="primary" onClick={() => { history.replaceState(null, '', '/'); onDone() }}>На страницу входа</button></div>
}

function CandidateApp({ me }: { me: User }) {
  const [tab, setTab] = useState('profile')
  const [profile, setProfile] = useState<Profile>(emptyProfile)
  const [skillsText, setSkillsText] = useState('')
  const [invites, setInvites] = useState<Invite[]>([])
  const [history, setHistory] = useState<{ id: string; category: string; state: string; score: number | null; outcome: string | null; started_at: string }[]>([])
  const [grants, setGrants] = useState<{ id: string; employer_id: string; revoked_at: string | null }[]>([])
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [spec, setSpec] = useState('backend')
  const [grade, setGrade] = useState('junior')
  const [fspId, setFspId] = useState(`demo-${me.id}`)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState('')
  const [importWarnings, setImportWarnings] = useState<string[]>([])
  const [importBusy, setImportBusy] = useState(false)
  async function load() {
    const [p, i, g, h] = await Promise.all([
      api<Profile | null>('/candidate/profile'), api<Invite[]>('/candidate/invitations'),
      api<typeof grants>('/candidate/contact-grants'), api<typeof history>('/candidate/assessment-history'),
    ])
    if (p) { setProfile(p); setSkillsText((p.skills || []).join(', ')) }
    setInvites(i); setGrants(g); setHistory(h)
  }
  useEffect(() => { load().catch(err => setError(err.message)) }, [])
  async function action(job: () => Promise<unknown>, success: string) {
    setError(''); setFeedback('')
    try { await job(); await load(); setFeedback(success) } catch (err) { setError((err as Error).message) }
  }
  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    await action(() => api('/candidate/profile', 'PUT', { ...profile,
      skills: skillsText.split(',').map(item => item.trim()).filter(Boolean) }), 'Профиль сохранён')
  }
  async function importResume(file?: File) {
    if (!file) return
    setError(''); setFeedback(''); setImportWarnings([]); setImportBusy(true)
    try {
      const draft = await uploadResume(file)
      setProfile(current => ({...current, full_name: draft.full_name || current.full_name,
        contact_email: draft.contact_email || current.contact_email,
        contact_phone: draft.contact_phone || current.contact_phone,
        summary: draft.summary || current.summary,
        experience_months: draft.experience_months || current.experience_months }))
      if (draft.skills.length) setSkillsText(draft.skills.join(', '))
      setImportWarnings(draft.warnings)
      setFeedback(`Извлечён черновик из PDF (${draft.pages} стр.). Проверьте поля и нажмите «Сохранить профиль».`)
    } catch (err) { setError((err as Error).message) } finally { setImportBusy(false) }
  }
  async function startTest() {
    setError(''); setFeedback('')
    try { const result = await api<Attempt>('/candidate/assessment-attempts', 'POST', { industry:'it', specialization: spec, grade });
      setAttempt(result); setAnswers({}); setTab('test') } catch (err) { setError((err as Error).message) }
  }
  async function resumeTest(id: string) {
    setError('')
    try { const result = await api<Attempt>(`/candidate/assessment-attempts/${id}`)
      setAttempt(result); setAnswers(Object.fromEntries(Object.entries(result.answers || {}).map(([key,value]) => [key,String(value)]))) }
    catch (err) { setError((err as Error).message) }
  }
  async function progressTest() {
    if (!attempt) return
    setError(''); setFeedback('')
    try {
      const current = attempt.questions.filter(q => q.phase === attempt.phase)
      if (current.some(q => answers[q.id] === undefined || answers[q.id] === '')) {
        throw new Error('Ответьте на все вопросы текущего этапа')
      }
      const currentAnswers = Object.fromEntries(current.map(q => [q.id, answers[q.id]]))
      await api(`/candidate/assessment-attempts/${attempt.id}/answers`, 'PUT', { answers: currentAnswers })
      const updated = await api<Attempt>(`/candidate/assessment-attempts/${attempt.id}/${attempt.phase === 1 ? 'advance' : 'submit'}`, 'POST')
      setAttempt(updated)
      if (updated.state === 'scored') { await load(); setFeedback(updated.outcome === 'passed' ? 'Категория подтверждена' : 'Тест не пройден. Ваш прежний подтверждённый грейд сохранён.') }
    } catch (err) { setError((err as Error).message) }
  }
  return <div className="workspace">
    <header className="topbar"><span className="logo">ФСП <strong>СИГНАЛ</strong></span><span className="top-id">{me.email}</span></header>
    <div className="shell"><aside className="sidebar"><p className="overline">КАБИНЕТ КАНДИДАТА</p>
      {[['profile','Мой профиль'],['test','Проверка навыков'],['offers','Приглашения'],['fsp','ФСП ID и доступ']].map(([id, label]) =>
        <button key={id} className={tab === id ? 'active' : ''} onClick={() => { setTab(id); setError(''); setFeedback('') }}>{label}</button>)}
      <div className="sidebar-bottom"><CategoryBadge spec={profile.verified_specialization} grade={profile.verified_grade}/><p className="small muted">Контакты открываются только по вашему решению.</p></div>
    </aside><main className="content">
      {error && <Notice tone="bad">{error}</Notice>}{feedback && <Notice tone="good">{feedback}</Notice>}
      {tab === 'profile' && <><div className="page-heading"><p className="eyebrow">ПАСПОРТ НАВЫКОВ</p><h1>Пусть навыки говорят за вас</h1><p>Работодатель увидит категорию после теста. Контакты остаются закрытыми до принятия приглашения.</p></div>
        <div className="summary-grid"><div className="metric"><span>Категория</span><CategoryBadge spec={profile.verified_specialization} grade={profile.verified_grade}/></div><div className="metric"><span>Результат теста</span><strong>{profile.test_score ?? '—'}<small>{profile.test_score != null ? ' / 100' : ''}</small></strong></div><div className="metric"><span>ФСП</span><strong>{profile.fsp_status === 'mock' ? 'Демо' : 'Нет истории'}</strong></div></div>
        <section className="card"><div className="section-title"><div><h2>Профиль кандидата</h2><p className="muted">Заявленные навыки отмечены отдельно от результата теста.</p></div>{profile.verified_grade && <a className="button subtle" href="/api/v1/candidate/passport.pdf">Скачать PDF</a>}</div>
          <label>Загрузить PDF-резюме для заполнения черновика<input type="file" accept="application/pdf,.pdf" disabled={importBusy} onChange={e => { void importResume(e.target.files?.[0]); e.target.value = '' }}/></label>
          <p className="small muted">До 5 МБ и 10 страниц, только PDF с текстовым слоем. Файл не сохраняется; импорт не публикует профиль.</p>
          {importWarnings.map((warning, index) => <p className="small muted" key={index}>{warning}</p>)}
          <form className="form-grid" onSubmit={saveProfile}>
            <label>Имя и фамилия<input value={profile.full_name} onChange={e => setProfile({...profile,full_name:e.target.value})} required/></label>
            <label>Контактный email<input type="email" value={profile.contact_email} onChange={e => setProfile({...profile,contact_email:e.target.value})} required/></label>
            <label>Телефон<input value={profile.contact_phone} onChange={e => setProfile({...profile,contact_phone:e.target.value})}/></label>
            <label>Город<input value={profile.city} onChange={e => setProfile({...profile,city:e.target.value})}/></label>
            <label>Навыки через запятую <span className="hint">заявлено</span><input value={skillsText} onChange={e => setSkillsText(e.target.value)} placeholder="Python, PostgreSQL"/></label>
            <label>Опыт, месяцев<input type="number" min="0" value={profile.experience_months} onChange={e => setProfile({...profile,experience_months:Number(e.target.value)})}/></label>
            <label>Минимальная зарплата, ₽/мес. до налогов<input type="number" min="0" value={profile.min_salary_rub} onChange={e => setProfile({...profile,min_salary_rub:Number(e.target.value)})}/></label>
            <label>Формат<select value={profile.work_format} onChange={e => setProfile({...profile,work_format:e.target.value})}><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option><option value="any">Любой</option></select></label>
            <label className="full">Опыт и задачи<textarea rows={4} value={profile.summary} onChange={e => setProfile({...profile,summary:e.target.value})}/></label>
            <div className="full check-list"><label><input type="checkbox" checked={profile.consent_processing} onChange={e => setProfile({...profile,consent_processing:e.target.checked,published:e.target.checked ? profile.published : false})}/> Согласен на обработку данных профиля</label><label><input type="checkbox" checked={profile.published} disabled={!profile.consent_processing} onChange={e => setProfile({...profile,published:e.target.checked})}/> Публиковать проверенный профиль работодателям</label><label><input type="checkbox" checked={profile.available} onChange={e => setProfile({...profile,available:e.target.checked})}/> Принимать приглашения</label></div>
            <div className="full"><button className="primary">Сохранить профиль</button></div>
          </form>
        </section></>}
      {tab === 'test' && <><div className="page-heading"><p className="eyebrow">ПРОВЕРКА НАВЫКОВ</p><h1>Категория, которую можно проверить</h1><p>Три группы практических вопросов, 20 минут. После первого этапа одно условие изменится. Ответы первого этапа будут зафиксированы.</p></div>
        {!attempt || attempt.state === 'scored' ? <section className="card"><h2>{attempt?.state === 'scored' ? `Результат: ${attempt.score} / 100` : 'Выберите направление'}</h2>{attempt?.state === 'scored' && <Notice tone={attempt.outcome === 'passed' ? 'good' : 'info'}>{attempt.outcome === 'passed' ? 'Категория подтверждена.' : 'Пока не подтверждено. Вы можете выбрать другой уровень по правилам попыток.'}</Notice>}
          <div className="form-grid"><label>Отрасль<select value="it" disabled><option value="it">Информационные технологии</option></select></label><label>Специализация<select value={spec} onChange={e => setSpec(e.target.value)}><option value="backend">Backend</option><option value="frontend">Frontend</option></select></label><label>Предполагаемый грейд<select value={grade} onChange={e => setGrade(e.target.value)}><option value="junior">Junior</option><option value="middle">Middle</option></select></label></div>
          <button className="primary" onClick={startTest}>Начать тест</button><p className="small muted">Порог: 70/100, половина баллов в каждой группе и верный ответ после изменения условия. Провал не понижает подтверждённый грейд.</p>{history.length > 0 && <div className="history"><h3>История тестов</h3>{history.map(item => <div className="grant" key={item.id}><span>{item.category} · {fmtDate(item.started_at)} · {item.state === 'scored' ? `${item.score}/100, ${item.outcome === 'passed' ? 'пройден' : 'не пройден'}` : 'в процессе'}</span>{item.state === 'in_progress' && <button className="button subtle" onClick={() => resumeTest(item.id)}>Продолжить</button>}</div>)}</div>}</section>
          : <section className="card"><div className="section-title"><div><h2>Этап {attempt.phase} из 2</h2><p className="muted">{attempt.phase === 1 ? 'Решите основные задания' : 'Изменилось одно условие. Старые ответы зафиксированы.'}</p></div><span className="badge">20 минут от начала попытки</span></div>
            {attempt.questions.filter(q => q.phase === attempt.phase).map((q, index) => <div className="question" key={q.id}><div className="question-top"><span>{index+1}. {skillNames[q.competency] ?? q.competency}</span><span>{q.points} баллов</span></div><p>{q.prompt}</p>{q.type === 'choice' ? <div className="options">{q.options?.map(o => <label key={o.value}><input type="radio" name={q.id} checked={answers[q.id] === o.value} onChange={() => setAnswers({...answers,[q.id]:o.value})}/>{o.label}</label>)}</div> : <input className="answer-input" type="number" aria-label={`Ответ на вопрос ${index+1}`} value={answers[q.id] ?? ''} onChange={e => setAnswers({...answers,[q.id]:e.target.value})}/>}</div>)}
            <button className="primary" onClick={progressTest}>{attempt.phase === 1 ? 'Зафиксировать ответы и продолжить' : 'Отправить на проверку'}</button></section>}
      </>}
    {tab === 'offers' && <><div className="page-heading"><p className="eyebrow">ПРЕДЛОЖЕНИЯ</p><h1>Компания делает первый шаг</h1><p>Условия и зарплата видны до раскрытия ваших контактов.</p></div>{invites.length === 0 ? <div className="empty card">Пока нет приглашений. Завершите тест и опубликуйте профиль, чтобы компании могли вас найти.</div> : invites.map(invite => <article className="card offer-card" key={invite.id}><div className="section-title"><div><span className="eyebrow">{invite.company_name}</span><h2>{invite.offer_text}</h2></div><span className={`badge ${invite.state === 'accepted' ? 'green' : ''}`}>{statusName(invite.state)}</span></div><div className="salary">{rubles(invite.salary_min_rub)} — {rubles(invite.salary_max_rub)} <small>/ месяц, до налогов</small></div><p><strong>Почему выбрали вас:</strong> {invite.reason}</p><p className="muted">Контакт работодателя: {invite.employer_contact} · предложение до {fmtDate(invite.expires_at)}</p>{['sent','viewed'].includes(invite.state) && <div className="actions"><button className="primary" onClick={() => action(() => api(`/invitations/${invite.id}/accept`, 'POST'), 'Приглашение принято. Контакты открыты только этой компании.')}>Принять и раскрыть контакты этой компании</button><button className="button subtle" onClick={() => action(() => api(`/invitations/${invite.id}/reject`, 'POST'), 'Приглашение отклонено')}>Отклонить</button></div>}</article>)}</>}
      {tab === 'fsp' && <><div className="page-heading"><p className="eyebrow">ИСТОЧНИК ДОСТИЖЕНИЙ</p><h1>Связь с ФСП ID</h1><p>История соревнований дополняет тест. Если истории нет, вы участвуете в подборе на равных.</p></div><section className="card"><h2>Состояние связи</h2><Notice>{profile.fsp_status === 'mock' ? 'Подключена демонстрационная запись. Это не реальный реестр ФСП.' : profile.fsp_status === 'unverified' ? 'ID введён, но принадлежность не подтверждена.' : 'ФСП ID не подключён.'}</Notice><label>ФСП ID<input value={fspId} onChange={e => setFspId(e.target.value)}/></label><p className="small muted">Для локальной демонстрации используйте ID: demo-{me.id}. Произвольный ID останется неподтверждённым.</p><div className="actions"><button className="primary" onClick={() => action(() => api('/candidate/fsp-link','POST',{participant_id:fspId}), 'Статус связи обновлён')}>Связать ID</button><button className="button subtle" onClick={() => action(() => api('/candidate/fsp-link','DELETE'), 'Связь удалена')}>Отключить</button></div></section><section className="card"><h2>Доступ компаний к контактам</h2>{grants.length === 0 ? <p className="muted">Никому не открыт.</p> : grants.map(grant => <div className="grant" key={grant.id}><span>Компания #{grant.employer_id.slice(0,8)} · {grant.revoked_at ? 'доступ отозван' : 'доступ открыт'}</span>{!grant.revoked_at && <button className="button subtle" onClick={() => action(() => api(`/candidate/contact-grants/${grant.id}/revoke`,'POST'), 'Доступ отозван')}>Отозвать</button>}</div>)}</section></>}
    </main></div>
  </div>
}

function EmployerApp({ me }: { me: User }) {
  const [tab, setTab] = useState('search')
  const [company, setCompany] = useState({ company_name:'', description:'', industry:'', contact_email:me.email })
  const [needs, setNeeds] = useState<Need[]>([])
  const [needId, setNeedId] = useState('')
  const [needForm, setNeedForm] = useState({ title:'', description:'', specialization:'backend', grade:'middle',
    competencies:[] as string[], stack:'', salary_min_rub:180000, salary_max_rub:230000, work_format:'remote' })
  const [search, setSearch] = useState<Search | null>(null)
  const [bank, setBank] = useState<Candidate[]>([])
  const [bankSpec, setBankSpec] = useState('')
  const [bankGrade, setBankGrade] = useState('')
  const [bankStack, setBankStack] = useState('')
  const [bankFsp, setBankFsp] = useState(false)
  const [fspOnly, setFspOnly] = useState(false)
  const [selected, setSelected] = useState<Candidate | null>(null)
  const [snapshots, setSnapshots] = useState<SearchSummary[]>([])
  const [offers, setOffers] = useState<Invite[]>([])
  const [offer, setOffer] = useState({ offer_text:'', reason:'', salary_min_rub:180000,
    salary_max_rub:230000, work_format:'remote', employer_contact:me.email })
  const [contact, setContact] = useState<Record<string,string> | null>(null)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  async function load() {
    const [c, n, o, b, h] = await Promise.all([api<typeof company | null>('/employer/company'),
      api<Need[]>('/employer/needs'), api<Invite[]>('/employer/invitations'),
      api<Candidate[]>('/employer/candidates'), api<SearchSummary[]>('/employer/searches')])
    if (c) setCompany(c)
    setNeeds(n); setOffers(o); setBank(b); setSnapshots(h)
    if (n.length) setNeedId(current => current || n[0].id)
  }
  useEffect(() => { load().catch(err => setError(err.message)) }, [])
  async function action(job: () => Promise<unknown>, success: string) {
    setError(''); setFeedback('')
    try { await job(); await load(); setFeedback(success) } catch (err) { setError((err as Error).message) }
  }
  async function saveCompany(event: FormEvent) { event.preventDefault(); await action(() => api('/employer/company','PUT',company), 'Профиль компании сохранён') }
  async function saveNeed(event: FormEvent) {
    event.preventDefault(); setError(''); setFeedback('')
    try {
      const result = await api<Need>('/employer/needs','POST',{...needForm, stack:needForm.stack.split(',').map(x => x.trim()).filter(Boolean)})
      setNeedId(result.id); await load(); setFeedback('Потребность создана. Теперь сформируйте подборку.'); setTab('search')
    } catch (err) { setError((err as Error).message) }
  }
  async function runSearch() {
    if (!needId) { setError('Сначала создайте потребность'); return }
    setError(''); setFeedback('')
    try { const result = await api<Search>('/employer/searches','POST',{need_id:needId, fsp_only:fspOnly,
      parent_snapshot_id:search?.need_id === needId ? search.id : null});
      setSearch(result); setSnapshots(await api<SearchSummary[]>('/employer/searches')); setTab('search') }
    catch (err) { setError((err as Error).message) }
  }
  async function restoreSearch(id: string) {
    setError('')
    try { const result = await api<Search>(`/employer/searches/${id}`)
      setSearch(result); setNeedId(result.need_id); setFspOnly(result.filters.fsp_only); setTab('search') }
    catch (err) { setError((err as Error).message) }
  }
  async function filterBank() {
    setError('')
    const params = new URLSearchParams()
    if (bankSpec) params.set('specialization', bankSpec)
    if (bankGrade) params.set('grade', bankGrade)
    if (bankStack) params.set('stack', bankStack)
    if (bankFsp) params.set('fsp_only', 'true')
    try { setBank(await api<Candidate[]>(`/employer/candidates?${params}`)) }
    catch (err) { setError((err as Error).message) }
  }
  function choose(candidate: Candidate) {
    setSelected(candidate); setContact(null)
    const need = needs.find(n => n.id === needId)
    setOffer({ offer_text:`Приглашаем обсудить роль ${need?.title ?? 'в нашей команде'} и задачи команды.`,
      reason:candidate.match?.reasons?.slice(0,2).join('. ') ?? `Подтверждена категория ${candidate.specialization} ${candidate.grade}.`,
      salary_min_rub:need?.salary_min_rub ?? 180000, salary_max_rub:need?.salary_max_rub ?? 230000,
      work_format:need?.work_format ?? 'remote', employer_contact:company.contact_email || me.email })
    setTab('search')
  }
  async function sendInvite(event: FormEvent) {
    event.preventDefault(); if (!selected) return
    setError(''); setFeedback('')
    try {
      await api('/employer/invitations','POST',{...offer,candidate_id:selected.id,need_id:needId || null},
        {'Idempotency-Key':crypto.randomUUID()})
      setSelected(null); await load(); setFeedback('Приглашение отправлено')
    } catch (err) { setError((err as Error).message) }
  }
  async function showContact(candidateId: string) {
    setError(''); setContact(null)
    try { setContact(await api<Record<string,string>>(`/employer/candidates/${candidateId}/contact`)) }
    catch (err) { setError((err as Error).message) }
  }
  function CandidateCard({ candidate }: { candidate: Candidate }) {
    return <article className="candidate-card card"><div className="section-title"><div><p className="eyebrow">{candidate.verification_source === 'synthetic_fixture' ? 'СИНТЕТИЧЕСКИЙ ПРОФИЛЬ' : 'ПРОВЕРЕННЫЙ ПРОФИЛЬ'}</p><h3>{candidate.alias}</h3></div><span className="match-score">{candidate.match ? `${candidate.match.score}/100` : `${candidate.bank_score}/100`}</span></div><CategoryBadge spec={candidate.specialization} grade={candidate.grade}/><div className="evidence-row"><span>{candidate.verification_source === 'synthetic_fixture' ? 'Учебный балл' : 'Тест'}: <strong>{candidate.test_score}/100</strong></span><span>ФСП: {candidate.fsp_status === 'mock' ? 'демо-достижение' : 'нет подтверждения'}</span></div><p className="small muted">Стек заявлен: {candidate.skills_declared?.join(', ') || '—'}</p>{candidate.match && <><ul className="reasons">{candidate.match.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>{candidate.match.gaps.length > 0 && <p className="gap">{candidate.match.gaps.join('; ')}</p>}</>}<button className="button outline" onClick={() => choose(candidate)}>Пригласить с зарплатой →</button></article>
  }
  return <div className="workspace"><header className="topbar"><span className="logo">ФСП <strong>СИГНАЛ</strong></span><span className="top-id">{company.company_name || me.email}</span></header><div className="shell"><aside className="sidebar"><p className="overline">КАБИНЕТ РАБОТОДАТЕЛЯ</p>{[['search','Найти специалиста'],['need','Потребность команды'],['bank','Банк кандидатов'],['offers','Приглашения'],['company','Компания']].map(([id,label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => {setTab(id);setSelected(null);setError('');setFeedback('')}}>{label}</button>)}<div className="sidebar-bottom"><p className="small muted">В этой демонстрации достижения ФСП синтетические.</p></div></aside><main className="content">
    {error && <Notice tone="bad">{error}</Notice>}{feedback && <Notice tone="good">{feedback}</Notice>}
    {tab === 'company' && <><div className="page-heading"><p className="eyebrow">КОМПАНИЯ</p><h1>Кто приглашает кандидата?</h1><p>Название и способ связи будут указаны в каждом предложении.</p></div><section className="card"><form className="form-grid" onSubmit={saveCompany}><label>Название компании<input value={company.company_name} onChange={e => setCompany({...company,company_name:e.target.value})} required/></label><label>Направление деятельности<input value={company.industry} onChange={e => setCompany({...company,industry:e.target.value})}/></label><label className="full">О команде<textarea rows={4} value={company.description} onChange={e => setCompany({...company,description:e.target.value})}/></label><label>Контактный email<input type="email" value={company.contact_email} onChange={e => setCompany({...company,contact_email:e.target.value})} required/></label><div className="full"><button className="primary">Сохранить компанию</button></div></form></section></>}
    {tab === 'need' && <><div className="page-heading"><p className="eyebrow">ЗАДАЧА КОМАНДЫ</p><h1>Кого вы ищете?</h1><p>Опишите рабочую задачу. Подбор строится по подтверждённой категории и результатам теста.</p></div><section className="card"><form className="form-grid" onSubmit={saveNeed}><label>Название роли<input value={needForm.title} onChange={e => setNeedForm({...needForm,title:e.target.value})} placeholder="Backend Middle" required/></label><label>Специализация<select value={needForm.specialization} onChange={e => setNeedForm({...needForm,specialization:e.target.value,competencies:[]})}><option value="backend">Backend</option><option value="frontend">Frontend</option></select></label><label>Грейд<select value={needForm.grade} onChange={e => setNeedForm({...needForm,grade:e.target.value,competencies:[]})}><option value="junior">Junior</option><option value="middle">Middle</option></select></label><label>Формат<select value={needForm.work_format} onChange={e => setNeedForm({...needForm,work_format:e.target.value})}><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option><option value="any">Любой</option></select></label><label className="full">Чем будет заниматься специалист<textarea rows={4} value={needForm.description} onChange={e => setNeedForm({...needForm,description:e.target.value})} required placeholder="Например: обеспечить корректную обработку повторных событий"/></label><div className="full"><p className="field-heading">Проверяемые компетенции</p><div className="checks">{skillsByCategory[`${needForm.specialization}:${needForm.grade}`].map(skill => <label key={skill}><input type="checkbox" checked={needForm.competencies.includes(skill)} onChange={e => setNeedForm({...needForm,competencies:e.target.checked ? [...needForm.competencies,skill] : needForm.competencies.filter(x => x !== skill)})}/>{skillNames[skill]}</label>)}</div></div><label>Стек через запятую <span className="hint">заявлено</span><input value={needForm.stack} onChange={e => setNeedForm({...needForm,stack:e.target.value})} placeholder="Python, PostgreSQL"/></label><label>Зарплата от, ₽/мес. до налогов<input type="number" min="1" value={needForm.salary_min_rub} onChange={e => setNeedForm({...needForm,salary_min_rub:Number(e.target.value)})}/></label><label>Зарплата до, ₽/мес. до налогов<input type="number" min="1" value={needForm.salary_max_rub} onChange={e => setNeedForm({...needForm,salary_max_rub:Number(e.target.value)})}/></label><div className="full"><button className="primary">Сохранить потребность</button></div></form></section></>}
    {tab === 'search' && <><div className="page-heading"><p className="eyebrow">ОБРАТНЫЙ НАЙМ</p><h1>Найдите человека по тому, что он умеет</h1><p>Компания делает первый шаг. Сначала подтверждённые навыки и зарплата, потом контакт.</p></div><section className="search-bar card"><label>Потребность<select value={needId} onChange={e => {setNeedId(e.target.value);setSearch(null)}}><option value="">Выберите потребность</option>{needs.map(n => <option key={n.id} value={n.id}>{n.title} · {n.grade}</option>)}</select></label><label className="inline-check"><input type="checkbox" checked={fspOnly} onChange={e => setFspOnly(e.target.checked)}/> Только с историей ФСП</label><button className="primary" onClick={runSearch}>Показать подборку</button></section>{needs.length === 0 && <Notice>Создайте профиль компании и потребность команды — после этого появится подборка.</Notice>}{snapshots.some(item => item.need_id === needId) && <div className="snapshot-history"><span>Сохранённые подборки:</span>{snapshots.filter(item => item.need_id === needId).slice(0,5).map(item => <button className="button subtle" key={item.id} onClick={() => restoreSearch(item.id)}>{fmtMoment(item.created_at)} · {item.result_count} профилей{search?.id === item.id ? ' · открыта' : ''}</button>)}</div>}{search && <><div className="results-heading"><h2>Подборка: {search.results.length}</h2><span className="muted">Алгоритм match_v1 · прежние подборки сохраняются</span></div>{search.results.length ? <div className="candidate-grid">{search.results.map(c => <CandidateCard key={c.id} candidate={c}/>)}</div> : <div className="empty card">Кандидаты пока не найдены. Проверьте категорию, бюджет или фильтр ФСП.</div>}{search.unavailable_count > 0 && <p className="muted">{search.unavailable_count} профиль больше не опубликован.</p>}</>}{selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section className="modal card" onClick={e => e.stopPropagation()}><button className="close" onClick={() => setSelected(null)} aria-label="Закрыть">×</button><p className="eyebrow">ПЕРСОНАЛЬНОЕ ПРИГЛАШЕНИЕ</p><h2>{selected.alias}</h2><p className="muted">Кандидат сначала увидит условия. Его контакты откроются вашей компании после принятия.</p>{error && <Notice tone="bad">{error}</Notice>}<form className="form-grid" onSubmit={sendInvite}><label className="full">Предложение<textarea rows={3} value={offer.offer_text} onChange={e => setOffer({...offer,offer_text:e.target.value})} required/></label><label className="full">Почему выбрали кандидата<textarea rows={3} value={offer.reason} onChange={e => setOffer({...offer,reason:e.target.value})} required/></label><label>Зарплата от, ₽/мес. до налогов<input type="number" min="1" value={offer.salary_min_rub} onChange={e => setOffer({...offer,salary_min_rub:Number(e.target.value)})} required/></label><label>Зарплата до, ₽/мес. до налогов<input type="number" min="1" value={offer.salary_max_rub} onChange={e => setOffer({...offer,salary_max_rub:Number(e.target.value)})} required/></label><label>Контакт компании<input type="email" value={offer.employer_contact} onChange={e => setOffer({...offer,employer_contact:e.target.value})} required/></label><div className="full"><button className="primary wide">Отправить приглашение</button></div></form></section></div>}</>}
    {tab === 'bank' && <><div className="page-heading"><p className="eyebrow">БАНК КАНДИДАТОВ</p><h1>Все открытые проверенные профили</h1><p>Порядок внутри категории учитывает тест и дополнительный сигнал ФСП.</p></div><section className="search-bar card"><label>Специализация<select value={bankSpec} onChange={e => setBankSpec(e.target.value)}><option value="">Все</option><option value="backend">Backend</option><option value="frontend">Frontend</option></select></label><label>Грейд<select value={bankGrade} onChange={e => setBankGrade(e.target.value)}><option value="">Все</option><option value="junior">Junior</option><option value="middle">Middle</option></select></label><label>Стек (заявлен)<input value={bankStack} onChange={e => setBankStack(e.target.value)} placeholder="Python"/></label><label className="inline-check"><input type="checkbox" checked={bankFsp} onChange={e => setBankFsp(e.target.checked)}/> С историей ФСП</label><button className="primary" onClick={filterBank}>Применить фильтры</button></section>{bank.length ? <div className="candidate-grid">{bank.map(candidate => <CandidateCard key={candidate.id} candidate={candidate}/>)}</div> : <div className="empty card">Пока нет подходящих опубликованных профилей.</div>}</>}
    {tab === 'offers' && <><div className="page-heading"><p className="eyebrow">ИСХОДЯЩИЕ ПРЕДЛОЖЕНИЯ</p><h1>Каждому — конкретные условия</h1><p>Контакты доступны только после принятия кандидатом именно вашего приглашения.</p></div>{offers.length === 0 ? <div className="empty card">Пока нет приглашений.</div> : offers.map(invite => <article className="card offer-card" key={invite.id}><div className="section-title"><div><h2>{invite.company_name} → Кандидат #{invite.candidate_id.slice(0,8)}</h2><p className="muted">{invite.offer_text}</p></div><span className={`badge ${invite.state === 'accepted' ? 'green' : ''}`}>{statusName(invite.state)}</span></div><div className="salary">{rubles(invite.salary_min_rub)} — {rubles(invite.salary_max_rub)}</div><p><strong>Основание:</strong> {invite.reason}</p>{invite.state === 'accepted' && <button className="button outline" onClick={() => showContact(invite.candidate_id)}>Показать контакты</button>}{contact && invite.state === 'accepted' && <Notice tone="good">{contact.full_name} · {contact.email} · {contact.phone}</Notice>}</article>)}</>}
  </main></div></div>
}

export default function App() {
  const [me, setMe] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => { api<User>('/me').then(setMe).catch(() => setMe(null)).finally(() => setLoading(false)) }, [revision])
  if (location.pathname === '/verify') return <Verify onDone={() => setRevision(revision+1)}/>
  if (loading) return <div className="centered"><div className="logo">ФСП СИГНАЛ</div><p>Загружаем кабинет…</p></div>
  if (!me) return <Auth onLogin={() => setRevision(revision+1)}/>
  return <><div className="logout"><button onClick={async () => { await api('/auth/logout','POST'); setRevision(revision+1) }}>Выйти</button></div>{me.role === 'candidate' ? <CandidateApp me={me}/> : <EmployerApp me={me}/>}</>
}
