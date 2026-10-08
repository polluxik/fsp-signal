import { expect, test } from '@playwright/test'
import { signIn } from './test-support'

test('employer activates a free demo campaign and the candidate sees one labeled shelf item on mobile', async ({ browser }, testInfo) => {
  const employer = await browser.newPage()
  await signIn(employer, 'employer@demo.test')
  await employer.getByRole('button', { name: 'Роль и условия' }).click()
  await expect(employer.getByRole('heading', { name: 'Опишите реальную работу' })).toBeVisible()
  const activate = employer.getByRole('button', { name: 'Включить продвижение' })
  await expect(activate).toBeVisible()
  await expect(employer.getByText('Без оплаты')).toBeVisible()
  let failFirstActivation = true
  await employer.route('**/api/v1/employer/needs/*/promotion/demo', async route => {
    if (route.request().method() === 'POST' && failFirstActivation) {
      failFirstActivation = false
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'PROMOTION_ROLE_NOT_ELIGIBLE' }) })
    } else await route.continue()
  })
  await activate.click()
  await expect(employer.getByRole('alert')).toContainText('Роль должна быть активной')
  await expect(activate).toBeEnabled()
  await activate.click()
  await expect(employer.getByRole('status').filter({ hasText: 'Продвижение активно до' })).toBeVisible()
  await employer.screenshot({ path: testInfo.outputPath('employer-demo-promotion.png'), fullPage: true })

  const promotion = await employer.evaluate(async () => {
    const needs = await fetch('/api/v1/employer/needs').then(response => response.json()) as { id: string }[]
    const response = await fetch(`/api/v1/employer/needs/${needs[0].id}/promotion/demo`)
    return { needId: needs[0].id, campaign: await response.json() }
  })
  expect(promotion.campaign.demo_only).toBe(true)
  expect(promotion.campaign.revenue_rub).toBe(0)
  expect(promotion.campaign.role_version_id).toBeTruthy()

  const candidate = await browser.newPage({ viewport: { width: 390, height: 844 } })
  const impressionResponse = candidate.waitForResponse(response =>
    response.url().includes(`/api/v1/candidate/promotions/${promotion.campaign.id}/impression`)
    && response.request().method() === 'POST')
  await signIn(candidate, 'backend-middle-1@demo.test')
  const shelf = candidate.getByTestId('sponsored-role-shelf')
  await expect(shelf.getByRole('heading', { name: 'Продвигаемые роли' })).toBeVisible()
  const promoted = shelf.locator(`[data-need-id="${promotion.needId}"]`)
  await expect(promoted).toHaveCount(1)
  await expect(promoted.getByText('Продвигаемая роль')).toBeVisible()
  await expect(promoted.getByText('Обязательные условия соблюдены')).toBeVisible()
  await expect(candidate.locator(`[data-testid="discovery-role"][data-need-id="${promotion.needId}"]`)).toHaveCount(1)
  await shelf.scrollIntoViewIfNeeded()
  expect((await impressionResponse).status()).toBe(200)
  await candidate.screenshot({ path: testInfo.outputPath('candidate-sponsored-mobile.png'), fullPage: true })
  await promoted.getByRole('button', { name: 'Сохранить' }).click()
  await expect(candidate.getByRole('status')).toContainText('Роль сохранена в вашем списке')
  await promoted.getByRole('button', { name: 'Сохранено' }).click()
  await expect(candidate.getByRole('status')).toContainText('Роль убрана из сохранённых')
  await promoted.getByRole('button', { name: 'Скрыть' }).click()
  await expect(promoted).toHaveCount(0)
  await candidate.getByRole('button', { name: 'Вернуть роль' }).click()
  await expect(shelf.locator(`[data-need-id="${promotion.needId}"]`)).toHaveCount(1)
  await employer.close()
  await candidate.close()
})
