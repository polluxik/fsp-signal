import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError, uploadResume } from './api'
import type { AchievementStory, AnswerValue, AssistantAchievementDraft, Attempt, Candidate, EvidenceCard, Invite, Need,
  Profile, RoleCardOut, Search, SearchSummary, User } from './types'
import EvidencePanel from './features/evidence/EvidencePanel'
import InvitationPanel from './features/invitations/InvitationPanel'
import PreferencesPanel from './features/preferences/PreferencesPanel'
import RoleCard from './features/roles/RoleCard'
import RoleFeed from './features/roles/RoleFeed'
import RoleEditor from './features/roles/RoleEditor'
import InterviewConfirmation from './features/invitations/InterviewConfirmation'
import AssistantPanel from './features/assistant/AssistantPanel'
import CalendarPanel from './features/calendar/CalendarPanel'
import MeetingList from './features/calendar/MeetingList'
import PublicCalendar from './features/calendar/PublicCalendar'
import BookingLink from './features/calendar/BookingLink'
import './features/calendar/calendar.css'

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
const matchSignalNames: Record<string, string> = {
  competencies: 'компетенциям', assessment: 'результату теста', text: 'содержанию роли',
}
const emptyProfile: Profile = {
  full_name: '', contact_email: '', contact_phone: '', city: '', summary: '', skills: [],
  experience_months: 0, min_salary_rub: 0, work_format: 'remote', consent_processing: false,
  published: false, available: true,
}
const emptyAchievementStory: AchievementStory = {
  title: '', context: '', personal_contribution: '', decision: '', result: '',
  result_scope: 'individual', basis: '', share_with_employers: false,
}

function rubles(value: number): string { return new Intl.NumberFormat('ru-RU').format(value) + ' ₽' }
function scalarAnswer(value: AnswerValue | undefined): string | number { return typeof value === 'object' ? '' : value ?? '' }
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
  return <div className={`notice ${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>{children}</div>
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
  const [tab, setTab] = useState('roles')
  const [profile, setProfile] = useState<Profile>(emptyProfile)
  const [story, setStory] = useState<AchievementStory>(emptyAchievementStory)
  const [skillsText, setSkillsText] = useState('')
  const [invites, setInvites] = useState<Invite[]>([])
  const [history, setHistory] = useState<{ id: string; category: string; state: string; score: number | null; outcome: string | null; started_at: string }[]>([])
  const [grants, setGrants] = useState<{ id: string; employer_id: string; revoked_at: string | null }[]>([])
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})
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
    if (p) {
      setProfile(current => current.preferences_version != null && p.preferences_version != null
        && current.preferences_version > p.preferences_version
        ? { ...p, preferences_version: current.preferences_version,
            min_salary_rub: current.min_salary_rub, work_format: current.work_format,
            available: current.available, adult_hiring_confirmed: current.adult_hiring_confirmed }
        : p)
      setSkillsText((p.skills || []).join(', '))
      setStory({ ...emptyAchievementStory, ...(p.achievement_story ?? {}) })
    }
    setInvites(i); setGrants(g); setHistory(h)
  }
  useEffect(() => { load().catch(err => setError(err.message)) }, [])
  useEffect(() => {
    if (tab !== 'offers') return
    const controller = new AbortController()
    api<Invite[]>('/candidate/invitations', 'GET', undefined, { signal: controller.signal })
      .then(setInvites)
      .catch((err: Error) => { if (err.name !== 'AbortError') setError(err.message) })
    return () => controller.abort()
  }, [tab])
  async function action(job: () => Promise<unknown>, success: string) {
    setError(''); setFeedback('')
    try { await job(); await load(); setFeedback(success) } catch (err) { setError((err as Error).message) }
  }
  function updateStory(patch: Partial<AchievementStory>) {
    setStory(current => ({ ...current, ...patch,
      share_with_employers: Object.keys(patch).some(key => key !== 'share_with_employers')
        ? false : patch.share_with_employers ?? current.share_with_employers,
      formatted_narrative: undefined,
    }))
  }
  function applyAchievementDraft(draft: AssistantAchievementDraft) {
    setStory(current => ({
      ...current,
      title: draft.title || current.title,
      context: draft.context || current.context,
      personal_contribution: draft.personal_contribution || current.personal_contribution,
      decision: draft.decision || current.decision,
      result: draft.result || current.result,
      result_scope: draft.result_scope ?? current.result_scope,
      basis: draft.basis || current.basis,
      share_with_employers: false,
      formatted_narrative: undefined,
    }))
  }
  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    const hasStory = [story.title, story.context, story.personal_contribution, story.decision, story.result, story.basis]
      .some(value => value.trim())
    if (hasStory && (!story.context.trim() || !story.personal_contribution.trim() || !story.result.trim())) {
      setError('Для истории нужны три коротких пункта: контекст, ваш вклад и результат. Остальное можно пропустить.')
      return
    }
    const { formatted_narrative: _preview, ...storyInput } = story
    await action(async () => {
      return api('/candidate/profile', 'PUT', { ...profile,
        expected_preferences_version: profile.preferences_version,
        achievement_story: hasStory ? storyInput : null,
        skills: skillsText.split(',').map(item => item.trim()).filter(Boolean) })
    }, 'Профиль сохранён')
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
      setAttempt(result); setAnswers(result.answers || {}) }
    catch (err) { setError((err as Error).message) }
  }
  async function progressTest() {
    if (!attempt) return
    setError(''); setFeedback('')
    try {
      const current = attempt.questions.filter(q => q.phase === attempt.phase)
      if (current.some(q => {
        const answer = answers[q.id]
        if (q.type !== 'structured') return answer === undefined || answer === ''
        return !q.fields?.every(field => typeof answer === 'object' && answer !== null &&
          answer[field.id] !== undefined && answer[field.id] !== '')
      })) {
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
      {[['roles','Для меня'],['profile','Мой профиль'],['preferences','Условия поиска'],['evidence','Доказательства'],['test','Проверка навыков'],['offers','Приглашения'],['meetings','Встречи'],['fsp','ФСП ID и доступ']].map(([id, label]) =>
        <button key={id} className={tab === id ? 'active' : ''} onClick={() => { setTab(id); setError(''); setFeedback('') }}>{label}</button>)}
      <div className="sidebar-bottom"><CategoryBadge spec={profile.verified_specialization} grade={profile.verified_grade}/><p className="small muted">Контакты открываются только по вашему решению.</p></div>
    </aside><main className="content">
      {error && <Notice tone="bad">{error}</Notice>}{feedback && <Notice tone="good">{feedback}</Notice>}
      {tab === 'roles' && <RoleFeed onNavigate={setTab}/>}
      {tab === 'meetings' && <><div className="page-heading"><p className="eyebrow">СЛЕДУЮЩИЙ ШАГ</p><h1>Встречи и договорённости</h1><p>Выберите время разговора и сохраните материалы вместе с работодателем.</p></div><MeetingList viewer="candidate"/></>}
      {tab === 'preferences' && <><div className="page-heading"><p className="eyebrow">ВАШИ ПРАВИЛА</p><h1>Подборка под ваши условия</h1><p>Сохранённые ограничения фильтруют выдачу. Их значения остаются закрытыми от компаний.</p></div><PreferencesPanel onSaved={preferences => setProfile(current => ({
        ...current,
        preferences_version: preferences.version,
        min_salary_rub: preferences.salary_min_rub ?? 0,
        work_format: preferences.allowed_work_formats.length === 1 ? preferences.allowed_work_formats[0] : 'any',
        available: preferences.available,
        adult_hiring_confirmed: preferences.adult_hiring_confirmed,
      }))}/></>}
      {tab === 'evidence' && <><div className="page-heading"><p className="eyebrow">ФАКТЫ О ВАШЕЙ РАБОТЕ</p><h1>Проверенное отдельно от заявленного</h1><p>Короткий ввод помогает быстро начать; в истории достижений можно сохранить контекст, личный вклад, решение, результат и его основание.</p></div><EvidencePanel/></>}
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
            <div className="full"><div className="field-heading">Один рабочий эпизод — чтобы было понятно, что сделали именно вы</div><p className="small muted">Три коротких пункта сохраняют контекст, ваш вклад и результат. Решение и основание можно добавить, если помните. Мы соберём рассказ, но не будем додумывать факты или объявлять их проверенными.</p></div>
            <AssistantPanel intent="candidate_achievement" testId="assistant-candidate-achievement"
              promptLabel="Расскажите, что произошло" onApply={applyAchievementDraft}/>
            <label className="full">Короткое название достижения<input maxLength={120} value={story.title} onChange={e => updateStory({title:e.target.value})} placeholder="Например: защита от повторной обработки"/></label>
            <label className="full">Контекст: какую задачу или проблему решали<input maxLength={700} value={story.context} onChange={e => updateStory({context:e.target.value})} placeholder="Например: повторная доставка события создавала риск двойной записи"/></label>
            <label className="full">Ваш личный вклад: что сделали вы<input maxLength={700} value={story.personal_contribution} onChange={e => updateStory({personal_contribution:e.target.value})} placeholder="Например: добавил защиту повторной обработки по event ID"/></label>
            <label className="full">Почему выбрали такой подход <span className="hint">необязательно</span><input maxLength={700} value={story.decision} onChange={e => updateStory({decision:e.target.value})} placeholder="Например: уникальное ограничение работает и при параллельных запросах"/></label>
            <label className="full">Что изменилось <span className="hint">без точных цифр, если их нет</span><input maxLength={700} value={story.result} onChange={e => updateStory({result:e.target.value})} placeholder="Например: команда перестала вручную разбирать дубли"/></label>
            <label>Масштаб результата<select value={story.result_scope} onChange={e => updateStory({result_scope:e.target.value as AchievementStory['result_scope']})}><option value="individual">Мой личный результат</option><option value="team">Результат команды</option></select></label>
            <label>Основание или артефакт <span className="hint">необязательно</span><input maxLength={500} value={story.basis} onChange={e => updateStory({basis:e.target.value})} placeholder="Например: ссылка на PR; сейчас не приложена"/></label>
            {story.formatted_narrative && <div className="full story-preview"><span className="small muted">Так рассказ сохранён для вас:</span><p>{story.formatted_narrative}</p></div>}
            <div className="full check-list"><label><input type="checkbox" disabled={!story.context.trim() || !story.personal_contribution.trim() || !story.result.trim()} checked={story.share_with_employers} onChange={e => setStory({...story,share_with_employers:e.target.checked})}/> Отдельно разрешаю показать этот рассказ работодателям как заявленный мной, не независимо проверенный</label></div>
            <div className="full check-list"><label><input type="checkbox" checked={profile.consent_processing} onChange={e => setProfile({...profile,consent_processing:e.target.checked,published:e.target.checked ? profile.published : false})}/> Согласен на обработку данных профиля</label><label><input type="checkbox" checked={profile.published} disabled={!profile.consent_processing} onChange={e => setProfile({...profile,published:e.target.checked})}/> Публиковать проверенный профиль работодателям</label><label><input type="checkbox" checked={profile.available} onChange={e => setProfile({...profile,available:e.target.checked})}/> Принимать приглашения</label></div>
            <div className="full"><button className="primary">Сохранить профиль</button></div>
          </form>
        </section></>}
      {tab === 'test' && <><div className="page-heading"><p className="eyebrow">ПРОВЕРКА НАВЫКОВ</p><h1>Категория, которую можно проверить</h1><p>Три группы практических вопросов, 20 минут. После первого этапа одно условие изменится. Ответы первого этапа будут зафиксированы.</p></div>
        {!attempt || attempt.state === 'scored' ? <section className="card"><h2>{attempt?.state === 'scored' ? `Результат: ${attempt.score} / 100` : 'Выберите направление'}</h2>{attempt?.state === 'scored' && <Notice tone={attempt.outcome === 'passed' ? 'good' : 'info'}>{attempt.outcome === 'passed' ? 'Категория подтверждена.' : 'Пока не подтверждено. Вы можете выбрать другой уровень по правилам попыток.'}</Notice>}
          <div className="form-grid"><label>Отрасль<select value="it" disabled><option value="it">Информационные технологии</option></select></label><label>Специализация<select value={spec} onChange={e => setSpec(e.target.value)}><option value="backend">Backend</option><option value="frontend">Frontend</option></select></label><label>Предполагаемый грейд<select value={grade} onChange={e => setGrade(e.target.value)}><option value="junior">Junior</option><option value="middle">Middle</option></select></label></div>
          <button className="primary" onClick={startTest}>Начать тест</button><p className="small muted">Порог: 70/100, половина баллов в каждой группе и верный ответ после изменения условия. Провал не понижает подтверждённый грейд.</p>{history.length > 0 && <div className="history"><h3>История тестов</h3>{history.map(item => <div className="grant" key={item.id}><span>{item.category} · {fmtDate(item.started_at)} · {item.state === 'scored' ? `${item.score}/100, ${item.outcome === 'passed' ? 'пройден' : 'не пройден'}` : 'в процессе'}</span>{item.state === 'in_progress' && <button className="button subtle" onClick={() => resumeTest(item.id)}>Продолжить</button>}</div>)}</div>}</section>
          : <section className="card"><div className="section-title"><div><h2>Этап {attempt.phase} из 2</h2><p className="muted">{attempt.phase === 1 ? 'Решите основные задания' : 'Изменилось одно условие. Старые ответы зафиксированы.'}</p></div><span className="badge">20 минут от начала попытки</span></div>
            {attempt.questions.filter(q => q.phase === attempt.phase).map((q, index) => <div className="question" key={q.id}><div className="question-top"><span>{index+1}. {skillNames[q.competency] ?? q.competency}</span><span>{q.points} баллов</span></div><p>{q.prompt}</p>{q.type === 'structured' ? <div className="form-grid">{q.fields?.map(field => { const current = answers[q.id]; const value = typeof current === 'object' && current !== null ? current[field.id] ?? '' : ''; return <label key={field.id}>{field.label}<select value={value} onChange={e => setAnswers({...answers,[q.id]:{...(typeof current === 'object' && current !== null ? current : {}),[field.id]:e.target.value}})}><option value="">Выберите вариант</option>{field.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label> })}</div> : q.type === 'choice' ? <div className="options">{q.options?.map(o => <label key={o.value}><input type="radio" name={q.id} checked={answers[q.id] === o.value} onChange={() => setAnswers({...answers,[q.id]:o.value})}/>{o.label}</label>)}</div> : <input className="answer-input" type="number" aria-label={`Ответ на вопрос ${index+1}`} value={scalarAnswer(answers[q.id])} onChange={e => setAnswers({...answers,[q.id]:e.target.value})}/>}</div>)}
            <button className="primary" onClick={progressTest}>{attempt.phase === 1 ? 'Зафиксировать ответы и продолжить' : 'Отправить на проверку'}</button></section>}
      </>}
    {tab === 'offers' && <InvitationPanel invites={invites} onChanged={load}/>}
      {tab === 'fsp' && <>
        <div className="page-heading"><p className="eyebrow">ИСТОЧНИК ДОСТИЖЕНИЙ</p><h1>Связь с ФСП ID</h1>
          <p>История соревнований дополняет тест. Если истории нет, вы участвуете в подборе на равных.</p></div>
        <section className="card"><h2>Состояние связи</h2>
          <Notice>{profile.fsp_status === 'mock' ? 'Подключена демонстрационная запись. Это не реальный реестр ФСП.' : profile.fsp_status === 'unverified' ? 'ID введён, но принадлежность не подтверждена.' : 'ФСП ID не подключён.'}</Notice>
          <label>ФСП ID<input value={fspId} onChange={e => setFspId(e.target.value)}/></label>
          <p className="small muted">Для локальной демонстрации используйте ID: demo-{me.id}. Произвольный ID останется неподтверждённым.</p>
          <div className="actions"><button className="primary" onClick={() => action(() => api('/candidate/fsp-link','POST',{participant_id:fspId}), 'Статус связи обновлён')}>Связать ID</button>
            <button className="button subtle" onClick={() => action(() => api('/candidate/fsp-link','DELETE'), 'Связь удалена')}>Отключить</button></div>
        </section>
        <section className="card"><h2>Доступ компаний к контактам</h2>
          {grants.some(grant => !grant.revoked_at) && <p className="small muted">Отзыв закроет компании дальнейший доступ к контактам, но не удалит данные, которые она уже увидела или сохранила.</p>}
          {grants.length === 0 ? <p className="muted">Никому не открыт.</p> : grants.map(grant => <div className="grant" key={grant.id}>
            <span>Компания #{grant.employer_id.slice(0,8)} · {grant.revoked_at ? 'доступ отозван' : 'доступ открыт'}</span>
            {!grant.revoked_at && <button className="button subtle" onClick={() => action(() => api(`/candidate/contact-grants/${grant.id}/revoke`,'POST'), 'Доступ отозван')}>Отозвать</button>}
          </div>)}
        </section>
      </>}
    </main></div>
  </div>
}

function EmployerApp({ me }: { me: User }) {
  const [tab, setTab] = useState('search')
  const [company, setCompany] = useState({ company_name:'', description:'', industry:'', contact_email:me.email })
  const [needs, setNeeds] = useState<Need[]>([])
  const [needId, setNeedId] = useState('')
  const [roleCard, setRoleCard] = useState<RoleCardOut | null>(null)
  const [showNeedForm, setShowNeedForm] = useState(false)
  const [searchBusy, setSearchBusy] = useState(false)
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
  const [candidateEvidence, setCandidateEvidence] = useState<EvidenceCard[]>([])
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>([])
  const [evidenceBusy, setEvidenceBusy] = useState(false)
  const [inviteBusy, setInviteBusy] = useState(false)
  const [snapshots, setSnapshots] = useState<SearchSummary[]>([])
  const [offers, setOffers] = useState<Invite[]>([])
  const [offer, setOffer] = useState({ offer_text:'', reason:'', salary_min_rub:180000,
    salary_max_rub:230000, work_format:'remote', employer_contact:me.email })
  const [contacts, setContacts] = useState<Record<string, Record<string,string>>>({})
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [inviteActionBusyId, setInviteActionBusyId] = useState('')
  const [companySetupRequired, setCompanySetupRequired] = useState(false)
  const [returnToInvitation, setReturnToInvitation] = useState(false)
  const [returnToNeed, setReturnToNeed] = useState(false)
  const inviteRequest = useRef<{ fingerprint: string; key: string } | null>(null)
  const bankRequest = useRef<AbortController | null>(null)
  const evidenceRequest = useRef<AbortController | null>(null)
  async function load() {
    setContacts({})
    const [c, n, o, b, h] = await Promise.all([api<typeof company | null>('/employer/company'),
      api<Need[]>('/employer/needs'), api<Invite[]>('/employer/invitations'),
      api<Candidate[]>('/employer/candidates'), api<SearchSummary[]>('/employer/searches')])
    if (c) setCompany(c)
    setNeeds(n); setOffers(o); setBank(b); setSnapshots(h)
    if (n.length) setNeedId(current => current || n[0].id)
    else setShowNeedForm(true)
  }
  useEffect(() => { load().catch(err => setError(err.message)) }, [])
  useEffect(() => () => evidenceRequest.current?.abort(), [])
  useEffect(() => {
    if (tab !== 'offers') return
    const controller = new AbortController()
    setContacts({})
    api<Invite[]>('/employer/invitations', 'GET', undefined, { signal: controller.signal })
      .then(setOffers)
      .catch((err: Error) => { if (err.name !== 'AbortError') setError(err.message) })
    return () => controller.abort()
  }, [tab])
  useEffect(() => {
    if (!needId) { setRoleCard(null); return }
    const controller = new AbortController()
    setRoleCard(null)
    api<RoleCardOut>(`/employer/needs/${needId}/role-card`, 'GET', undefined, { signal: controller.signal })
      .then(setRoleCard)
      .catch((err: Error) => { if (err.name !== 'AbortError') setRoleCard(null) })
    return () => controller.abort()
  }, [needId])
  async function saveCompany(event: FormEvent) {
    event.preventDefault(); setError(''); setFeedback('')
    try {
      await api('/employer/company','PUT',company)
      await load()
      setCompanySetupRequired(false)
      setFeedback('Профиль компании сохранён')
    } catch (err) {
      setCompanySetupRequired(false)
      setError((err as Error).message)
    }
  }
  async function saveNeed(event: FormEvent) {
    event.preventDefault(); setError(''); setFeedback(''); setCompanySetupRequired(false)
    if (needForm.competencies.length === 0) { setError('Выберите хотя бы одну компетенцию.'); return }
    try {
      const result = await api<Need>('/employer/needs','POST',{...needForm, stack:needForm.stack.split(',').map(x => x.trim()).filter(Boolean)})
      setNeedForm({ title:'', description:'', specialization:'backend', grade:'middle', competencies:[], stack:'',
        salary_min_rub:180000, salary_max_rub:230000, work_format:'remote' })
      setNeedId(result.id); setShowNeedForm(false); await load(); setFeedback('Короткая потребность создана. Теперь добавьте условия роли, которые увидит кандидат.'); setTab('need')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'COMPANY_PROFILE_REQUIRED') {
        setCompanySetupRequired(true)
        setError('Перед созданием роли заполните профиль компании.')
      } else setError((err as Error).message)
    }
  }
  async function runSearch() {
    if (!needId) { setError('Сначала создайте потребность'); return }
    setError(''); setFeedback('')
    setSearchBusy(true)
    try {
      const [latestNeeds, card] = await Promise.all([
        api<Need[]>('/employer/needs'), api<RoleCardOut>(`/employer/needs/${needId}/role-card`),
      ])
      setNeeds(latestNeeds)
      setRoleCard(card)
      const need = latestNeeds.find(item => item.id === needId)
      if (!need?.role_version_id || card.publication_state !== 'active' || !card.fresh) {
        setError('Сначала заполните и опубликуйте актуальные условия роли.')
        return
      }
      const roleVersionId = need.role_version_id
      const result = await api<Search>('/employer/searches','POST',{need_id:needId,
        role_version_id:roleVersionId, fsp_only:fspOnly, stack:need.stack ?? [],
        parent_snapshot_id:search?.need_id === needId && search.role_version_id === roleVersionId ? search.id : null})
      setSearch(result); setSnapshots(await api<SearchSummary[]>('/employer/searches')); setTab('search')
    } catch (err) { setError((err as Error).message) } finally { setSearchBusy(false) }
  }
  async function restoreSearch(id: string) {
    setError('')
    try { const result = await api<Search>(`/employer/searches/${id}`)
      setSearch(result); setNeedId(result.need_id); setFspOnly(result.filters.fsp_only); setTab('search') }
    catch (err) { setError((err as Error).message) }
  }
  async function filterBank() {
    setError('')
    bankRequest.current?.abort()
    const controller = new AbortController()
    bankRequest.current = controller
    const params = new URLSearchParams()
    if (bankSpec) params.set('specialization', bankSpec)
    if (bankGrade) params.set('grade', bankGrade)
    if (bankStack) params.set('stack', bankStack)
    if (bankFsp) params.set('fsp_only', 'true')
    try { setBank(await api<Candidate[]>(`/employer/candidates?${params}`, 'GET', undefined, { signal: controller.signal })) }
    catch (err) { if ((err as Error).name !== 'AbortError') setError((err as Error).message) }
  }
  function clearSelectedCandidate() {
    evidenceRequest.current?.abort()
    evidenceRequest.current = null
    setSelected(null)
    setCandidateEvidence([])
    setSelectedEvidenceIds([])
    setEvidenceBusy(false)
  }
  async function choose(candidate: Candidate) {
    evidenceRequest.current?.abort()
    evidenceRequest.current = null
    setSelected(candidate)
    setCandidateEvidence([])
    setSelectedEvidenceIds([])
    setEvidenceBusy(true)
    setError('')
    const need = needs.find(n => n.id === needId)
    if (!roleCard || roleCard.publication_state !== 'active' || !roleCard.fresh || !need?.role_version_id) {
      setSelected(null)
      setTab('need')
      setError('Перед приглашением заполните и опубликуйте условия роли.')
      setEvidenceBusy(false)
      return
    }
    setOffer({ offer_text:`Приглашаем обсудить роль ${need?.title ?? 'в нашей команде'} и задачи команды.`,
      reason:candidate.match?.reasons?.slice(0,2).join('. ') ?? `Подтверждена категория ${candidate.specialization} ${candidate.grade}.`,
      salary_min_rub:roleCard.payload.salary_min_rub ?? need?.salary_min_rub ?? 180000,
      salary_max_rub:roleCard.payload.salary_max_rub ?? need?.salary_max_rub ?? 230000,
      work_format:roleCard.payload.work_format ?? 'remote', employer_contact:(roleCard.payload.employer_contact ?? company.contact_email) || me.email })
    setTab('search')
    const controller = new AbortController()
    evidenceRequest.current = controller
    try {
      const cards = await api<EvidenceCard[]>(`/employer/candidates/${candidate.id}/evidence`, 'GET', undefined, { signal: controller.signal })
      if (evidenceRequest.current !== controller) return
      setCandidateEvidence(cards)
      const preferred = cards.find(card => card.competency && (roleCard.payload.competencies ?? []).includes(card.competency)
        && ['verified_action', 'synthetic_fixture', 'aggregate'].includes(card.verification_level))
        ?? cards.find(card => card.source_type === 'assessment_attempt' || card.source_type === 'legacy_aggregate')
        ?? cards[0]
      setSelectedEvidenceIds(preferred ? [preferred.id] : [])
    } catch (err) {
      if ((err as Error).name !== 'AbortError' && evidenceRequest.current === controller) setError((err as Error).message)
    } finally {
      if (evidenceRequest.current === controller) {
        evidenceRequest.current = null
        setEvidenceBusy(false)
      }
    }
  }
  async function sendInvite(event: FormEvent) {
    event.preventDefault(); if (!selected) return
    setError(''); setFeedback(''); setCompanySetupRequired(false); setInviteBusy(true)
    try {
      const need = needs.find(item => item.id === needId)
      if (!roleCard || !need?.role_version_id || !roleCard.fresh) throw new Error('Версия роли устарела. Подтвердите её актуальность и попробуйте снова.')
      if (selectedEvidenceIds.length === 0) throw new Error('Выберите хотя бы один источник доказательства для приглашения.')
      const body = { ...offer, candidate_id:selected.id, need_id:needId,
        role_version_id:need.role_version_id, evidence_ids:selectedEvidenceIds }
      const fingerprint = JSON.stringify(body)
      if (!inviteRequest.current || inviteRequest.current.fingerprint !== fingerprint) {
        inviteRequest.current = { fingerprint, key: crypto.randomUUID() }
      }
      await api('/employer/invitations','POST',body,{ idempotencyKey:inviteRequest.current.key })
      inviteRequest.current = null
      clearSelectedCandidate(); await load(); setFeedback('Приглашение отправлено с зафиксированными условиями и выбранным основанием.')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'COMPANY_PROFILE_REQUIRED') {
        setCompanySetupRequired(true)
        setError('Перед отправкой приглашения заполните профиль компании.')
      } else setError((err as Error).message)
    } finally { setInviteBusy(false) }
  }
  async function showContact(candidateId: string) {
    setError('')
    try {
      const contact = await api<Record<string,string>>(`/employer/candidates/${candidateId}/contact`)
      setContacts(current => ({ ...current, [candidateId]: contact }))
    }
    catch (err) { setError((err as Error).message) }
  }
  async function withdrawInvitation(invite: Invite) {
    setError('')
    setFeedback('')
    setInviteActionBusyId(invite.id)
    try {
      await api(`/invitations/${invite.id}/withdraw`, 'POST', {
        expected_state_version: invite.state_version ?? 1,
      })
      setOffers(await api<Invite[]>('/employer/invitations'))
      setFeedback('Приглашение отозвано. Кандидат больше не увидит его как активное.')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INVITATION_STATE_CONFLICT') {
        try {
          setOffers(await api<Invite[]>('/employer/invitations'))
          setError('Статус приглашения уже изменился. Список обновлён — проверьте актуальное состояние перед повтором.')
        } catch (refreshError) { setError((refreshError as Error).message) }
      } else setError((err as Error).message)
    }
    finally { setInviteActionBusyId('') }
  }
  async function onRoleSaved(card: RoleCardOut) {
    setRoleCard(card)
    try { setNeeds(await api<Need[]>('/employer/needs')) }
    catch (err) { setError((err as Error).message) }
  }
  const activeNeed = needs.find(item => item.id === needId) ?? null
  const activeRoleCard = roleCard?.need_id === needId ? roleCard : null
  const staleSearch = tab === 'search' && !!search
    && (search.changed_since_search || search.role_version_id !== activeNeed?.role_version_id)
  function CandidateCard({ candidate }: { candidate: Candidate }) {
    const unknownSignals = Object.entries(candidate.match?.components ?? {})
      .filter(([, value]) => value == null)
      .map(([name]) => matchSignalNames[name] ?? name)
    return <article className="candidate-card card">
      <div className="section-title">
        <div>
          <p className="eyebrow">{candidate.verification_source === 'synthetic_fixture' ? 'СИНТЕТИЧЕСКИЙ ПРОФИЛЬ'
            : candidate.verification_source === 'assessment' ? 'КАТЕГОРИЯ ПОДТВЕРЖДЕНА ТЕСТОМ' : 'КАТЕГОРИЯ НЕ ПОДТВЕРЖДЕНА'}</p>
          <h3>{candidate.alias}</h3>
        </div>
      </div>
      <div className="candidate-signals">
        <div><span>{candidate.match ? 'Соответствие роли' : 'Оценка в банке'}</span>
          <strong>{candidate.match ? candidate.match.score == null ? 'Недостаточно данных' : `${candidate.match.score}/100`
            : candidate.bank_score == null ? 'Нет данных' : `${candidate.bank_score}/100`}</strong></div>
        <div><span>{candidate.verification_source === 'synthetic_fixture' ? 'Результат теста · учебные данные' : 'Результат теста'}</span>
          <strong>{candidate.test_score}/100</strong></div>
        {candidate.match && <div><span>Охват доказательствами</span>
          <strong>{candidate.match.evidence_coverage == null ? 'Недостаточно данных' : `${Math.round(candidate.match.evidence_coverage * 100)}%`}</strong></div>}
      </div>
      <CategoryBadge spec={candidate.specialization} grade={candidate.grade}/>
      <div className="evidence-row">
        <span>ФСП: {candidate.fsp_status === 'mock' ? 'демо-достижение' : 'нет подтверждения'}</span>
      </div>
      {unknownSignals.length > 0 && <p className="small muted unknown-match-data">
        Нет данных по {unknownSignals.join(', ')}. Их отсутствие не означает отсутствие навыка и не считалось нулём.
      </p>}
      <p className="small muted">Заявленные навыки: {candidate.skills_declared?.join(', ') || '—'} · не считаются результатом проверки</p>
      {candidate.match && <>
        <ul className="reasons">{candidate.match.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        {candidate.match.gaps.length > 0 && <p className="gap">{candidate.match.gaps.join('; ')}</p>}
      </>}
      <button className="button outline" disabled={evidenceBusy || inviteBusy || staleSearch || !activeRoleCard || activeRoleCard.publication_state !== 'active' || !activeRoleCard.fresh}
        onClick={() => void choose(candidate)}>Пригласить с условиями →</button>
    </article>
  }
  return <div className="workspace"><header className="topbar"><span className="logo">ФСП <strong>СИГНАЛ</strong></span><span className="top-id">{company.company_name || me.email}</span></header><div className="shell"><aside className="sidebar"><p className="overline">КАБИНЕТ РАБОТОДАТЕЛЯ</p>{[['search','Найти специалиста'],['need','Роль и условия'],['bank','Банк кандидатов'],['offers','Приглашения'],['calendar','Календарь HR'],['company','Компания']].map(([id,label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => {setTab(id);clearSelectedCandidate();setError('');setFeedback('');setReturnToInvitation(false);setReturnToNeed(false);setCompanySetupRequired(false)}}>{label}</button>)}<div className="sidebar-bottom"><p className="small muted">В этой демонстрации достижения ФСП синтетические.</p></div></aside><main className="content">
    {error && !companySetupRequired && <Notice tone="bad">{error}</Notice>}
    {companySetupRequired && !selected && tab !== 'company' && error && <div className="notice bad" role="alert">{error}
      <button className="text-button" type="button" onClick={() => {
        setError(''); setReturnToInvitation(false); setReturnToNeed(tab === 'need'); setTab('company')
      }}>Перейти к профилю компании</button>
    </div>}
    {feedback && <Notice tone="good">{feedback}</Notice>}
    {tab === 'company' && <><div className="page-heading"><p className="eyebrow">КОМПАНИЯ</p><h1>Кто приглашает кандидата?</h1><p>Название и способ связи будут указаны в каждом предложении.</p></div>{((selected && returnToInvitation) || returnToNeed) && <div className="notice info" role="status">{returnToNeed ? 'Черновик роли сохранён в этой вкладке.' : 'Черновик приглашения сохранён в этой вкладке.'} <button className="text-button" type="button" onClick={() => { setTab(returnToNeed ? 'need' : 'search'); setReturnToInvitation(false); setReturnToNeed(false); setCompanySetupRequired(false); setError('') }}>{returnToNeed ? 'Вернуться к роли' : 'Вернуться к приглашению'}</button></div>}<section className="card"><form className="form-grid" onSubmit={saveCompany}><label>Название компании<input value={company.company_name} onChange={e => setCompany({...company,company_name:e.target.value})} required/></label><label>Направление деятельности<input value={company.industry} onChange={e => setCompany({...company,industry:e.target.value})}/></label><label className="full">О команде<textarea rows={4} value={company.description} onChange={e => setCompany({...company,description:e.target.value})}/></label><label>Контактный email<input type="email" value={company.contact_email} onChange={e => setCompany({...company,contact_email:e.target.value})} required/></label><div className="full"><button className="primary">Сохранить компанию</button></div></form></section></>}
    {tab === 'need' && needs.length > 0 && <><div className="page-heading"><p className="eyebrow">РОЛЬ И УСЛОВИЯ</p><h1>Сделайте вакансию понятной до отклика</h1><p>Сначала короткая потребность, затем задача первых 30 дней, зарплата, нагрузка и прозрачные этапы отбора.</p></div>
      <section className="search-bar card role-selector"><label>Потребность команды<select value={needId} onChange={event => { setNeedId(event.target.value); setSearch(null); clearSelectedCandidate() }}>{needs.map(item => <option key={item.id} value={item.id}>{item.title} · {item.grade}</option>)}</select></label>
        {!showNeedForm && <button className="button outline" onClick={() => setShowNeedForm(true)}>Новая потребность</button>}
      </section>
      {activeNeed && !showNeedForm && <RoleEditor key={activeNeed.id} need={activeNeed} companyContact={company.contact_email || me.email} onSaved={onRoleSaved}/>}
    </>}
    {tab === 'need' && showNeedForm && <><div className="page-heading"><p className="eyebrow">ЗАДАЧА КОМАНДЫ</p><h1>Кого вы ищете?</h1><p>Создайте короткий черновик. Затем добавьте реальные условия роли, которые кандидаты увидят до решения.</p></div><section className="card"><form className="form-grid" onSubmit={saveNeed}><label>Название роли<input value={needForm.title} onChange={e => setNeedForm({...needForm,title:e.target.value})} placeholder="Backend Middle" required/></label><label>Специализация<select value={needForm.specialization} onChange={e => setNeedForm({...needForm,specialization:e.target.value,competencies:[]})}><option value="backend">Backend</option><option value="frontend">Frontend</option></select></label><label>Грейд<select value={needForm.grade} onChange={e => setNeedForm({...needForm,grade:e.target.value,competencies:[]})}><option value="junior">Junior</option><option value="middle">Middle</option></select></label><label>Формат<select value={needForm.work_format} onChange={e => setNeedForm({...needForm,work_format:e.target.value})}><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option><option value="any">Пока не решили</option></select></label><label className="full">Чем будет заниматься специалист<textarea rows={4} value={needForm.description} onChange={e => setNeedForm({...needForm,description:e.target.value})} required placeholder="Например: обеспечить корректную обработку повторных событий"/></label><div className="full"><p className="field-heading">Проверяемые компетенции</p><div className="checks">{skillsByCategory[`${needForm.specialization}:${needForm.grade}`].map(skill => <label key={skill}><input type="checkbox" checked={needForm.competencies.includes(skill)} onChange={e => setNeedForm({...needForm,competencies:e.target.checked ? [...needForm.competencies,skill] : needForm.competencies.filter(x => x !== skill)})}/>{skillNames[skill]}</label>)}</div></div><label>Стек через запятую <span className="hint">заявлено</span><input value={needForm.stack} onChange={e => setNeedForm({...needForm,stack:e.target.value})} placeholder="Python, PostgreSQL"/></label><label>Зарплата от, ₽/мес. до налогов<input type="number" min="1" value={needForm.salary_min_rub} onChange={e => setNeedForm({...needForm,salary_min_rub:Number(e.target.value)})}/></label><label>Зарплата до, ₽/мес. до налогов<input type="number" min="1" value={needForm.salary_max_rub} onChange={e => setNeedForm({...needForm,salary_max_rub:Number(e.target.value)})}/></label><div className="full"><button className="primary">Создать черновик роли</button></div></form></section></>}
    {tab === 'search' && <>
      <div className="page-heading"><p className="eyebrow">ОБРАТНЫЙ НАЙМ</p><h1>Найдите человека по тому, что он умеет</h1>
        <p>Сначала подтверждённые действия и понятная задача. Контакт — только после принятия конкретных условий.</p></div>
      <section className="search-bar card"><label>Потребность<select value={needId} onChange={event => { setNeedId(event.target.value); setSearch(null) }}>
        <option value="">Выберите потребность</option>{needs.map(item => <option key={item.id} value={item.id}>{item.title} · {item.grade}</option>)}</select></label>
        <label className="inline-check"><input type="checkbox" checked={fspOnly} onChange={event => setFspOnly(event.target.checked)}/> Только с историей ФСП</label>
        <button className="primary" disabled={searchBusy || !activeRoleCard || activeRoleCard.publication_state !== 'active' || !activeRoleCard.fresh}
          onClick={runSearch}>{searchBusy ? 'Формируем подборку…' : 'Показать подборку'}</button>
      </section>
      {needs.length === 0 && <Notice>Создайте профиль компании и заполните условия первой роли.</Notice>}
      {activeRoleCard && <div className="role-search-preview"><RoleCard role={activeRoleCard.payload} status={activeRoleCard.publication_state}
        confirmedAt={activeRoleCard.confirmed_at} source={activeRoleCard.source} compact/><button className="text-button" onClick={() => setTab('need')}>Изменить условия роли</button></div>}
      {needs.length > 0 && (!activeRoleCard || activeRoleCard.publication_state !== 'active' || !activeRoleCard.fresh) &&
        <Notice>Подборка доступна только по опубликованной актуальной роли. <button className="text-button" onClick={() => setTab('need')}>Оформить роль</button></Notice>}
      {snapshots.some(item => item.need_id === needId) && <div className="snapshot-history"><span>Сохранённые подборки:</span>
        {snapshots.filter(item => item.need_id === needId).slice(0,5).map(item => <button className="button subtle" key={item.id} onClick={() => restoreSearch(item.id)}>
          {fmtMoment(item.created_at)} · {item.result_count} профилей{search?.id === item.id ? ' · открыта' : ''}</button>)}</div>}
      {search && <><div className="results-heading"><h2>Подборка: {search.results.length}</h2><span className="muted">Алгоритм {search.algorithm_version} · снимок условий</span></div>
        {(search.changed_since_search || search.role_version_id !== activeNeed?.role_version_id) && <Notice>Эта подборка рассчитана по прежним условиям. Сформируйте новую, прежде чем приглашать кандидатов.</Notice>}
        {search.results.length ? <div className="candidate-grid">{search.results.map(candidate => <CandidateCard key={candidate.id} candidate={candidate}/>)}</div>
          : <div className="empty card">Кандидаты пока не найдены. Проверьте категорию, бюджет или фильтр ФСП.</div>}
        {search.unavailable_count > 0 && <p className="muted">Недоступно профилей в этой подборке: {search.unavailable_count}.</p>}
      </>}
      {selected && <div className="modal-backdrop" onClick={() => { if (!inviteBusy) clearSelectedCandidate() }}>
        <section className="modal card" role="dialog" aria-modal="true" aria-labelledby="invite-title" onClick={event => event.stopPropagation()}>
          <button className="close" type="button" disabled={inviteBusy} onClick={clearSelectedCandidate} aria-label="Закрыть">×</button>
          <p className="eyebrow">ПЕРСОНАЛЬНОЕ ПРИГЛАШЕНИЕ · УСЛОВИЯ ЗАФИКСИРОВАНЫ</p><h2 id="invite-title">{selected.alias}</h2>
          <p className="muted">Кандидат увидит эту версию до решения. Контакты откроются вашей компании только после явного согласия.</p>
          {companySetupRequired && error && <div className="notice bad" role="alert">{error}<button className="text-button" type="button" onClick={() => { setError(''); setReturnToInvitation(true); setTab('company') }}>Перейти к профилю компании</button></div>}
          {activeRoleCard && <RoleCard role={activeRoleCard.payload} status={activeRoleCard.publication_state}
            confirmedAt={activeRoleCard.confirmed_at} source={activeRoleCard.source}/>}
          <EvidencePanel mode="select" candidateId={selected.id} externalCards={candidateEvidence} externalLoading={evidenceBusy}
            selectedIds={selectedEvidenceIds} onSelectedIdsChange={setSelectedEvidenceIds}/>
          <form className="form-grid" onSubmit={sendInvite}>
            <label className="full">Текст приглашения<textarea rows={3} minLength={20} maxLength={4000} value={offer.offer_text}
              onChange={event => setOffer({...offer,offer_text:event.target.value})} required/></label>
            <label className="full">Почему выбрали кандидата?<span className="hint">Конкретная причина — от 10 символов</span><textarea rows={3} minLength={10} maxLength={1500} value={offer.reason}
              onChange={event => setOffer({...offer,reason:event.target.value})} required/></label>
            <label>Предлагаем от, ₽/мес. до налогов<input type="number" min={activeRoleCard?.payload.salary_min_rub ?? 1}
              max={activeRoleCard?.payload.salary_max_rub} value={offer.salary_min_rub} onChange={event => setOffer({...offer,salary_min_rub:Number(event.target.value)})} required/></label>
            <label>До, ₽/мес. до налогов<input type="number" min={offer.salary_min_rub} max={activeRoleCard?.payload.salary_max_rub}
              value={offer.salary_max_rub} onChange={event => setOffer({...offer,salary_max_rub:Number(event.target.value)})} required/></label>
            <div className="full pinned-contact"><span className="field-heading">Контакт ответственного</span><strong>{activeRoleCard?.payload.employer_contact ?? offer.employer_contact}</strong>
              <span className="small muted">Зафиксирован в версии роли</span></div>
            <div className="full"><button className="primary wide" disabled={inviteBusy || evidenceBusy || selectedEvidenceIds.length === 0 || !activeRoleCard?.fresh}>
              {inviteBusy ? 'Отправляем…' : `Отправить с выбранным основанием (${selectedEvidenceIds.length})`}</button></div>
          </form>
        </section>
      </div>}
    </>}
    {tab === 'bank' && <><div className="page-heading"><p className="eyebrow">БАНК КАНДИДАТОВ</p><h1>Все открытые проверенные профили</h1><p>{bank[0]?.bank_score_algorithm_version === 'match_v2' ? 'Порядок внутри категории основан на тестовом результате; ФСП доступен как отдельный фильтр.' : bank[0]?.bank_score_algorithm_version === 'match_v1' ? 'Порядок внутри категории учитывает тест и дополнительный сигнал ФСП.' : 'Порядок внутри категории определяется выбранной версией алгоритма; ФСП можно фильтровать отдельно.'}</p></div><section className="search-bar card"><label>Специализация<select value={bankSpec} onChange={e => setBankSpec(e.target.value)}><option value="">Все</option><option value="backend">Backend</option><option value="frontend">Frontend</option></select></label><label>Грейд<select value={bankGrade} onChange={e => setBankGrade(e.target.value)}><option value="">Все</option><option value="junior">Junior</option><option value="middle">Middle</option></select></label><label>Стек (заявлен)<input value={bankStack} onChange={e => setBankStack(e.target.value)} placeholder="Python"/></label><label className="inline-check"><input type="checkbox" checked={bankFsp} onChange={e => setBankFsp(e.target.checked)}/> С историей ФСП</label><button className="primary" onClick={filterBank}>Применить фильтры</button></section>{bank.length ? <div className="candidate-grid">{bank.map(candidate => <CandidateCard key={candidate.id} candidate={candidate}/>)}</div> : <div className="empty card">Пока нет подходящих опубликованных профилей.</div>}</>}
    {tab === 'calendar' && <CalendarPanel/>}
    {tab === 'offers' && <><div className="page-heading"><p className="eyebrow">ИСХОДЯЩИЕ ПРЕДЛОЖЕНИЯ</p><h1>Нанимайте по обещаниям, которые можно проверить</h1><p>Каждое приглашение привязано к выбранным доказательствам и конкретной версии условий.</p></div>{offers.length === 0 ? <div className="empty card">Пока нет приглашений.</div> : offers.map(invite => <article className="card offer-card" key={invite.id}><div className="section-title"><div><h2>{invite.company_name} → Кандидат #{invite.candidate_id.slice(0,8)}</h2><p className="muted">{invite.offer_text}</p></div><span className={`badge ${invite.state === 'accepted' ? 'green' : ''}`}>{statusName(invite.state)}</span></div><div className="salary">{rubles(invite.salary_min_rub)} — {rubles(invite.salary_max_rub)} <small>в месяц · до налогов</small></div><p><strong>Основание:</strong> {invite.reason}</p>{['sent', 'viewed'].includes(invite.state) && <button className="button subtle" type="button" disabled={inviteActionBusyId === invite.id} onClick={() => void withdrawInvitation(invite)}>{inviteActionBusyId === invite.id ? 'Отзываем…' : 'Отозвать приглашение'}</button>}{invite.state === 'accepted' && <><InterviewConfirmation invite={invite} viewer="employer" onChanged={load}/><BookingLink invitationId={invite.id} employer/><button className="button outline" onClick={() => showContact(invite.candidate_id)}>Показать контакты кандидата #{invite.candidate_id.slice(0,8)}</button></>}{contacts[invite.candidate_id] && invite.state === 'accepted' && <Notice tone="good">{contacts[invite.candidate_id].full_name} · {contacts[invite.candidate_id].email} · {contacts[invite.candidate_id].phone}</Notice>}</article>)}</>}
  </main></div></div>
}

export default function App() {
  const [me, setMe] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => { api<User>('/me').then(setMe).catch(() => setMe(null)).finally(() => setLoading(false)) }, [revision])
  if (location.pathname === '/verify') return <Verify onDone={() => setRevision(revision+1)}/>
  if (loading) return <div className="centered"><div className="logo">ФСП СИГНАЛ</div><p>Загружаем кабинет…</p></div>
  if (location.pathname.startsWith('/calendar/')) return <PublicCalendar me={me} auth={<Auth onLogin={() => setRevision(revision+1)}/>}/>
  if (!me) return <Auth onLogin={() => setRevision(revision+1)}/>
  return <><div className="logout"><button onClick={async () => { await api('/auth/logout','POST'); setRevision(revision+1) }}>Выйти</button></div>{me.role === 'candidate' ? <CandidateApp me={me}/> : <EmployerApp me={me}/>}</>
}
