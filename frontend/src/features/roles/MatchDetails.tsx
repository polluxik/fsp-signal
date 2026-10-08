import type { CSSProperties } from 'react'
import { displayText } from '../../presentation'
import type { CandidateRoleFeedItem } from '../../types'

export default function MatchDetails({ item }: { item: CandidateRoleFeedItem }) {
  const match = item.discovery_match
  if (match?.percent == null) return <p className="small muted">Добавьте описание и навыки в профиль, чтобы увидеть персональное совпадение.</p>
  return <div className="discovery-match"><div className="match-ring" style={{ '--match': `${match.percent}%` } as CSSProperties}><strong>{match.percent}%</strong></div>
    <div><strong>Совпадение по профилю</strong><p className="small muted">Индекс близости по указанным данным. Это не вероятность найма.</p>
      <details><summary>Из чего складывается процент</summary><ul className="match-components">{match.components.map(component =>
        <li key={component.label}><span>{displayText(component.label)} <small>· вес {component.weight_percent}%</small></span><strong>{component.percent}%</strong></li>)}</ul>
        {match.peer_signal ? <p className="small">Обезличенная группа: {match.peer_signal.cohort_size} кандидатов сохранили эту роль.
          {match.peer_signal.common_skills.length > 0 && ` Часто указаны: ${match.peer_signal.common_skills.join(', ')}.`}</p>
          : <p className="small muted">Сигнал других кандидатов появится при группе из пяти и более участников, разрешивших такое использование профиля.</p>}
      </details></div></div>
}
