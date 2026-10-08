import { useEffect, useRef, useState } from 'react'
import { api, uploadMeetingRecording } from '../../api'
import { displayText } from '../../presentation'
import type { Invite } from '../../types'
import BookingLink from './BookingLink'
import { type Meeting, moment } from './types'

type Capabilities = { summary: boolean; transcription: boolean }

function MeetingCard({ initial, viewer, capabilities, onChanged }: {
  initial: Meeting; viewer: 'candidate' | 'employer'; capabilities: Capabilities; onChanged?: () => void
}) {
  const [meeting, setMeeting] = useState(initial)
  const [notes, setNotes] = useState(initial.notes)
  const [transcript, setTranscript] = useState(initial.transcript)
  const [externalConsent, setExternalConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [recording, setRecording] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mounted = useRef(true)
  const dirty = notes !== meeting.notes || transcript !== meeting.transcript
  useEffect(() => {
    // Repeated reads (including StrictMode startup) must not erase a draft.
    if (initial.version === meeting.version && initial.access_revoked === meeting.access_revoked) return
    if (dirty && !initial.access_revoked &&
        initial.candidate_recording_consent === meeting.candidate_recording_consent &&
        initial.employer_recording_consent === meeting.employer_recording_consent) {
      setError('Материалы изменились у другого участника. Ваш черновик сохранён на экране; загрузите актуальную версию перед сохранением.')
      return
    }
    setMeeting(initial)
    setNotes(initial.notes); setTranscript(initial.transcript)
  }, [initial])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (timer.current) clearTimeout(timer.current)
      if (recorder.current?.state === 'recording') recorder.current.stop()
      stream.current?.getTracks().forEach(track => track.stop())
    }
  }, [])
  async function act(job: () => Promise<Meeting>, text: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await job()
      if (!mounted.current) return
      setMeeting(updated); setNotes(updated.notes); setTranscript(updated.transcript)
      setNotice(text); onChanged?.()
    } catch (err) { if (mounted.current) setError((err as Error).message) }
    finally { if (mounted.current) setBusy(false) }
  }
  const bothConsented = meeting.candidate_recording_consent && meeting.employer_recording_consent
  const ownConsent = viewer === 'candidate' ? meeting.candidate_recording_consent : meeting.employer_recording_consent
  const finished = Date.parse(meeting.ends_at) <= Date.now()
  const started = Date.parse(meeting.starts_at) <= Date.now()
  async function recordMicrophone() {
    setError('')
    try {
      if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') throw new Error('Запись недоступна в этом браузере. Загрузите готовое аудио.')
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.current = audioStream
      const type = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg'
      const mediaRecorder = new MediaRecorder(audioStream, { mimeType: type })
      const chunks: BlobPart[] = []
      recorder.current = mediaRecorder
      mediaRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      mediaRecorder.onstop = () => {
        if (timer.current) clearTimeout(timer.current)
        audioStream.getTracks().forEach(track => track.stop())
        if (!mounted.current) return
        setRecording(false)
        const blob = new Blob(chunks, { type })
        if (blob.size > 15 * 1024 * 1024) { setError('Запись превышает 15 МБ. Загрузите более короткий файл.'); return }
        void act(() => uploadMeetingRecording(meeting.id, meeting.version, blob), 'Запись микрофона сохранена.')
      }
      mediaRecorder.start(1000); setRecording(true)
      timer.current = setTimeout(() => { if (mediaRecorder.state === 'recording') mediaRecorder.stop() }, 5 * 60 * 1000)
    } catch (err) { stream.current?.getTracks().forEach(track => track.stop()); setError((err as Error).message) }
  }
  return <article className="card meeting-card" data-testid="meeting-card"><div className="section-title"><div>
    <p className="eyebrow">{displayText(viewer === 'candidate' ? meeting.company_name : meeting.candidate_alias)}</p>
    <h3>{moment(meeting.starts_at)} — {new Date(meeting.ends_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</h3>
    </div><span className={`badge ${meeting.state === 'cancelled' ? '' : 'green'}`}>{meeting.state === 'cancelled' ? 'Отменена' : finished ? 'Время завершено' : 'Назначена'}</span></div>
    {error && <div className="notice bad" role="alert">{error}</div>}{notice && <div className="notice good" role="status">{notice}</div>}
    <div className="meeting-actions"><a className="button outline" href={`/api/v1/meetings/${meeting.id}/calendar.ics`}>В мой календарь</a>
      {meeting.call_url && meeting.state !== 'cancelled' && <a className="button primary" href={meeting.call_url} target="_blank" rel="noreferrer">Перейти к созвону</a>}
      {meeting.state === 'scheduled' && !finished && <button className="button subtle" disabled={busy || recording || dirty}
        onClick={() => void act(() => api(`/meetings/${meeting.id}/cancel`, 'POST', { expected_version: meeting.version }), 'Встреча отменена, слот снова свободен.')}>Отменить встречу</button>}</div>
    {meeting.access_revoked ? <p className="muted">Кандидат отозвал доступ к материалам. Время встречи можно отменить.</p> : <>
      <label className="inline-check recording-consent"><input type="checkbox" checked={ownConsent} disabled={busy || dirty || recording}
        onChange={event => void act(() => api(`/meetings/${meeting.id}/recording-consent`, 'PUT', { expected_version: meeting.version, consent: event.target.checked }), event.target.checked ? 'Согласие сохранено.' : 'Согласие отозвано. Аудио, расшифровка и AI-итоги удалены.')}/>
        Я согласен на хранение записи и расшифровки этой встречи</label>
      <p className="small muted">{bothConsented ? 'Оба участника согласны. Материалы доступны только вам двоим.' : 'Для записи и расшифровки нужны согласия обоих участников.'}</p>
      {meeting.state === 'scheduled' && bothConsented && started && <div className="recording-tools">
        <button className={`button ${recording ? 'recording-stop' : 'outline'}`} disabled={busy || dirty}
          onClick={() => recording ? recorder.current?.stop() : void recordMicrophone()}>{recording ? 'Остановить и сохранить' : 'Записать мой микрофон'}</button>
        <label className="button outline">Загрузить запись<input className="visually-hidden" type="file" accept="audio/webm,audio/ogg,audio/wav,audio/mpeg,audio/mp4" disabled={busy || dirty || recording}
          onChange={event => { const file = event.target.files?.[0]; if (file) void act(() => uploadMeetingRecording(meeting.id, meeting.version, file), 'Аудио сохранено.'); event.target.value = '' }}/></label>
        <p className="small muted">Браузер пишет ваш микрофон до 5 минут. Для полной записи звонка загрузите аудио из сервиса созвона (до 15 МБ).</p>
      </div>}
      {meeting.has_recording && bothConsented && <audio controls preload="none" src={`/api/v1/meetings/${meeting.id}/recording`}/>}
      <div className="meeting-materials"><label>Общие заметки и договорённости<textarea rows={4} value={notes} maxLength={12000} disabled={busy || recording} onChange={event => setNotes(event.target.value)}/></label>
        <label>Расшифровка встречи<textarea rows={6} value={transcript} maxLength={12000} disabled={busy || recording || !bothConsented || !finished}
          onChange={event => setTranscript(event.target.value)} placeholder="Вставьте текст беседы после окончания встречи"/></label>
        <p className="small muted">{finished ? 'До 12 000 символов. Изменение расшифровки сбрасывает прежние AI-итоги.' : 'Расшифровка станет доступна после окончания встречи.'}</p>
        <button className="button outline" disabled={busy || recording || !dirty} onClick={() => void act(() => api(`/meetings/${meeting.id}/materials`, 'PUT', { expected_version: meeting.version, notes, transcript }), 'Материалы сохранены.')}>Сохранить материалы</button>
      </div>
      {dirty && <p className="small muted">Сначала сохраните материалы, чтобы продолжить.</p>}
      {dirty && <button className="text-button" disabled={busy || recording} onClick={() => {
        setMeeting(initial); setNotes(initial.notes); setTranscript(initial.transcript); setError('')
      }}>Загрузить актуальные материалы и убрать мой черновик</button>}
      {finished && bothConsented && <div className="meeting-ai"><label className="inline-check"><input type="checkbox" checked={externalConsent} onChange={event => setExternalConsent(event.target.checked)}/>
        Разрешаю отправить материал внешнему AI-сервису для обработки</label>
        <div className="meeting-actions"><button className="button outline" disabled={busy || dirty || !externalConsent || !meeting.has_recording || !capabilities.transcription}
          onClick={() => void act(() => api(`/meetings/${meeting.id}/transcribe`, 'POST', { expected_version: meeting.version, external_ai_consent: true }), 'Расшифровка готова. Проверьте текст.')}>Расшифровать аудио</button>
          <button className="primary" disabled={busy || dirty || !externalConsent || !meeting.transcript.trim() || !capabilities.summary}
            onClick={() => void act(() => api(`/meetings/${meeting.id}/summary`, 'POST', { expected_version: meeting.version, external_ai_consent: true }), 'Черновик итогов готов.')}>{busy ? 'Обрабатываем…' : 'Собрать итоги встречи'}</button></div>
        {!capabilities.transcription && <p className="small muted">Автоматическая расшифровка аудио пока недоступна. Вставьте готовый текст выше, чтобы получить итоги.</p>}
      </div>}
      {meeting.summary && <section className="meeting-summary"><p className="eyebrow">AI-ЧЕРНОВИК · ПРОВЕРЬТЕ ПО БЕСЕДЕ</p><h3>Итоги встречи</h3><p>{meeting.summary.summary}</p>
        {([['decisions', 'Решения'], ['next_steps', 'Следующие шаги'], ['open_questions', 'Открытые вопросы']] as const).map(([key, title]) =>
          meeting.summary![key].length > 0 && <div key={key}><h4>{title}</h4><ul>{meeting.summary![key].map((text, index) => <li key={index}>{text}</li>)}</ul></div>)}
      </section>}
    </>}
  </article>
}

export default function MeetingList({ viewer, onChanged }: { viewer: 'candidate' | 'employer'; onChanged?: () => void }) {
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [invites, setInvites] = useState<Invite[]>([])
  const [capabilities, setCapabilities] = useState<Capabilities>({ summary: false, transcription: false })
  const [error, setError] = useState('')
  async function load() {
    setMeetings(await api<Meeting[]>('/meetings'))
    setCapabilities(await api<Capabilities>('/meetings/capabilities'))
    if (viewer === 'candidate') setInvites((await api<Invite[]>('/candidate/invitations')).filter(invite => invite.state === 'accepted'))
  }
  useEffect(() => { void load().catch(err => setError(err.message)) }, [viewer])
  return <section className="meetings-panel"><div className="section-title"><h2>Ваши встречи</h2><button className="button outline" onClick={() => void load().then(() => setError('')).catch(err => setError(err.message))}>Обновить встречи</button></div>
    <p className="small muted">Время показано в {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>
    {error && <div className="notice bad" role="alert">{error}</div>}
    {viewer === 'candidate' && invites.length > 0 && <section className="card"><h3>Назначить разговор</h3>{invites.map(invite => <div className="calendar-invitation" key={invite.id}><span>{displayText(invite.company_name)}</span><BookingLink invitationId={invite.id}/></div>)}</section>}
    {!meetings.length && <div className="card empty">Пока нет назначенных встреч.</div>}
    {meetings.map(meeting => <MeetingCard key={meeting.id} initial={meeting} viewer={viewer} capabilities={capabilities} onChanged={onChanged}/>)}
  </section>
}
