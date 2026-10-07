import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import type { CandidateRoleDecision, CandidateRoleFeed, CandidateRoleFeedItem } from '../../types'
import RoleCard from './RoleCard'
import MatchDetails from './MatchDetails'
import TwinDeck from './TwinDeck'

type Props = { onNavigate: (tab: string) => void }
type Filters = { specialization: string; grade: string; workFormat: string; savedOnly: boolean }

const emptyFeedMessage: Record<NonNullable<CandidateRoleFeed['empty_state']>, string> = {
  no_active_roles: 'Пока нет активных актуальных ролей в этом сегменте.',
  no_compatible_roles: 'Сейчас не нашлось ролей, проходящих ваши обязательные условия. Мы не ослабляли их автоматически.',
  no_saved_roles: 'Сохранённых ролей пока нет. Вернитесь к общей ленте и отметьте интересные.',
}

function makeQuery(filters: Filters, cursor?: string): string {
  const params = new URLSearchParams()
  if (filters.specialization) params.set('specialization', filters.specialization)
  if (filters.grade) params.set('grade', filters.grade)
  if (filters.workFormat) params.set('work_format', filters.workFormat)
  if (filters.savedOnly) params.set('saved_only', 'true')
  if (cursor) params.set('cursor', cursor)
  return params.toString()
}

function matchLabel(item: CandidateRoleFeedItem): string {
  if (item.match_state === 'compatible') return 'Обязательные условия соблюдены'
  if (item.match_state === 'needs_clarification') return 'Нужно уточнить условия'
  return 'Пока не оценивали по вашему профилю'
}

function RoleGroup({ title, items, busyId, onDecision, sponsored = false }: {
  title: string
  items: CandidateRoleFeedItem[]
  busyId: string | null
  onDecision: (item: CandidateRoleFeedItem, action: CandidateRoleDecision) => void
  sponsored?: boolean
}) {
  if (!items.length) return null
  return <section className={`feed-section${sponsored ? ' sponsored-feed-section' : ''}`}
    data-testid={sponsored ? 'sponsored-role-shelf' : undefined}>
    <div className="results-heading"><h2>{title}</h2><span className="badge">{items.length}</span></div>
    <div className="feed-list">
      {items.map(item => <div className="discovery-role" data-testid="discovery-role" data-need-id={item.need_id}
        data-campaign-id={item.campaign_id} key={item.need_id}>
        <div className="discovery-role-heading">
          <p className="discovery-company">{item.company_name}</p>
          <div className="discovery-badges">
            {sponsored && <span className="badge sponsored-label">Продвигаемая роль</span>}
            {item.data_mode === 'synthetic' && <span className="badge synthetic-badge">Демо-данные</span>}
            {item.data_mode === 'unknown' && <span className="badge unknown-source-badge">Источник данных не подтверждён</span>}
            <span className={`badge match-badge ${item.match_state}`}>{matchLabel(item)}</span>
          </div>
        </div>
        <RoleCard role={item.role} status="active" confirmedAt={item.confirmed_at}/>
        <MatchDetails item={item}/>
        {item.compatibility && <div className={`compatibility-summary ${item.compatibility.status}`}>
          <strong>{item.match_state === 'needs_clarification'
            ? item.compatibility.status === 'needs_clarification'
              ? 'Часть обязательных условий пока нельзя проверить по данным вакансии.'
              : 'Проверьте категорию роли и свою подтверждённую категорию.'
            : 'Сравнение выполнено только по указанным вами обязательным условиям.'}</strong>
          {item.compatibility.checks.some(check => check.status === 'unknown') &&
            <ul className="compatibility-unknowns">
              {item.compatibility.checks.filter(check => check.status === 'unknown').map(check =>
                <li key={check.code}>{check.public_text}</li>)}
            </ul>}
        </div>}
        {item.match_state === 'needs_clarification' && !item.compatibility &&
          <p className="small muted">Роль или профиль пока не дают проверить все условия. Дополните сведения, не ослабляя ограничения.</p>}
        {item.match_state === 'not_assessed' && <p className="small muted">Можно смотреть роли сейчас; для персонального сравнения категория профиля пока не подтверждена.</p>}
        <div className="discovery-actions">
          <button className={item.decision === 'saved' ? 'button subtle' : 'primary'}
            disabled={busyId !== null}
            aria-pressed={item.decision === 'saved'}
            onClick={() => onDecision(item, item.decision === 'saved' ? 'none' : 'saved')}>
            {item.decision === 'saved' ? 'Сохранено' : 'Сохранить'}
          </button>
          <button className="button outline" disabled={busyId !== null}
            onClick={() => onDecision(item, 'hidden')}>Скрыть</button>
        </div>
      </div>)}
    </div>
  </section>
}

export default function RoleFeed({ onNavigate }: Props) {
  const [view, setView] = useState<'list' | 'cards'>('list')
  const [recommendationConsent, setRecommendationConsent] = useState(false)
  useEffect(() => { api<{ consent: boolean }>('/candidate/recommendations/consent').then(result => setRecommendationConsent(result.consent)).catch(() => {}) }, [])
  const [filters, setFilters] = useState<Filters>({ specialization: '', grade: '', workFormat: '', savedOnly: false })
  const [items, setItems] = useState<CandidateRoleFeedItem[]>([])
  const [sponsoredItems, setSponsoredItems] = useState<CandidateRoleFeedItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [emptyState, setEmptyState] = useState<CandidateRoleFeed['empty_state']>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [refreshNotice, setRefreshNotice] = useState('')
  const [feedback, setFeedback] = useState('')
  const [undoTarget, setUndoTarget] = useState<{ item: CandidateRoleFeedItem; index: number } | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const sequence = useRef(0)
  const reportedCampaigns = useRef(new Set<string>())

  const sponsoredCampaignKey = sponsoredItems.map(item => item.campaign_id).filter(Boolean).join('|')
  useEffect(() => {
    if (!sponsoredCampaignKey || typeof IntersectionObserver === 'undefined') return
    const shelf = document.querySelector('[data-testid="sponsored-role-shelf"]')
    if (!shelf) return
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const campaignId = (entry.target as HTMLElement).dataset.campaignId
        if (!campaignId || reportedCampaigns.current.has(campaignId)) continue
        reportedCampaigns.current.add(campaignId)
        void api(`/candidate/promotions/${campaignId}/impression`, 'POST')
          .catch(() => { reportedCampaigns.current.delete(campaignId) })
        observer.unobserve(entry.target)
      }
    }, { threshold: 0.25 })
    shelf.querySelectorAll<HTMLElement>('[data-campaign-id]').forEach(card => observer.observe(card))
    return () => observer.disconnect()
  }, [sponsoredCampaignKey])

  useEffect(() => {
    const controller = new AbortController()
    const requestSequence = ++sequence.current
    setLoading(true)
    setLoadingMore(false)
    setItems([])
    setSponsoredItems([])
    setNextCursor(null)
    setEmptyState(null)
    setError('')
    api<CandidateRoleFeed>(`/candidate/roles?${makeQuery(filters)}`, 'GET', undefined, { signal: controller.signal })
      .then(feed => {
        if (sequence.current !== requestSequence) return
        setItems(feed.items)
        setSponsoredItems(feed.sponsored_items ?? [])
        setNextCursor(feed.next_cursor)
        setEmptyState(feed.empty_state)
      })
      .catch((err: Error) => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => { if (!controller.signal.aborted && sequence.current === requestSequence) setLoading(false) })
    return () => controller.abort()
  }, [filters.specialization, filters.grade, filters.workFormat, filters.savedOnly, refreshKey])

  async function loadMore() {
    if (!nextCursor || loadingMore) return
    const requestSequence = sequence.current
    setLoadingMore(true)
    setError('')
    setRefreshNotice('')
    try {
      const feed = await api<CandidateRoleFeed>(`/candidate/roles?${makeQuery(filters, nextCursor)}`)
      if (sequence.current !== requestSequence) return
      setItems(current => [...current, ...feed.items])
      setNextCursor(feed.next_cursor)
      setEmptyState(feed.empty_state)
    } catch (err) {
      if (sequence.current === requestSequence) setError((err as Error).message)
    }
    finally { if (sequence.current === requestSequence) setLoadingMore(false) }
  }

  async function decide(item: CandidateRoleFeedItem, action: CandidateRoleDecision) {
    setBusyId(item.need_id)
    setError('')
    setRefreshNotice('')
    setFeedback('')
    try {
      await api(`/candidate/role-decisions/${item.need_id}`, 'PUT', {
        action,
        expected_role_version: item.role_version_id,
        expected_preferences_version: item.preferences_version,
        ...(item.campaign_id ? { source_campaign_id: item.campaign_id } : {}),
      })
      if (action === 'hidden') {
        setUndoTarget({ item, index: (item.campaign_id ? sponsoredItems : items)
          .findIndex(candidate => candidate.need_id === item.need_id) })
        if (item.campaign_id) setSponsoredItems(current => current.filter(candidate => candidate.need_id !== item.need_id))
        else setItems(current => current.filter(candidate => candidate.need_id !== item.need_id))
        setFeedback('')
      } else if (filters.savedOnly && action !== 'saved') {
        setFeedback('Роль убрана из сохранённых.')
        setRefreshKey(value => value + 1)
      } else {
        const updateItem = (current: CandidateRoleFeedItem[]) => current.map(candidate => candidate.need_id === item.need_id
          ? { ...candidate, decision: action }
          : candidate)
        if (item.campaign_id) setSponsoredItems(updateItem)
        else setItems(updateItem)
        setFeedback(action === 'saved' ? 'Роль сохранена в вашем списке.' : 'Роль убрана из сохранённых.')
      }
      return true
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRefreshNotice('Роль или ваши условия обновились. Лента загружена заново; проверьте актуальные данные.')
        setRefreshKey(value => value + 1)
      } else {
        setError((err as Error).message)
      }
      return false
    } finally { setBusyId(null) }
  }

  async function undoHide() {
    if (!undoTarget) return
    const { item, index } = undoTarget
    setBusyId(item.need_id)
    setError('')
    setRefreshNotice('')
    try {
      await api(`/candidate/role-decisions/${item.need_id}`, 'PUT', {
        action: 'none',
        expected_role_version: item.role_version_id,
        expected_preferences_version: item.preferences_version,
        ...(item.campaign_id ? { source_campaign_id: item.campaign_id } : {}),
      })
      setUndoTarget(null)
      setFeedback('Роль возвращена в ленту.')
      const stillMatchesFilters = (!filters.specialization || filters.specialization === item.role.specialization)
        && (!filters.grade || filters.grade === item.role.grade)
        && (!filters.workFormat || filters.workFormat === item.role.work_format)
      if (filters.savedOnly || !stillMatchesFilters) {
        setRefreshKey(value => value + 1)
      } else {
        const restoreItem = (current: CandidateRoleFeedItem[]) => {
          const next = [...current]
          next.splice(Math.max(0, Math.min(index, next.length)), 0, { ...item, decision: 'none' })
          return next
        }
        if (item.campaign_id) setSponsoredItems(restoreItem)
        else setItems(restoreItem)
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRefreshNotice('Условия роли или поиска изменились. Лента обновлена; проверьте её перед отменой скрытия.')
        setUndoTarget(null)
        setRefreshKey(value => value + 1)
      } else setError((err as Error).message)
    } finally { setBusyId(null) }
  }

  const compatible = items.filter(item => item.match_state === 'compatible')
  const clarification = items.filter(item => item.match_state === 'needs_clarification')
  const notAssessed = items.filter(item => item.match_state === 'not_assessed')

  return <>
    <div className="page-heading"><p className="eyebrow">АКТУАЛЬНЫЕ РОЛИ</p><h1>Роли с понятными условиями</h1>
      <p>Ваши закрытые ограничения фильтруют выдачу и не видны работодателям. Продвигаемые роли проходят те же обязательные условия, вынесены отдельно и не дублируются в общей ленте.</p>
    </div>
    <section className="card discovery-filters" aria-label="Фильтры вакансий">
      <label>Направление<select value={filters.specialization} onChange={event => { setRefreshNotice(''); setFilters(current => ({ ...current, specialization: event.target.value })) }}>
        <option value="">Любое</option><option value="backend">Backend</option><option value="frontend">Frontend</option>
      </select></label>
      <label>Грейд<select value={filters.grade} onChange={event => { setRefreshNotice(''); setFilters(current => ({ ...current, grade: event.target.value })) }}>
        <option value="">Любой</option><option value="junior">Junior</option><option value="middle">Middle</option>
      </select></label>
      <label>Формат<select value={filters.workFormat} onChange={event => { setRefreshNotice(''); setFilters(current => ({ ...current, workFormat: event.target.value })) }}>
        <option value="">Любой</option><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option>
      </select></label>
      <label className="inline-check"><input type="checkbox" checked={filters.savedOnly}
        onChange={event => { setRefreshNotice(''); setFilters(current => ({ ...current, savedOnly: event.target.checked })) }}/>
        Только сохранённые</label>
    </section>
    <div className="feed-view-controls"><div className="segmented"><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>Список</button><button className={view === 'cards' ? 'active' : ''} onClick={() => setView('cards')}>Карточки</button></div>
      <label className="inline-check"><input type="checkbox" checked={recommendationConsent} onChange={event => {
        const consent = event.target.checked
        void api<{ consent: boolean }>('/candidate/recommendations/consent', 'PUT', { consent }).then(result => setRecommendationConsent(result.consent)).catch(err => setError(err.message))
      }}/> Разрешаю использовать моё описание и сохранения в обезличенных рекомендациях</label></div>
    {error && <div className="notice bad feed-error" role="alert"><span>{error}</span>
      <button className="text-button" onClick={() => setRefreshKey(value => value + 1)}>Обновить ленту</button>
    </div>}
    {refreshNotice && <div className="notice bad feed-error" role="alert">{refreshNotice}</div>}
    {feedback && <div className="notice good" role="status">{feedback}</div>}
    {undoTarget && <div className="notice undo-notice" role="status"><span>Роль скрыта из вашей ленты.</span>
      <button className="text-button" disabled={busyId !== null} onClick={() => void undoHide()}>Вернуть роль</button>
    </div>}
    {loading && <section className="card loading-panel" aria-busy="true"><div className="skeleton-line"/><div className="skeleton-line short"/><p className="muted">Подбираем актуальные роли…</p></section>}
    {!loading && !items.length && !sponsoredItems.length && emptyState && <section className="card empty discovery-empty">
      <h2>{emptyFeedMessage[emptyState]}</h2>
      {emptyState === 'no_saved_roles'
        ? <button className="primary" onClick={() => setFilters(current => ({ ...current, savedOnly: false }))}>Показать все роли</button>
        : emptyState === 'no_active_roles'
          ? <button className="button subtle" onClick={() => setFilters({ specialization: '', grade: '', workFormat: '', savedOnly: false })}>Сбросить фильтры ленты</button>
          : <button className="button subtle" onClick={() => onNavigate('preferences')}>Проверить условия поиска</button>}
      {emptyState === 'no_compatible_roles' && <p className="small muted">Вы можете изменить их сами; лента не ослабляет ограничения автоматически.</p>}
    </section>}
    {!loading && (!!items.length || !!sponsoredItems.length) && <>
      <RoleGroup title="Продвигаемые роли" items={sponsoredItems} busyId={busyId} sponsored
        onDecision={(item, action) => void decide(item, action)}/>
      {view === 'cards' ? <TwinDeck key={`${filters.specialization}:${filters.grade}:${filters.workFormat}:${filters.savedOnly}`} items={items} busy={busyId !== null} decide={decide}/>
        : <><RoleGroup title="Подтверждённая категория и условия подходят" items={compatible} busyId={busyId} onDecision={(item, action) => void decide(item, action)}/>
          <RoleGroup title="Нужно уточнить" items={clarification} busyId={busyId} onDecision={(item, action) => void decide(item, action)}/>
          <RoleGroup title="Пока без персональной оценки" items={notAssessed} busyId={busyId} onDecision={(item, action) => void decide(item, action)}/></>}
      {nextCursor && <div className="feed-more"><button className="button outline" disabled={loadingMore} onClick={() => void loadMore()}>
        {loadingMore ? 'Загружаем…' : 'Показать ещё 5'}
      </button></div>}
    </>}
  </>
}
