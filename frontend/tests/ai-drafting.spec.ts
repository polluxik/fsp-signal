import { expect, test } from '@playwright/test'
import { signIn } from './test-support'

test('candidate preference assistant requires opt-in and applies only an editable draft', async ({ page }) => {
  let requestBody: Record<string, unknown> | undefined
  let preferenceWrites = 0
  await page.route('**/api/v1/assistant/candidate/preferences', async route => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      salary_min_rub: 180000,
      allowed_work_formats: ['remote'],
      allowed_cities: ['Казань'],
      excluded_industries: [],
      preferred_stack: ['Python', 'PostgreSQL'],
      preferred_tasks: ['Надёжность API'],
      max_take_home_minutes: 60,
      missing_fields: ['excluded_industries'],
      follow_up_questions: ['Есть ли отрасли, которые нужно исключить?'],
    }) })
  })
  await page.route('**/api/v1/candidate/preferences', async route => {
    if (route.request().method() === 'PUT') preferenceWrites += 1
    await route.continue()
  })

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Условия поиска' }).click()
  const assistant = page.getByTestId('assistant-candidate-preferences')
  await assistant.getByLabel('Что важно в работе?').fill('Удалённая работа, задачи на надёжность API, от 180 тысяч рублей.')
  await expect(assistant.getByRole('button', { name: 'Составить черновик' })).toBeDisabled()
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()

  await expect(assistant.getByRole('heading', { name: 'Черновик предпочтений' })).toBeVisible()
  expect(requestBody).toEqual({
    text: 'Удалённая работа, задачи на надёжность API, от 180 тысяч рублей.',
    external_ai_consent: true,
  })
  await expect(page.getByLabel(/Минимум, ₽ в месяц/)).toHaveValue('170000')
  await expect(assistant.getByText('Есть ли отрасли, которые нужно исключить?')).toBeVisible()
  await assistant.getByRole('button', { name: 'Применить в форму' }).click()
  await expect(page.getByLabel(/Минимум, ₽ в месяц/)).toHaveValue('180000')
  await expect(page.getByLabel(/Интересующий стек/)).toHaveValue('Python, PostgreSQL')
  expect(preferenceWrites).toBe(0)
})

test('candidate achievement assistant keeps drafts private and does not save automatically', async ({ page }) => {
  let profileWrites = 0
  await page.route('**/api/v1/assistant/candidate/achievement', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      title: 'Защита от повторной обработки',
      context: 'События могли приходить повторно и создавать дубли.',
      personal_contribution: 'Добавил проверку event ID перед записью.',
      decision: 'Использовал уникальное ограничение на стороне базы.',
      result: 'Повторная доставка больше не создавала дубли.',
      result_scope: 'individual',
      basis: '',
      missing_fields: [],
      follow_up_questions: [],
    }) })
  })
  await page.route('**/api/v1/candidate/profile', async route => {
    if (route.request().method() === 'PUT') profileWrites += 1
    await route.continue()
  })

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Мой профиль' }).click()
  const assistant = page.getByTestId('assistant-candidate-achievement')
  await assistant.getByLabel('Расскажите, что произошло').fill('Я добавил защиту от повторной обработки событий по event ID.')
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  await expect(assistant.getByRole('heading', { name: 'Черновик рассказа' })).toBeVisible()
  await assistant.getByRole('button', { name: 'Применить в форму' }).click()

  await expect(page.getByLabel(/Контекст: какую задачу/)).toHaveValue('События могли приходить повторно и создавать дубли.')
  await expect(page.getByLabel(/Ваш личный вклад/)).toHaveValue('Добавил проверку event ID перед записью.')
  const employerSharing = page.getByRole('checkbox', { name: /Отдельно разрешаю показать этот рассказ/ })
  await expect(employerSharing).not.toBeChecked()
  await employerSharing.check()
  await page.getByLabel(/Что изменилось/).fill('После изменения пользователь явно перепроверяет текст.')
  await expect(employerSharing).not.toBeChecked()
  expect(profileWrites).toBe(0)
})

test('employer role assistant leaves the role editable and does not create a new version', async ({ page }) => {
  let versionWrites = 0
  await page.route('**/api/v1/assistant/employer/role', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      title: 'QA Junior — платёжные сценарии',
      description: 'Проверять платёжные сценарии, API и повторную доставку событий.',
      specialization: 'qa',
      grade: 'junior',
      competencies: ['test_design', 'api_testing'],
      stack: ['Playwright', 'HTTP API'],
      salary_min_rub: 140000,
      salary_max_rub: 180000,
      work_format: 'remote',
      work_city: null,
      industry: 'Финтех',
      first_30_days: 'Собрать карту рисков для критичных платёжных сценариев.',
      interview_steps: [{ title: 'Разбор тестового сценария', duration_minutes: 45 }],
      take_home_minutes: 0,
      response_sla_hours: 48,
      missing_fields: [],
      ambiguous_fields: [],
      follow_up_questions: [],
    }) })
  })
  await page.route('**/api/v1/employer/needs/*/versions', async route => {
    if (route.request().method() === 'POST') versionWrites += 1
    await route.continue()
  })

  await signIn(page, 'employer@demo.test')
  await page.getByRole('button', { name: 'Роль и условия' }).click()
  const assistant = page.getByTestId('assistant-employer-role')
  await assistant.getByLabel('Опишите роль своими словами').fill('Нужен QA junior для проверки платёжных API и повторных событий.')
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  await expect(assistant.getByRole('heading', { name: 'Черновик вакансии' })).toBeVisible()
  await assistant.getByRole('button', { name: 'Применить в форму' }).click()

  await expect(page.getByLabel('Название роли')).toHaveValue('QA Junior — платёжные сценарии')
  await expect(page.getByLabel('Направление')).toHaveValue('qa')
  await expect(page.getByRole('checkbox', { name: 'Проектирование проверок' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Проверка API' })).toBeChecked()
  await expect(page.getByLabel(/Результат первых 30 дней/)).toHaveValue('Собрать карту рисков для критичных платёжных сценариев.')
  expect(versionWrites).toBe(0)
})

test('provider failure keeps the candidate text and the regular preferences form available', async ({ page }) => {
  await page.route('**/api/v1/assistant/candidate/preferences', route =>
    route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'AI_PROVIDER_DISABLED' }) }))

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Условия поиска' }).click()
  const assistant = page.getByTestId('assistant-candidate-preferences')
  const text = 'Нужна удалённая работа и никаких многочасовых тестовых заданий.'
  await assistant.getByLabel('Что важно в работе?').fill(text)
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  await expect(assistant.getByRole('alert')).toContainText(/ИИ-помощник сейчас недоступен/i)
  await expect(assistant.getByLabel('Что важно в работе?')).toHaveValue(text)
  await page.getByLabel(/Минимум, ₽ в месяц/).fill('175000')
  await page.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(page.getByRole('status')).toContainText('Условия обновлены')
})

test('assistant shows the extended wait state and prevents duplicate submissions while pending', async ({ page }) => {
  let releaseResponse: (() => void) | undefined
  const responseGate = new Promise<void>(resolve => { releaseResponse = resolve })
  let requestCount = 0
  await page.route('**/api/v1/assistant/candidate/preferences', async route => {
    requestCount += 1
    await responseGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      salary_min_rub: 160000,
      allowed_work_formats: ['remote'],
      missing_fields: ['allowed_cities'],
      follow_up_questions: ['Какие города вам подходят?'],
    }) })
  })

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Условия поиска' }).click()
  const assistant = page.getByTestId('assistant-candidate-preferences')
  await assistant.getByLabel('Что важно в работе?').fill('Удалённая работа на Python от 160 тысяч рублей.')
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()
  const submit = assistant.getByRole('button', { name: 'Составить черновик' })
  await submit.click()

  await expect(assistant.getByRole('status')).toContainText('до 30 секунд')
  await expect(assistant.getByRole('button', { name: 'Готовим черновик…' })).toBeDisabled()
  expect(requestCount).toBe(1)

  releaseResponse?.()
  await expect(assistant.getByRole('heading', { name: 'Черновик предпочтений' })).toBeVisible()
  expect(requestCount).toBe(1)
})

test('assistant timeout warns before a possible duplicate and keeps manual editing available', async ({ page }) => {
  let requestCount = 0
  await page.route('**/api/v1/assistant/candidate/preferences', async route => {
    requestCount += 1
    await route.fulfill({ status: 504, contentType: 'application/json', body: JSON.stringify({ detail: 'AI_PROVIDER_TIMEOUT' }) })
  })

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Условия поиска' }).click()
  const assistant = page.getByTestId('assistant-candidate-preferences')
  const text = 'Удалённая работа и задачи на устойчивость сервиса.'
  await assistant.getByLabel('Что важно в работе?').fill(text)
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()

  await expect(assistant.getByRole('alert')).toContainText('подождите перед повтором')
  await expect(assistant.getByLabel('Что важно в работе?')).toHaveValue(text)
  await expect(assistant.getByLabel(/Понимаю: этот текст будет отправлен/)).not.toBeChecked()
  await expect(assistant.getByRole('button', { name: 'Составить черновик' })).toBeDisabled()
  expect(requestCount).toBe(1)

  await page.getByLabel(/Минимум, ₽ в месяц/).fill('175000')
  await page.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(page.getByRole('status')).toContainText('Условия обновлены')
})
