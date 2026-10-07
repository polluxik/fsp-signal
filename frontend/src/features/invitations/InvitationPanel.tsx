import { useState } from 'react'
import { api } from '../../api'
import type { CandidatePreferences, Invite, RoleCardPayload } from '../../types'
import RoleCard from '../roles/RoleCard'
import InterviewConfirmation from './InterviewConfirmation'
import BookingLink from '../calendar/BookingLink'

type Props = { invites: Invite[]; onChanged: () => Promise<void> }

function rubles(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value) + ' ₽'
}

function date(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value))
}

function statusName(value: Invite['state']): string {
  return ({ sent: 'Новое', viewed: 'Просмотрено', accepted: 'Принято', rejected: 'Отклонено',
    withdrawn: 'Отозвано', expired: 'Срок истёк' } as Record<Invite['state'], string>)[value]
}

function compatibilityText(invite: Invite): string {
  const status = invite.compatibility?.status
  if (status === 'compatible') return 'Условия соответствуют сохранённым ограничениям.'
  if (status === 'needs_clarification') return 'Часть условий не указана. Вы можете запросить уточнение до решения.'
  if (status === 'incompatible') return 'Эта версия конфликтует с вашими условиями. Принять её нельзя; попросите работодателя изменить предложение.'
  return 'Проверьте условия. Совместимость не удалось пересчитать.'
}

function roleFrom(invite: Invite): Partial<RoleCardPayload> {
  return invite.terms_snapshot?.role ?? {
    title: invite.offer_text,
    salary_min_rub: invite.salary_min_rub,
    salary_max_rub: invite.salary_max_rub,
    work_format: invite.work_format as RoleCardPayload['work_format'],
  }
}

const reopenAfterAcceptanceConflict = new Set([
  'INVITATION_STATE_CONFLICT', 'TERMS_VERSION_CONFLICT', 'PREFERENCES_VERSION_CONFLICT',
  'ROLE_VERSION_CONFLICT', 'ROLE_STALE', 'CONDITIONS_INCOMPATIBLE',
])
const verificationNames: Record<string, string> = {
  verified_action: 'Проверенное действие',
  declared: 'Заявлено кандидатом',
  aggregate: 'Агрегированный результат оценки',
  synthetic_fixture: 'Синтетический пример',
}

export default function InvitationPanel({ invites, onChanged }: Props) {
  const [active, setActive] = useState<Invite | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')

  async function open(invite: Invite) {
    setError('')
    setFeedback('')
    setConfirmed(false)
    let reviewedInvite = invite
    if (invite.state === 'sent') {
      setBusyId(invite.id)
      try {
        const viewed = await api<Partial<Invite>>(`/invitations/${invite.id}/view`, 'POST', { expected_state_version: invite.state_version ?? 1 })
        reviewedInvite = { ...invite, ...viewed,
          compatibility: viewed.compatibility ?? invite.compatibility,
          evidence_refs: viewed.evidence_refs ?? invite.evidence_refs }
        await onChanged()
      }
      catch (err) { setError((err as Error).message) }
      finally { setBusyId('') }
    }
    setActive(reviewedInvite)
  }

  async function accept() {
    if (!active || !confirmed || active.compatibility?.status === 'incompatible') return
    setError('')
    setBusy(true)
    try {
      if (active.terms_hash) {
        const preferences = await api<CandidatePreferences>('/candidate/preferences')
        await api(`/invitations/${active.id}/accept`, 'POST', {
          expected_terms_hash: active.terms_hash,
          expected_preferences_version: preferences.version,
          expected_state_version: active.state_version ?? 1,
        })
      } else {
        await api(`/invitations/${active.id}/accept`, 'POST')
      }
      setActive(null)
      setConfirmed(false)
      setFeedback('Вы приняли именно эту версию условий. Контакты доступны только этой компании.')
      await onChanged()
    } catch (err) {
      setConfirmed(false)
      setError((err as Error).message)
      const code = (err as { code?: string }).code
      if (code && reopenAfterAcceptanceConflict.has(code)) {
        setActive(null)
        try { await onChanged() } catch (refreshError) { setError((refreshError as Error).message) }
      }
    } finally { setBusy(false) }
  }

  async function reject(invite: Invite) {
    setBusyId(invite.id)
    setError('')
    setFeedback('')
    try {
      await api(`/invitations/${invite.id}/reject`, 'POST', { expected_state_version: invite.state_version ?? 1 })
      if (active?.id === invite.id) setActive(null)
      setFeedback('Приглашение отклонено. Ваши контакты не раскрыты.')
      await onChanged()
    } catch (err) { setError((err as Error).message) } finally { setBusyId('') }
  }

  return <>
    <div className="page-heading"><p className="eyebrow">ПРЕДЛОЖЕНИЯ</p><h1>Сначала условия — потом ваше решение</h1>
      <p>Зарплата и этапы видны до согласия. Принятие открывает контакты только компании, которая отправила это приглашение.</p></div>
    {error && !active && <div className="notice bad" role="alert">{error}</div>}
    {feedback && <div className="notice good" role="status">{feedback}</div>}
    {invites.length === 0 ? <div className="empty card">Пока нет приглашений. Заполните условия поиска и проверьте навыки, чтобы получать подходящие предложения.</div> : invites.map(invite =>
      <article className="card offer-card" key={invite.id}>
        <div className="section-title"><div><span className="eyebrow">{invite.company_name}</span><h2>{invite.offer_text}</h2></div>
          <span className={`badge ${invite.state === 'accepted' ? 'green' : ''}`}>{statusName(invite.state)}</span></div>
        <p className="salary">{rubles(invite.salary_min_rub)} — {rubles(invite.salary_max_rub)} <small>в месяц · до налогов</small></p>
        <p><strong>Почему пригласили:</strong> {invite.reason}</p>
        <p className="small muted">Актуально на момент отправки · {invite.created_at ? date(invite.created_at) : 'дата не сохранена'} · решить до {date(invite.expires_at)}</p>
        {invite.state === 'accepted' && invite.response_due_at && <p className="small muted">Работодатель указал срок следующего шага до {date(invite.response_due_at)}.</p>}
        {invite.state === 'accepted' && <><InterviewConfirmation invite={invite} viewer="candidate" onChanged={onChanged}/><BookingLink invitationId={invite.id}/></>}
        {['sent', 'viewed'].includes(invite.state) && <div className="actions">
          <button className="primary" disabled={busyId === invite.id} onClick={() => open(invite)}>{busyId === invite.id ? 'Открываем…' : 'Проверить условия'}</button>
          <button className="button subtle" disabled={busyId === invite.id} onClick={() => reject(invite)}>Отклонить</button>
        </div>}
      </article>)}
    {active && <div className="modal-backdrop" onClick={() => { if (!busy) setActive(null) }}>
      <section className="modal card invitation-review" role="dialog" aria-modal="true" aria-labelledby="invitation-title" onClick={event => event.stopPropagation()}>
        <button className="close" type="button" onClick={() => setActive(null)} aria-label="Закрыть">×</button>
        <p className="eyebrow">ВЕРСИЯ УСЛОВИЙ · {active.company_name}</p>
        <h2 id="invitation-title">Проверьте предложение до решения</h2>
        <div className={`compatibility-summary ${active.compatibility?.status ?? 'unknown'}`}>
          <strong>{compatibilityText(active)}</strong>
          {active.compatibility?.checks.map(check => <p className={`compatibility-check ${check.status}`} key={check.code}>{check.public_text}</p>)}
        </div>
        <RoleCard role={roleFrom(active)} status="active" recordedAt={active.created_at}/>
        {active.terms_snapshot?.offer && <section className="role-detail"><h4>Ваше предложение</h4>
          <p>{rubles(active.salary_min_rub)} — {rubles(active.salary_max_rub)} в месяц, до налогов · {active.work_format}</p>
          <p>{active.offer_text}</p>
        </section>}
        {active.evidence_refs?.length ? <section className="invitation-evidence"><h3>На каких фактах основано приглашение</h3>
          {active.evidence_refs.map(card => <div className="invitation-evidence-item" key={card.id}>
            <span className={`badge ${card.verification_level === 'verified_action' ? 'green' : ''}`}>{verificationNames[card.verification_level] ?? 'Уровень подтверждения неизвестен'}</span>
            <p>{card.action}</p><ul className="evidence-limitations">{card.limitations.map(item => <li key={item}>{item}</li>)}</ul>
          </div>)}
        </section> : <p className="small muted">Для этой старой версии приглашения источники доказательств не сохранялись.</p>}
        {active.explanation_snapshot?.agenda?.length ? <section className="role-detail"><h4>Что можно обсудить</h4>
          <ul>{active.explanation_snapshot.agenda.map(item => <li key={item}>{item}</li>)}</ul></section> : null}
        {error && <div className="notice bad" role="alert">{error}</div>}
        {['sent', 'viewed'].includes(active.state) && <>
          {active.compatibility?.status === 'incompatible' && <div className="notice bad">Попросите работодателя прислать новую версию. Текущие условия нельзя принять.</div>}
          <label className="accept-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>
            Я проверил(а) зарплату, формат и этапы и принимаю именно эту версию условий.</label>
          <div className="actions"><button className="primary" disabled={busy || !confirmed || active.compatibility?.status === 'incompatible'} onClick={accept}>
            {busy ? 'Проверяем условия…' : 'Принять условия'}
          </button><button className="button subtle" disabled={busy} onClick={() => reject(active)}>Отклонить без раскрытия контактов</button></div>
        </>}
      </section>
    </div>}
  </>
}
