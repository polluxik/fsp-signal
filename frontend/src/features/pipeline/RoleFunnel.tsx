import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { PipelineVersion } from './useShortlist'

type Counts = { matched: number; invited: number; accepted: number; scheduled: number; held: number }
type Funnel = { role_version_id: string; role_version: number; title: string; current: boolean; versions: PipelineVersion[]; real: Counts; synthetic: Counts; explanation: string }
const stages = [['matched', 'Профили в подборках'], ['invited', 'Приглашены'], ['accepted', 'Приняли'], ['scheduled', 'Встречи назначены'], ['held', 'Подтверждено обоими']] as const

export default function RoleFunnel({ needId, versionId, revision }: { needId: string; versionId: string; revision: string }) {
  const [data, setData] = useState<Funnel | null>(null)
  const [historicalVersion, setHistoricalVersion] = useState('')
  const [mode, setMode] = useState<'real' | 'synthetic' | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => { setHistoricalVersion(''); setMode(null); setData(null) }, [needId, versionId])
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    api<Funnel>(`/employer/needs/${needId}/funnel?role_version_id=${historicalVersion || versionId}`, 'GET', undefined, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData(result) })
      .catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [needId, versionId, historicalVersion, revision, retry])
  const selectedMode = mode ?? (data && Object.values(data.real).some(count => count > 0) ? 'real' : 'synthetic')
  return <section className="card role-funnel" data-testid="role-funnel">
    <div className="section-title"><div><p className="eyebrow">АКТИВНОСТЬ ПО РОЛИ</p><h2>От подбора до встречи</h2></div>
      <button className="button subtle" onClick={() => setRetry(value => value + 1)}>Обновить воронку</button></div>
    {error && <p role="alert">{error}</p>}
    {!data ? <p role="status">Загружаем воронку…</p> : <>
      <label>Версия роли в воронке<select value={historicalVersion || versionId} onChange={event => { setHistoricalVersion(event.target.value); setData(null) }}>
        {data.versions.map(version => <option key={version.id} value={version.id}>v{version.version} · {version.title}</option>)}</select></label>
      {!data.current && <p className="small muted">История прежних условий. Новые приглашения относятся к текущей версии роли.</p>}
      <div className="segmented pipeline-mode" aria-label="Данные воронки">
        <button className={selectedMode === 'synthetic' ? 'active' : ''} aria-pressed={selectedMode === 'synthetic'} onClick={() => setMode('synthetic')}>Тестовые данные</button>
        <button className={selectedMode === 'real' ? 'active' : ''} aria-pressed={selectedMode === 'real'} onClick={() => setMode('real')}>Реальные данные</button>
      </div>
      <ol className="pipeline-stages">{stages.map(([key, label]) => <li key={key}><strong data-testid={`funnel-${key}`}>{data[selectedMode][key]}</strong><span>{label}</span></li>)}</ol>
      <p className="small muted">{selectedMode === 'synthetic' ? 'Учебные данные, не результаты реального найма. ' : ''}{data.explanation}</p>
    </>}
  </section>
}
