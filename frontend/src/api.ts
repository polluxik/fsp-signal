import type { Profile } from './types'

export type ApiOptions = { signal?: AbortSignal; idempotencyKey?: string }

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(messageFor(code, status))
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const messages: Record<string, string> = {
  AVAILABILITY_RANGE_INVALID: 'Выберите будущий диапазон от 20 минут до 12 часов в пределах 90 дней.',
  AVAILABILITY_NOT_DIVISIBLE: 'Диапазон должен делиться на выбранную длительность 20 или 30 минут.',
  AVAILABILITY_OVERLAP: 'Диапазон пересекается с уже открытыми слотами. Уберите прежние или выберите другое время.',
  SLOT_ALREADY_BOOKED: 'Время уже занято или встреча по этому приглашению назначена. Обновите календарь.',
  SLOT_NOT_AVAILABLE: 'Слот больше недоступен. Выберите другое время.',
  MEETING_TIME_CONFLICT: 'На это время у вас уже есть встреча с другой компанией.',
  ACCEPT_INVITATION_FIRST: 'Сначала примите приглашение этой компании.',
  MEETING_VERSION_CONFLICT: 'Встреча обновилась. Обновите список встреч и проверьте актуальные данные.',
  RECORDING_CONSENT_REQUIRED: 'Для записи и расшифровки нужны согласия обоих участников.',
  MEETING_NOT_STARTED: 'Запись можно добавить после начала встречи.',
  MEETING_NOT_FINISHED: 'Добавьте расшифровку после окончания встречи.',
  TRANSCRIPT_REQUIRED: 'Сначала сохраните расшифровку встречи.',
  TRANSCRIPTION_PROVIDER_DISABLED: 'Автоматическая расшифровка пока недоступна. Вставьте готовый текст беседы.',
  AUDIO_TOO_LARGE: 'Загрузите аудио не больше 15 МБ.',
  AUDIO_FORMAT_INVALID: 'Поддерживаются аудио WebM, Ogg, WAV, MP3 и M4A.',
  PROFILE_REQUIRED: 'Сначала сохраните профиль кандидата.',
  LOGIN_REQUIRED: 'Войдите в аккаунт',
  EMAIL_NOT_VERIFIED: 'Сначала подтвердите email',
  INVALID_CREDENTIALS: 'Неверный email или пароль',
  CONSENT_REQUIRED: 'Нужно согласие на обработку данных',
  ASSESSMENT_ATTEMPT_LIMIT: 'Лимит: три попытки за семь дней',
  ASSESSMENT_RETRY_COOLDOWN: 'Повтор этого теста доступен через 72 часа',
  GRADE_CHANGE_COOLDOWN: 'Смена грейда доступна через 30 дней после предыдущей',
  ANSWERS_INCOMPLETE: 'Ответьте на все вопросы',
  SALARY_RANGE_INVALID: 'Проверьте зарплатный диапазон и ожидания кандидата',
  ACTIVE_INVITATION_EXISTS: 'У вашей компании уже есть активное приглашение этому кандидату',
  COMPANY_PROFILE_REQUIRED: 'Перед отправкой приглашения заполните профиль компании.',
  CONTACT_LOCKED: 'Контакты откроются после принятия приглашения',
  ORIGIN_FORBIDDEN: 'Некорректный адрес приложения; проверьте PUBLIC_BASE_URL сервера',
  PREFERENCES_VERSION_REQUIRED: 'Не удалось проверить актуальные условия. Обновите страницу и повторите сохранение.',
  PREFERENCES_VERSION_CONFLICT: 'Условия изменились в другой вкладке. Несохранённые изменения остались в форме; проверьте актуальные условия перед повторным сохранением.',
  ROLE_VERSION_CONFLICT: 'Роль уже изменена. Обновите версию перед повторным сохранением.',
  ROLE_INCOMPLETE: 'Заполните обязательные условия роли перед публикацией',
  ROLE_NOT_ACTIVE: 'Сначала опубликуйте актуальную роль',
  ROLE_STALE: 'Подтвердите актуальность роли перед отправкой приглашения',
  INVITATION_STATE_CONFLICT: 'Состояние приглашения уже изменилось. Обновите список.',
  TERMS_VERSION_CONFLICT: 'Условия приглашения изменились. Откройте их заново перед решением.',
  INVITATION_TERMS_CHANGED: 'Условия приглашения изменились. Проверьте их заново.',
  PREFERENCES_CHANGED: 'Ваши условия поиска изменились. Проверьте совместимость заново.',
  EXTERNAL_AI_CONSENT_REQUIRED: 'Подтвердите отправку текста внешнему AI-провайдеру.',
  AI_PROVIDER_DISABLED: 'ИИ-помощник сейчас недоступен. Продолжайте заполнять форму вручную.',
  AI_PROVIDER_TIMEOUT: 'ИИ-помощник не успел ответить вовремя. Провайдер мог продолжить обработку запроса; подождите перед повтором. Текст остался в форме — можно продолжить вручную.',
  AI_PROVIDER_UNAVAILABLE: 'ИИ-помощник временно недоступен. Текст остался в форме — попробуйте ещё раз или продолжите вручную.',
  AI_PROVIDER_INVALID_RESPONSE: 'Не удалось разобрать ответ помощника. Ваш текст не потерян; проверьте его и попробуйте ещё раз.',
  AI_INPUT_TOO_LONG: 'Сократите текст до 2 000 символов.',
  AI_INPUT_REQUIRED: 'Добавьте короткое описание, чтобы составить черновик.',
  AI_RATE_LIMIT_EXCEEDED: 'Лимит запросов к помощнику на этот час исчерпан. Заполните форму вручную или попробуйте позже.',
  PROMOTION_ROLE_NOT_ELIGIBLE: 'Роль должна быть активной, доступной кандидатам и подтверждённой не более 14 дней назад.',
  PROMOTION_NOT_AVAILABLE: 'Эта продвигаемая роль больше недоступна. Обновите ленту.',
}

function messageFor(code: string, status: number): string {
  if (messages[code]) return messages[code]
  if (status >= 500) return 'Сервис временно недоступен. Данные в форме сохранены; попробуйте позже.'
  return 'Не удалось выполнить операцию. Проверьте данные и повторите попытку.'
}

function csrfToken(): string {
  return document.cookie.split('; ').find(item => item.startsWith('fsp_csrf='))?.split('=')[1] ?? ''
}

export async function uploadMeetingRecording(id: string, version: number, file: File | Blob) {
  const data = new FormData()
  data.append('file', file, file instanceof File ? file.name : 'meeting.webm')
  const response = await fetch(`/api/v1/meetings/${id}/recording?expected_version=${version}`, {
    method: 'POST', credentials: 'same-origin', headers: { 'x-csrf-token': decodeURIComponent(csrfToken()) }, body: data,
  })
  const result = await response.json()
  if (!response.ok) throw new ApiError(response.status, result?.detail ?? '')
  return result
}

export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  options: ApiOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken()) headers['x-csrf-token'] = decodeURIComponent(csrfToken())
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    signal: options.signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    throw new ApiError(response.status, typeof detail === 'string' ? detail : '')
  }
  return data as T
}

export async function uploadResume(file: File): Promise<Pick<Profile,
  'full_name' | 'contact_email' | 'contact_phone' | 'summary' | 'skills' | 'experience_months'> & {
    warnings: string[]
    pages: number
  }> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/v1/candidate/resume/preview', {
    method: 'POST',
    body,
    credentials: 'same-origin',
    headers: { 'x-csrf-token': decodeURIComponent(csrfToken()) },
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const uploadMessages: Record<string, string> = {
      PDF_TOO_LARGE: 'PDF больше 5 МБ',
      NOT_A_PDF: 'Выберите PDF-файл',
      PDF_ENCRYPTED: 'PDF защищён паролем',
      PDF_PAGE_LIMIT: 'Допускается PDF до 10 страниц',
      PDF_UNREADABLE: 'Не удалось прочитать PDF',
      PDF_TEXT_NOT_FOUND: 'В PDF нет текстового слоя. Заполните форму вручную.',
    }
    throw new ApiError(response.status, uploadMessages[data?.detail] ?? data?.detail ?? '')
  }
  return data
}
