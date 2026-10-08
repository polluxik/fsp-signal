import { expect, test } from '@playwright/test'
import { signIn } from './test-support'

test('candidate journey uses saved state and optional FSP does not block onboarding', async ({ page }) => {
  await signIn(page, 'new-candidate@demo.test')
  const journey = page.getByTestId('candidate-journey')
  await expect(journey).toContainText('Профиль пока скрыт')
  await expect(journey).toContainText('ФСП ID необязателен')
  await journey.getByRole('button', { name: 'Сохранить имя и контактный email', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Пусть навыки говорят за вас' })).toBeVisible()
  await page.getByLabel('Имя и фамилия').fill('Несохранённый черновик')
  await page.getByRole('button', { name: 'Для меня', exact: true }).click()
  await expect(journey.getByRole('button', { name: 'Сохранить имя и контактный email', exact: true })).toBeVisible()
  expect(await page.evaluate(async () => (await fetch('/api/v1/candidate/profile')).json())).toBeNull()
})

test('test blueprint and failed-attempt practice report survive reload and history navigation', async ({ page }) => {
  await signIn(page, 'backend-junior-11@demo.test')
  await page.getByRole('button', { name: 'Проверка навыков', exact: true }).click()
  const plan = page.getByTestId('assessment-plan')
  await expect(plan).toContainText('Backend · Junior')
  await expect(plan).toContainText('Трассировка данных')
  await page.getByRole('button', { name: 'Начать тест', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Этап 1 из 2' })).toBeVisible()
  await page.reload()
  const journey = page.getByTestId('candidate-journey')
  await journey.getByRole('button', { name: 'Продолжить незавершённый тест' }).click()
  await expect(page.getByRole('heading', { name: 'Этап 1 из 2' })).toBeVisible()
  for (let phase = 1; phase <= 2; phase++) {
    for (const question of await page.locator('.question').all()) {
      const number = question.locator('input[type="number"]')
      if (await number.count()) await number.fill('-999')
      else await question.getByRole('radio').first().check()
    }
    await page.getByRole('button', { name: phase === 1 ? 'Зафиксировать ответы и продолжить' : 'Отправить на проверку', exact: true }).click()
    if (phase === 1) await expect(page.getByRole('heading', { name: 'Этап 2 из 2' })).toBeVisible()
  }
  const report = page.getByTestId('assessment-report')
  await expect(report).toContainText('Не пройден')
  await expect(report).toContainText('Попробуйте на практике')
  await expect(report.getByRole('progressbar')).toHaveCount(3)
  await expect(report).toContainText('Отчёт доступен только вам')
  const original = await report.innerText()
  await page.reload()
  await page.getByRole('button', { name: 'Проверка навыков', exact: true }).click()
  await page.getByRole('button', { name: /^Разбор попытки от/ }).first().click()
  await expect.poll(() => report.innerText()).toBe(original)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(report).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
  const screenshot = test.info().outputPath('assessment-report-mobile.png')
  await report.screenshot({ path: screenshot })
  console.log(`Assessment report screenshot: ${screenshot}`)
})
