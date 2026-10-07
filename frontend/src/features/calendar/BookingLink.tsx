import { useEffect, useState } from 'react'
import { api } from '../../api'

export default function BookingLink({ invitationId, employer = false }: { invitationId: string; employer?: boolean }) {
  const [url, setUrl] = useState('')
  useEffect(() => { api<{ url: string }>(`/invitations/${invitationId}/calendar`).then(result => setUrl(result.url)).catch(() => setUrl('')) }, [invitationId])
  if (!url) return null
  return <a className="button outline booking-link" href={url}>{employer ? 'Открыть календарь для кандидата' : 'Выбрать время созвона'} →</a>
}
