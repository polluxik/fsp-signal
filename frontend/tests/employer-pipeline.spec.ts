import { expect, test, type Page } from '@playwright/test'
import { currentUserId, signIn } from './test-support'

async function request(page: Page, path: string, method = 'GET', body?: unknown) {
  return page.evaluate(async ({ path, method, body }) => {
    const token = decodeURIComponent(document.cookie.split('; ').find(part => part.startsWith('fsp_csrf='))!.split('=')[1])
    const response = await fetch(`/api/v1${path}`, { method, headers: {
      'content-type': 'application/json', 'x-csrf-token': token,
    }, body: body === undefined ? undefined : JSON.stringify(body) })
    const data = await response.json()
    if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(data)}`)
    return data
  }, { path, method, body })
}

async function createRole(page: Page, title: string) {
  const payload = { title, description: 'Надёжно обрабатывать повторные события в сервисе',
    specialization: 'backend', grade: 'middle', competencies: ['event_idempotency'],
    stack: ['Python', 'PostgreSQL'], salary_min_rub: 180000, salary_max_rub: 230000,
    work_format: 'remote', work_city: null, first_30_days: 'Устранить повторную обработку платёжных событий',
    interview_steps: [{ title: 'Знакомство с командой', duration_minutes: 30 }],
    take_home_minutes: 0, response_sla_hours: 48, employer_contact: 'other@demo.test', active_headcount_attested: true }
  const need = await request(page, '/employer/needs', 'POST', payload)
  await request(page, `/employer/needs/${need.id}/versions`, 'POST', { expected_version: 1, card: payload })
  await request(page, `/employer/needs/${need.id}/publish`, 'POST', { expected_version: 2, active_headcount_attested: true, discoverable: false })
  const funnel = await request(page, `/employer/needs/${need.id}/funnel`)
  return { needId: need.id as string, versionId: funnel.role_version_id as string, payload }
}

async function openSearch(page: Page, needId: string) {
  await page.reload()
  await page.getByRole('button', { name: 'Найти специалиста', exact: true }).click()
  await page.getByRole('combobox', { name: 'Потребность', exact: true }).selectOption(needId)
  await page.getByRole('button', { name: 'Показать подборку', exact: true }).click()
  await expect(page.locator('.candidate-card').first()).toBeVisible()
}

test('private shortlist persists, respects withdrawal and renders role activity on mobile', async ({ browser }, testInfo) => {
  const employer = await browser.newPage()
  const candidate = await browser.newPage()
  await signIn(employer, 'other@demo.test')
  await signIn(candidate, 'backend-middle-12@demo.test')
  const candidateId = await currentUserId(candidate)
  const role = await createRole(employer, 'Shortlist: сохранение и приватность')
  await openSearch(employer, role.needId)
  const alias = `Кандидат #${candidateId.slice(0, 8)}`
  const card = employer.locator('.candidate-card').filter({ hasText: alias })
  await card.getByRole('button', { name: 'Сохранить кандидата', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Убрать из избранного' })).toHaveAttribute('aria-pressed', 'true')
  const funnel = employer.getByTestId('role-funnel')
  await expect(funnel.getByTestId('funnel-matched')).not.toHaveText('0')
  await expect(funnel.getByTestId('funnel-held')).toHaveText('0')
  await expect(funnel).not.toContainText(/демо|синтетическ|учебные данные/i)
  await expect(funnel).toContainText('уникальных кандидатов')
  await employer.setViewportSize({ width: 390, height: 844 })
  expect(await employer.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
  await funnel.screenshot({ path: testInfo.outputPath('funnel-mobile.png') })
  await employer.getByRole('button', { name: 'Избранные кандидаты', exact: true }).click()
  await expect(employer.getByTestId('shortlist-cards').locator('.candidate-card')).toHaveCount(1)
  await employer.reload()
  await employer.getByRole('button', { name: 'Избранные кандидаты', exact: true }).click()
  await employer.getByLabel('Роль для избранного').selectOption(role.needId)
  await expect(employer.getByTestId('shortlist-cards')).toContainText(alias)
  await expect(employer.getByTestId('shortlist-cards')).not.toContainText('backend-middle-12@demo.test')
  await employer.screenshot({ path: testInfo.outputPath('shortlist-mobile.png'), fullPage: true })
  console.log(`Pipeline screenshots: ${testInfo.outputPath('funnel-mobile.png')}, ${testInfo.outputPath('shortlist-mobile.png')}`)

  const profile = await request(candidate, '/candidate/profile')
  try {
    await request(candidate, '/candidate/profile', 'PUT', { ...profile, published: false,
      expected_preferences_version: profile.preferences_version })
    await employer.getByRole('button', { name: 'Обновить избранное' }).click()
    await expect(employer.getByTestId('shortlist-cards')).toHaveCount(0)
    await expect(employer.getByText('Недоступных сохранённых профилей: 1. Их данные скрыты.')).toBeVisible()
    const hidden = await request(employer, `/employer/needs/${role.needId}/shortlist`)
    expect(JSON.stringify(hidden)).not.toContain(candidateId)
  } finally {
    const latest = await request(candidate, '/candidate/profile')
    await request(candidate, '/candidate/profile', 'PUT', { ...profile,
      expected_preferences_version: latest.preferences_version })
  }
  await employer.getByRole('button', { name: 'Обновить избранное' }).click()
  await expect(employer.getByTestId('shortlist-cards')).toContainText(alias)
  await employer.getByTestId('shortlist-cards').getByRole('button', { name: 'Убрать из избранного' }).click()
  await expect(employer.getByTestId('shortlist-cards')).toHaveCount(0)
  await employer.close(); await candidate.close()
})

test('stale employer tab reloads CAS state and previous role version cannot send a new invitation', async ({ browser }) => {
  const first = await browser.newPage()
  const second = await browser.newPage()
  await signIn(first, 'other@demo.test')
  const role = await createRole(first, 'Shortlist: версии и параллельные вкладки')
  await signIn(second, 'other@demo.test')
  await openSearch(first, role.needId)
  await openSearch(second, role.needId)
  const alias = await first.locator('.candidate-card').first().getByRole('heading').innerText()
  const firstCard = first.locator('.candidate-card').filter({ hasText: alias })
  const secondCard = second.locator('.candidate-card').filter({ hasText: alias })
  await firstCard.getByRole('button', { name: 'Сохранить кандидата' }).click()
  await expect(firstCard.getByRole('button', { name: 'Убрать из избранного' })).toBeVisible()
  await secondCard.getByRole('button', { name: 'Сохранить кандидата' }).click()
  await expect(second.getByRole('alert')).toContainText('Избранное изменилось')
  await expect(secondCard.getByRole('button', { name: 'Убрать из избранного' })).toHaveAttribute('aria-pressed', 'true')
  const saved = await request(first, `/employer/needs/${role.needId}/shortlist`)
  expect(saved.entries.filter((entry: { saved: boolean }) => entry.saved)).toHaveLength(1)

  await request(first, `/employer/needs/${role.needId}/versions`, 'POST', {
    expected_version: 2, card: { ...role.payload, first_30_days: 'Новая задача: обеспечить идемпотентный импорт событий' },
  })
  await request(first, `/employer/needs/${role.needId}/publish`, 'POST', { expected_version: 3, active_headcount_attested: true, discoverable: false })
  await first.reload()
  await first.getByRole('button', { name: 'Найти специалиста', exact: true }).click()
  await first.getByRole('combobox', { name: 'Потребность', exact: true }).selectOption(role.needId)
  const funnel = first.getByTestId('role-funnel')
  await expect(funnel.getByTestId('funnel-matched')).toHaveText('0')
  await funnel.getByLabel('Версия роли в воронке').selectOption(role.versionId)
  await expect(funnel.getByTestId('funnel-matched')).not.toHaveText('0')
  await first.getByRole('button', { name: 'Избранные кандидаты', exact: true }).click()
  await expect(first.getByTestId('shortlist-cards')).toHaveCount(0)
  await first.getByLabel('Версия роли в избранном').selectOption(role.versionId)
  await expect(first.getByText('Это список для прежних условий.', { exact: false })).toBeVisible()
  const historical = first.getByTestId('shortlist-cards')
  await expect(historical).toContainText(alias)
  await expect(historical.getByRole('button', { name: 'Пригласить с условиями →', exact: true })).toBeDisabled()
  await historical.getByRole('button', { name: 'Убрать из избранного' }).click()
  await expect(first.getByTestId('shortlist-cards')).toHaveCount(0)
  await first.close(); await second.close()
})
