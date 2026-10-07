import { expect, test } from '@playwright/test'
import { signIn } from './test-support'

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }))
  expect(dimensions.content, `page overflows horizontally: ${JSON.stringify(dimensions)}`)
    .toBeLessThanOrEqual(dimensions.viewport + 1)
}

test('candidate and employer sections fit a narrow mobile viewport', async ({ browser }) => {
  const candidate = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  await signIn(candidate, 'backend-middle-1@demo.test')
  for (const section of ['Для меня', 'Условия поиска', 'Доказательства', 'Мой профиль', 'Проверка навыков', 'Приглашения', 'ФСП ID и доступ']) {
    await candidate.getByRole('button', { name: section }).click()
    await expect(candidate.locator('.sidebar button.active')).toHaveText(section)
    await expectNoHorizontalOverflow(candidate)
  }
  await candidate.close()

  const employer = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  await signIn(employer, 'employer@demo.test')
  for (const section of ['Найти специалиста', 'Роль и условия', 'Банк кандидатов', 'Приглашения', 'Компания']) {
    await employer.getByRole('button', { name: section }).click()
    await expect(employer.locator('.sidebar button.active')).toHaveText(section)
    await expectNoHorizontalOverflow(employer)
  }
  await employer.close()
})

test('assistant consent and send actions are keyboard operable with visible focus', async ({ page }) => {
  let assistantCalls = 0
  await page.route('**/api/v1/assistant/candidate/preferences', async route => {
    assistantCalls += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      salary_min_rub: null, allowed_work_formats: [], allowed_cities: [], excluded_industries: [],
      preferred_stack: [], preferred_tasks: [], max_take_home_minutes: null,
      missing_fields: [], follow_up_questions: [],
    }) })
  })
  await signIn(page, 'backend-middle-1@demo.test')
  const preferencesTab = page.getByRole('button', { name: 'Условия поиска' })
  await preferencesTab.focus()
  await page.keyboard.press('Enter')
  const assistant = page.getByTestId('assistant-candidate-preferences')
  const text = assistant.getByLabel('Что важно в работе?')
  await text.focus()
  await page.keyboard.type('Удалённо, продуктовые задачи.')
  await page.keyboard.press('Tab')
  const consent = assistant.getByLabel(/Понимаю: этот текст будет отправлен/)
  await expect(consent).toBeFocused()
  await page.keyboard.press('Space')
  await expect(consent).toBeChecked()
  await page.keyboard.press('Tab')
  const send = assistant.getByRole('button', { name: 'Составить черновик' })
  await expect(send).toBeFocused()
  const focusStyle = await send.evaluate(element => getComputedStyle(element).outlineStyle)
  expect(focusStyle).not.toBe('none')
  await page.keyboard.press('Enter')
  await expect(assistant.getByRole('heading', { name: 'Черновик предпочтений' })).toBeVisible()
  expect(assistantCalls).toBe(1)
})

test('reduced-motion preference disables nonessential button movement', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await signIn(page, 'backend-middle-1@demo.test')
  const button = page.getByRole('button', { name: 'Условия поиска' })
  await expect(button).toHaveCSS('transition-duration', '0s')
})

test('failed preference save keeps entered values and offers a working retry', async ({ page }) => {
  let failFirstSave = true
  await page.route('**/api/v1/candidate/preferences', async route => {
    if (route.request().method() === 'PUT' && failFirstSave) {
      failFirstSave = false
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'SERVICE_UNAVAILABLE' }) })
    } else await route.continue()
  })
  await signIn(page, 'backend-middle-1@demo.test')
  await page.getByRole('button', { name: 'Условия поиска' }).click()
  const salary = page.getByLabel(/Минимум, ₽ в месяц/)
  await salary.fill('195000')
  await page.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(page.getByRole('alert')).toContainText('Сервис временно недоступен')
  await expect(page.getByRole('alert')).not.toContainText('SERVICE_UNAVAILABLE')
  await expect(salary).toHaveValue('195000')
  await page.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(page.getByRole('status')).toContainText('Условия обновлены')
  await expect(salary).toHaveValue('195000')
})

test('desktop candidate and employer draft screens render without browser errors', async ({ browser }, testInfo) => {
  const pageErrors: string[] = []
  const candidate = await browser.newPage({ viewport: { width: 1365, height: 920 } })
  candidate.on('pageerror', error => pageErrors.push(error.message))
  await signIn(candidate, 'backend-middle-1@demo.test')
  await candidate.getByRole('button', { name: 'Условия поиска' }).click()
  await expect(candidate.getByTestId('assistant-candidate-preferences')).toBeVisible()
  await candidate.screenshot({ path: testInfo.outputPath('candidate-preferences-desktop.png'), fullPage: true })
  await candidate.getByRole('button', { name: 'Мой профиль' }).click()
  await expect(candidate.getByTestId('assistant-candidate-achievement')).toBeVisible()
  await candidate.screenshot({ path: testInfo.outputPath('candidate-profile-desktop.png'), fullPage: true })
  await candidate.close()

  const employer = await browser.newPage({ viewport: { width: 1365, height: 920 } })
  employer.on('pageerror', error => pageErrors.push(error.message))
  await signIn(employer, 'employer@demo.test')
  await employer.getByRole('button', { name: 'Роль и условия' }).click()
  await expect(employer.getByTestId('assistant-employer-role')).toBeVisible()
  await employer.screenshot({ path: testInfo.outputPath('employer-role-desktop.png'), fullPage: true })
  await employer.close()

  const mobileCandidate = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  mobileCandidate.on('pageerror', error => pageErrors.push(error.message))
  await signIn(mobileCandidate, 'backend-middle-1@demo.test')
  await mobileCandidate.getByRole('button', { name: 'Условия поиска' }).click()
  await expect(mobileCandidate.getByTestId('assistant-candidate-preferences')).toBeVisible()
  await mobileCandidate.screenshot({ path: testInfo.outputPath('candidate-preferences-mobile.png'), fullPage: true })
  await mobileCandidate.close()

  const mobileEmployer = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  mobileEmployer.on('pageerror', error => pageErrors.push(error.message))
  await signIn(mobileEmployer, 'employer@demo.test')
  await mobileEmployer.getByRole('button', { name: 'Роль и условия' }).click()
  await expect(mobileEmployer.getByTestId('assistant-employer-role')).toBeVisible()
  const actionWidths = await mobileEmployer.locator('.role-editor-actions').evaluate(container => {
    const width = container.getBoundingClientRect().width
    const controls = [...container.querySelectorAll('button')]
      .filter(button => getComputedStyle(button).display !== 'none')
      .map(button => button.getBoundingClientRect().width)
    return { width, controls }
  })
  expect(actionWidths.controls.every(width => width >= actionWidths.width * 0.8), JSON.stringify(actionWidths)).toBeTruthy()
  await mobileEmployer.screenshot({ path: testInfo.outputPath('employer-role-mobile.png'), fullPage: true })
  await mobileEmployer.close()
  expect(pageErrors).toEqual([])
})
