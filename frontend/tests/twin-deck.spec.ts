import { expect, test } from '@playwright/test'
import { signIn } from './test-support'
import type { CandidateRoleFeedItem, CandidatePreferences } from '../src/types'

const preferences: CandidatePreferences = { version: 1, salary_min_rub: null, allowed_work_formats: ['remote'], allowed_cities: [], excluded_industries: [], preferred_stack: [], preferred_tasks: [], max_take_home_minutes: null, available: true, adult_hiring_confirmed: true }
const fixture = (id: string): CandidateRoleFeedItem => ({
  need_id: id, role_version_id: `version-${id}`, role_version: 1, preferences_version: 1,
  company_name: 'Команда Сигнал', data_mode: 'unknown', match_state: 'compatible', compatibility: null, decision: 'none', confirmed_at: '2026-10-09T10:00:00Z',
  role: { title: `Backend-разработчик ${id}`, specialization: 'backend', grade: 'middle', description: 'Развивать надёжные сервисы и API.', stack: ['Python', 'PostgreSQL'], competencies: [], salary_min_rub: 180000, salary_max_rub: 250000, work_format: 'remote', work_city: null, industry: null, first_30_days: 'Разобраться в сервисах и запустить первый API.', interview_steps: [], take_home_minutes: 0, response_sla_hours: 48 },
  discovery_match: { percent: 78, components: [{ label: 'Описание и задачи', percent: 78, weight_percent: 100 }], peer_signal: null, algorithm_version: 'discovery_match_v1' },
})

test('deck does not skip a role after save, hide and undo; failed save keeps the current card', async ({ page }) => {
  let hidden = new Set<string>()
  let failNext = true
  const decisions: string[] = []
  await page.route('**/api/v1/candidate/roles?*', route => route.fulfill({ json: { items: ['a', 'b', 'c'].filter(id => !hidden.has(id)).map(fixture), sponsored_items: [], next_cursor: null, empty_state: null } }))
  await page.route('**/api/v1/candidate/role-decisions/*', async route => {
    const id = route.request().url().split('/').at(-1)!
    const { action } = route.request().postDataJSON()
    decisions.push(`${id}:${action}`)
    if (failNext) { failNext = false; await route.fulfill({ status: 503, json: { detail: 'SERVICE_UNAVAILABLE' } }); return }
    if (action === 'hidden') hidden.add(id)
    else hidden.delete(id)
    await route.fulfill({ json: {} })
  })
  await signIn(page, 'backend-middle-2@demo.test')
  await page.getByRole('button', { name: 'Карточки', exact: true }).click()
  const card = page.getByTestId('twin-card')
  await expect(card).toHaveAttribute('data-need-id', 'a')
  await card.getByRole('button', { name: 'Интересно — сохранить ♥' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(card).toHaveAttribute('data-need-id', 'a')
  await card.focus()
  await page.keyboard.press('ArrowRight')
  await expect(card).toHaveAttribute('data-need-id', 'b')
  await card.getByRole('button', { name: '← Пропустить роль' }).click()
  await expect(card).toHaveAttribute('data-need-id', 'c')
  await page.getByRole('button', { name: 'Вернуть роль' }).click()
  await expect(card).toHaveAttribute('data-need-id', 'b')
  expect(decisions).toEqual(['a:saved', 'a:saved', 'b:hidden', 'b:none'])
  for (const width of [1365, 820, 390]) {
    await page.setViewportSize({ width, height: 920 })
    const bounds = await card.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: test.info().outputPath(`twin-${width}.png`), fullPage: true })
  }
})

test('swipes preserve vertical scrolling and nested controls, and pending decisions cannot be repeated', async ({ page }) => {
  const decisions: string[] = []
  await page.route('**/api/v1/candidate/roles?*', route => route.fulfill({ json: { items: ['a', 'b', 'c'].map(fixture), sponsored_items: [], next_cursor: null, empty_state: null } }))
  let finish: (() => void) | undefined
  await page.route('**/api/v1/candidate/role-decisions/*', async route => {
    const action = route.request().postDataJSON().action
    decisions.push(action)
    if (action === 'saved') await new Promise<void>(resolve => { finish = resolve })
    await route.fulfill({ json: {} })
  })
  await signIn(page, 'backend-middle-2@demo.test')
  await page.getByRole('button', { name: 'Карточки', exact: true }).click()
  const card = page.getByTestId('twin-card')
  await card.scrollIntoViewIfNeeded()
  const title = await card.getByRole('heading').boundingBox()
  expect(title).not.toBeNull()
  const x = title!.x + title!.width / 2, y = title!.y + 10
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 5, y + 120, { steps: 5 })
  await page.mouse.up()
  await expect(card).toHaveAttribute('data-need-id', 'a')
  expect(decisions).toEqual([])
  await card.locator('.twin-details > summary').click()
  await card.locator('.twin-details > summary').press('ArrowRight')
  expect(decisions).toEqual([])
  await card.locator('.twin-details > summary').click()
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 160, y, { steps: 8 })
  await expect(card.locator('.twin-stamp')).toContainText('ИНТЕРЕСНО')
  await page.mouse.up()
  await expect.poll(() => decisions.length).toBe(1)
  await expect(card).toHaveAttribute('aria-busy', 'true')
  await card.focus()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowLeft')
  expect(decisions).toEqual(['saved'])
  finish!()
  await expect(card).toHaveAttribute('data-need-id', 'b')
  await card.scrollIntoViewIfNeeded()
  const next = await card.getByRole('heading').boundingBox()
  await page.mouse.move(next!.x + next!.width / 2, next!.y + 10)
  await page.mouse.down()
  await page.mouse.move(next!.x + next!.width / 2 - 160, next!.y + 10, { steps: 8 })
  await page.mouse.up()
  await expect(card).toHaveAttribute('data-need-id', 'c')
  expect(decisions).toEqual(['saved', 'hidden'])
})

test('assistant in the feed requires consent and saves reviewed preferences separately', async ({ page }) => {
  let writes = 0, aiCalls = 0, feedRequests = 0
  await page.route('**/api/v1/candidate/roles?*', route => { feedRequests++; return route.fulfill({ json: { items: [fixture('a')], sponsored_items: [], next_cursor: null, empty_state: null } }) })
  await page.route('**/api/v1/candidate/preferences', async route => {
    if (route.request().method() === 'PUT') {
      writes++
      expect(route.request().postDataJSON()).toMatchObject({ expected_version: 1, salary_min_rub: 210000, allowed_work_formats: ['remote'], preferred_stack: ['Python'], adult_hiring_confirmed: true })
      await route.fulfill({ json: { ...preferences, ...route.request().postDataJSON(), version: 2 } })
    } else await route.fulfill({ json: preferences })
  })
  await page.route('**/api/v1/assistant/candidate/preferences', async route => {
    aiCalls++
    expect(route.request().postDataJSON()).toMatchObject({ external_ai_consent: true })
    await route.fulfill({ json: { salary_min_rub: 210000, allowed_work_formats: ['remote'], allowed_cities: [], excluded_industries: [], preferred_stack: ['Python'], preferred_tasks: ['API'], max_take_home_minutes: null, missing_fields: [], follow_up_questions: [] } })
  })
  await signIn(page, 'backend-middle-2@demo.test')
  await page.getByRole('button', { name: 'ИИ-помощник подбора' }).click()
  const panel = page.getByTestId('feed-ai-preferences')
  const assistant = panel.getByTestId('assistant-candidate-preferences')
  await assistant.getByLabel('Что важно в работе?').fill('Удалённо, Python и API, от 210000 рублей.')
  await expect(assistant.getByRole('button', { name: 'Составить черновик' })).toBeDisabled()
  expect(aiCalls).toBe(0)
  await assistant.getByRole('checkbox').check()
  await assistant.getByRole('button', { name: 'Составить черновик' }).click()
  await assistant.getByRole('button', { name: 'Применить в форму' }).click()
  expect(writes).toBe(0)
  const beforeSave = feedRequests
  await panel.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect.poll(() => writes).toBe(1)
  await expect.poll(() => feedRequests).toBeGreaterThan(beforeSave)
  await expect(page.getByRole('status').filter({ hasText: 'Подборка обновлена' })).toBeVisible()
})
