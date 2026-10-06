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
  CONTACT_LOCKED: 'Контакты откроются после принятия приглашения',
  ORIGIN_FORBIDDEN: 'Некорректный адрес приложения; проверьте PUBLIC_BASE_URL сервера',
  PREFERENCES_VERSION_CONFLICT: 'Предпочтения изменились в другой вкладке. Ваш черновик сохранён.',
  ROLE_VERSION_CONFLICT: 'Роль уже изменена. Обновите версию перед повторным сохранением.',
  ROLE_INCOMPLETE: 'Заполните обязательные условия роли перед публикацией',
  ROLE_NOT_ACTIVE: 'Сначала опубликуйте актуальную роль',
  ROLE_STALE: 'Подтвердите актуальность роли перед отправкой приглашения',
  INVITATION_STATE_CONFLICT: 'Состояние приглашения уже изменилось. Обновите список.',
  INVITATION_TERMS_CHANGED: 'Условия приглашения изменились. Проверьте их заново.',
  PREFERENCES_CHANGED: 'Ваши условия поиска изменились. Проверьте совместимость заново.',
}

function messageFor(code: string, status: number): string {
  return messages[code] ?? (code || `Ошибка ${status}`)
}

function csrfToken(): string {
  return document.cookie.split('; ').find(item => item.startsWith('fsp_csrf='))?.split('=')[1] ?? ''
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
