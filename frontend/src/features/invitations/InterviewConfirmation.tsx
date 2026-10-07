import { useState } from 'react'
import { api } from '../../api'
import type { Invite } from '../../types'

type Props = {
  invite: Invite
  viewer: 'candidate' | 'employer'
  onChanged: () => Promise<void>
}

export default function InterviewConfirmation({ invite, viewer, onChanged }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const candidateConfirmed = invite.candidate_interview_confirmed
  const employerConfirmed = invite.employer_interview_confirmed
  const bothConfirmed = candidateConfirmed && employerConfirmed
  const mineConfirmed = viewer === 'candidate' ? candidateConfirmed : employerConfirmed
  const otherParty = viewer === 'candidate' ? 'работодателя' : 'кандидата'

  if (invite.state !== 'accepted') return null

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await api(`/invitations/${invite.id}/interview-held-confirmation`, 'POST')
      await onChanged()
    } catch (err) {
      setError((err as Error).message)
      try { await onChanged() } catch { /* keep the original actionable error */ }
    } finally {
      setBusy(false)
    }
  }

  return <section className="interview-confirmation" aria-label="Подтверждение состоявшейся встречи">
    {bothConfirmed
      ? <p className="notice good" role="status">Встреча подтверждена обеими сторонами.</p>
      : mineConfirmed
        ? <p className="small muted" role="status">Вы подтвердили встречу. Ждём подтверждения {otherParty}.</p>
        : <div><p className="small muted">Отметьте только состоявшуюся встречу. Она учитывается после подтверждения обеих сторон.</p>
          <button className="button outline" type="button" disabled={busy} onClick={() => void confirm()}>
            {busy ? 'Сохраняем подтверждение…' : 'Подтвердить встречу'}
          </button></div>}
    {error && <div className="notice bad" role="alert">{error}</div>}
  </section>
}
