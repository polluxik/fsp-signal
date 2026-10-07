import { expect, test } from '@playwright/test'
import { signIn } from './test-support'

const liveAiEnabled = process.env.FSP_SIGNAL_LIVE_AI === '1'
  && Boolean(process.env.FRONTIERAI_API_KEY?.trim())

test('configured FrontierAI provider returns a validated preference draft through the real app route', async ({ page }) => {
  test.skip(!liveAiEnabled, 'Opt in with FSP_SIGNAL_LIVE_AI=1 and FRONTIERAI_API_KEY for one billable synthetic request.')
  test.setTimeout(60_000)

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Условия поиска' }).click()
  const assistant = page.getByTestId('assistant-candidate-preferences')
  await assistant.getByLabel('Что важно в работе?').fill(
    'Ищу удалённую работу с Python и PostgreSQL, зарплата от 160000 рублей.',
  )
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()

  const responsePromise = page.waitForResponse(response =>
    response.url().endsWith('/api/v1/assistant/candidate/preferences')
    && response.request().method() === 'POST')
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)

  const draft = await response.json() as {
    salary_min_rub: number | null
    preferred_stack: string[]
  }
  expect(draft.salary_min_rub).toBe(160000)
  expect(draft.preferred_stack).toContain('Python')
  await expect(assistant.getByRole('heading', { name: 'Черновик предпочтений' })).toBeVisible()
  await expect(assistant.getByText(/160/)).toBeVisible()
})

test('configured FrontierAI provider returns an achievement draft through the real app route', async ({ page }) => {
  test.skip(!liveAiEnabled, 'Opt in with FSP_SIGNAL_LIVE_AI=1 and FRONTIERAI_API_KEY for one billable synthetic request.')
  test.setTimeout(60_000)

  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Мой профиль' }).click()
  const assistant = page.getByTestId('assistant-candidate-achievement')
  await assistant.getByLabel('Расскажите, что произошло').fill(
    'Повторная доставка одного события создавала дубли в базе. Я добавил уникальную проверку event ID в PostgreSQL. После этого повторы не создавали дубли; работу выполнил самостоятельно.',
  )
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()

  const responsePromise = page.waitForResponse(response =>
    response.url().endsWith('/api/v1/assistant/candidate/achievement')
    && response.request().method() === 'POST')
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)

  const draft = await response.json() as {
    context: string
    personal_contribution: string
    result: string
    result_scope: 'individual' | 'team' | null
  }
  expect(draft.context.length).toBeGreaterThan(0)
  expect(draft.personal_contribution.length).toBeGreaterThan(0)
  expect(draft.result.length).toBeGreaterThan(0)
  expect(draft.result_scope).toBe('individual')
  await expect(assistant.getByRole('heading', { name: 'Черновик рассказа' })).toBeVisible()
})

test('configured FrontierAI provider returns a typed employer role draft through the real app route', async ({ page }) => {
  test.skip(!liveAiEnabled, 'Opt in with FSP_SIGNAL_LIVE_AI=1 and FRONTIERAI_API_KEY for one billable synthetic request.')
  test.setTimeout(60_000)

  await signIn(page, 'employer@demo.test')
  await page.getByRole('button', { name: 'Роль и условия' }).click()
  const assistant = page.getByTestId('assistant-employer-role')
  await assistant.getByLabel('Опишите роль своими словами').fill(
    'Ищем QA junior для проверки платежного API. Формат удалённый, зарплата от 140000 до 180000 рублей в месяц. В первые 30 дней нужно составить карту рисков платежных сценариев.',
  )
  await assistant.getByLabel(/Понимаю: этот текст будет отправлен/).check()

  const responsePromise = page.waitForResponse(response =>
    response.url().endsWith('/api/v1/assistant/employer/role')
    && response.request().method() === 'POST')
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)

  const draft = await response.json() as {
    specialization: string | null
    grade: string | null
    salary_min_rub: number | null
    salary_max_rub: number | null
    work_format: string | null
  }
  expect(draft.specialization).toBe('qa')
  expect(draft.grade).toBe('junior')
  expect(draft.salary_min_rub).toBe(140000)
  expect(draft.salary_max_rub).toBe(180000)
  expect(draft.work_format).toBe('remote')
  await expect(assistant.getByRole('heading', { name: 'Черновик вакансии' })).toBeVisible()
})
