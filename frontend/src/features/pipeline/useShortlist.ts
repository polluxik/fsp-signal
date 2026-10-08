import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import type { Candidate } from '../../types'

export type PipelineVersion = { id: string; version: number; title: string }
type Entry = { candidate_id: string; role_version_id: string; saved: boolean; version: number; candidate: Candidate }
type Shortlist = { need_id: string; role_version_id: string; role_version: number; current: boolean; versions: PipelineVersion[]; entries: Entry[]; unavailable_count: number }

export function useShortlist(needId: string, versionId: string | null, tab: string) {
  const [result, setResult] = useState<Shortlist | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const scope = `${needId}:${versionId}`
  const scopeRef = useRef(scope)
  scopeRef.current = scope
  useEffect(() => { setError('') }, [needId, versionId, tab])
  useEffect(() => {
    const controller = new AbortController()
    if (!needId || !versionId) { setResult(null); setLoading(false); return }
    setLoading(true)
    api<Shortlist>(`/employer/needs/${needId}/shortlist?role_version_id=${versionId}`, 'GET', undefined, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setResult(data) })
      .catch(err => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [needId, versionId, tab, revision])
  const data = result?.need_id === needId && result.role_version_id === versionId ? result : null
  async function toggle(candidateId: string) {
    if (!data || busy || loading) return
    const entry = data.entries.find(item => item.candidate_id === candidateId)
    const capturedScope = scope
    setError(''); setBusy(candidateId)
    try {
      await api(`/employer/needs/${needId}/shortlist/${candidateId}`, 'PUT', {
        role_version_id: versionId, expected_version: entry?.version ?? 0, saved: !entry?.saved,
      })
      if (scopeRef.current === capturedScope) setRevision(value => value + 1)
    } catch (err) {
      if (scopeRef.current === capturedScope) {
        setError((err as Error).message)
        if (err instanceof ApiError && err.status === 409) setRevision(value => value + 1)
      }
    } finally { setBusy('') }
  }
  return { data, loading, busy, error, toggle,
    refresh: () => { setError(''); setRevision(value => value + 1) } }
}
