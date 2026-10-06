import { expect, test } from '@playwright/test'

async function signIn(page: import('@playwright/test').Page, email: string) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Вход' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Пароль').fill('DemoPass123!')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('button', { name: 'Выйти' })).toBeVisible()
}

async function currentUserId(page: import('@playwright/test').Page): Promise<string> {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/me')
    const user = await response.json()
    return user.id as string
  })
}

test('candidate preferences persist without publishing and stay private from employers', async ({ browser }) => {
  const candidate = await browser.newPage()
  await signIn(candidate, 'backend-middle-1@demo.test')
  await candidate.getByRole('button', { name: 'Условия поиска' }).click()
  await candidate.getByLabel(/Минимум, ₽ в месяц/).fill('175000')
  await candidate.getByLabel(/Города для гибрида и офиса/).fill('Москва')
  await expect(candidate.getByLabel(/мне исполнилось 18 лет/)).toBeChecked()
  await candidate.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(candidate.locator('.notice')).toContainText('Условия обновлены')

  await candidate.reload()
  await candidate.getByRole('button', { name: 'Условия поиска' }).click()
  await expect(candidate.getByLabel(/Минимум, ₽ в месяц/)).toHaveValue('175000')
  await candidate.getByRole('button', { name: 'Мой профиль' }).click()
  await expect(candidate.getByLabel(/Публиковать проверенный профиль работодателям/)).toBeChecked()
  await candidate.getByLabel('Контекст: какую задачу или проблему решали').fill('Повторная доставка события могла создать двойную запись в расчётах.')
  await candidate.getByLabel('Ваш личный вклад: что сделали вы').fill('Добавил идемпотентную обработку по идентификатору события.')
  await candidate.getByLabel(/Почему выбрали такой подход/).fill('Уникальное ограничение защищает и при параллельной обработке.')
  await candidate.getByLabel(/Что изменилось/).fill('Команда перестала вручную разбирать повторные записи.')
  await candidate.getByLabel(/Основание или артефакт/).fill('Ссылка на PR не приложена.')
  await expect(candidate.getByLabel(/Отдельно разрешаю показать этот рассказ/)).not.toBeChecked()
  await candidate.getByRole('button', { name: 'Сохранить профиль' }).click()
  await expect(candidate.getByRole('status')).toContainText('Профиль сохранён')
  await candidate.reload()
  await expect(candidate.getByLabel('Контекст: какую задачу или проблему решали'))
    .toHaveValue('Повторная доставка события могла создать двойную запись в расчётах.')
  await expect(candidate.getByLabel(/Отдельно разрешаю показать этот рассказ/)).not.toBeChecked()
  await expect(candidate.getByLabel(/Публиковать проверенный профиль работодателям/)).toBeChecked()

  const employer = await browser.newPage()
  await signIn(employer, 'employer@demo.test')
  const forbidden = await employer.evaluate(async () => (await fetch('/api/v1/candidate/preferences')).status)
  expect(forbidden).toBe(403)
  await candidate.close()
  await employer.close()
})

test('role facts, selected evidence, explicit acceptance, and pair-scoped contact access work end to end', async ({ browser }) => {
  const candidatePage = await browser.newPage()
  await signIn(candidatePage, 'backend-middle-1@demo.test')
  const candidateId = await currentUserId(candidatePage)

  const employerPage = await browser.newPage()
  await signIn(employerPage, 'employer@demo.test')
  await employerPage.getByRole('button', { name: 'Роль и условия' }).click()
  await expect(employerPage.getByRole('heading', { name: 'Опишите реальную работу' })).toBeVisible()
  const rolePreview = employerPage.locator('.role-preview')
  await expect(rolePreview).toContainText('180 000 ₽ — 230 000 ₽')
  await expect(rolePreview).toContainText('Первые 30 дней')
  await expect(rolePreview).toContainText('Этапы')

  await employerPage.getByLabel(/Результат первых 30 дней/).fill('Снизить риск повторной записи по платёжным событиям и согласовать мониторинг.')
  await employerPage.getByRole('button', { name: 'Сохранить черновик' }).click()
  await expect(employerPage.locator('.notice')).toContainText('Условия сохранены как версия')
  await employerPage.getByRole('button', { name: 'Сохранить и опубликовать' }).click()
  await expect(employerPage.getByRole('status')).toContainText('подтверждена на ближайшие 14 дней')

  await employerPage.getByRole('button', { name: 'Найти специалиста' }).click()
  const searchResponsePromise = employerPage.waitForResponse(response =>
    response.url().endsWith('/api/v1/employer/searches') && response.request().method() === 'POST')
  await employerPage.getByRole('button', { name: 'Показать подборку' }).click()
  const searchResponse = await searchResponsePromise
  expect(searchResponse.ok()).toBeTruthy()
  const snapshot = await searchResponse.json()
  const target = snapshot.results.find((item: { id: string }) => item.id === candidateId)
  expect(target, `candidate ${candidateId} not found in ${JSON.stringify(snapshot.results.map((item: { id: string }) => item.id))}`).toBeTruthy()
  const targetAlias = target.alias as string
  await employerPage.locator('.candidate-card').filter({ hasText: targetAlias })
    .getByRole('button', { name: /Пригласить с условиями/ }).click()
  await expect(employerPage.getByRole('dialog')).toBeVisible()
  const selectedEvidence = employerPage.getByRole('checkbox', { name: 'Добавить: Ранее сохранённая категория' })
  await expect(selectedEvidence).toBeChecked()
  await expect(employerPage.getByRole('checkbox', { name: 'Добавить: Навык из профиля' }).first()).not.toBeChecked()
  await employerPage.getByRole('button', { name: /Отправить с выбранным основанием/ }).click()
  await expect(employerPage.getByRole('status')).toContainText('Приглашение отправлено')

  await candidatePage.getByRole('button', { name: 'Приглашения' }).click()
  await candidatePage.getByRole('button', { name: 'Проверить условия' }).click()
  const acceptButton = candidatePage.getByRole('button', { name: 'Принять условия' })
  await expect(acceptButton).toBeDisabled()
  await candidatePage.getByRole('checkbox', { name: /проверил.*принимаю именно эту версию/ }).check()
  await expect(acceptButton).toBeEnabled()
  await acceptButton.click()
  await expect(candidatePage.getByRole('status')).toContainText('Контакты доступны только этой компании')

  await employerPage.getByRole('button', { name: 'Приглашения' }).click()
  await employerPage.getByRole('button', { name: new RegExp(`Показать контакты кандидата #${candidateId.slice(0, 8)}`) }).click()
  await expect(employerPage.getByRole('status')).toContainText('backend-middle-1@demo.test')

  const secondCandidatePage = await browser.newPage()
  await signIn(secondCandidatePage, 'backend-middle-2@demo.test')
  const secondCandidateId = await currentUserId(secondCandidatePage)
  await employerPage.getByRole('button', { name: 'Найти специалиста' }).click()
  const secondSearchPromise = employerPage.waitForResponse(response =>
    response.url().endsWith('/api/v1/employer/searches') && response.request().method() === 'POST')
  await employerPage.getByRole('button', { name: 'Показать подборку' }).click()
  const secondSearch = await secondSearchPromise
  const secondSnapshot = await secondSearch.json()
  const secondTarget = secondSnapshot.results.find((item: { id: string }) => item.id === secondCandidateId)
  expect(secondTarget, `candidate ${secondCandidateId} missing from second search`).toBeTruthy()
  await employerPage.locator('.candidate-card').filter({ hasText: secondTarget.alias })
    .getByRole('button', { name: /Пригласить с условиями/ }).click()
  await expect(employerPage.getByRole('dialog')).toBeVisible()
  await expect(employerPage.getByRole('checkbox', { name: 'Добавить: Ранее сохранённая категория' })).toBeChecked()
  await employerPage.getByRole('button', { name: /Отправить с выбранным основанием/ }).click()
  await expect(employerPage.getByRole('status')).toContainText('Приглашение отправлено')

  await secondCandidatePage.getByRole('button', { name: 'Приглашения' }).click()
  await secondCandidatePage.getByRole('button', { name: 'Проверить условия' }).click()
  await secondCandidatePage.getByRole('checkbox', { name: /проверил.*принимаю именно эту версию/ }).check()
  await secondCandidatePage.getByRole('button', { name: 'Принять условия' }).click()
  await expect(secondCandidatePage.getByRole('status')).toContainText('Контакты доступны только этой компании')

  await employerPage.getByRole('button', { name: 'Приглашения' }).click()
  await employerPage.getByRole('button', { name: new RegExp(`Показать контакты кандидата #${secondCandidateId.slice(0, 8)}`) }).click()
  const secondContactCard = employerPage.locator('.offer-card').filter({ hasText: secondCandidateId.slice(0, 8) })
  await expect(secondContactCard.getByRole('status')).toContainText('backend-middle-2@demo.test')
  const firstContactCard = employerPage.locator('.offer-card').filter({ hasText: candidateId.slice(0, 8) })
  await firstContactCard.getByRole('button', { name: /Показать контакты кандидата/ }).click()
  await expect(firstContactCard.getByRole('status')).toContainText('backend-middle-1@demo.test')
  await expect(secondContactCard.getByRole('status')).toContainText('backend-middle-2@demo.test')

  const otherEmployer = await browser.newPage()
  await signIn(otherEmployer, 'other@demo.test')
  const contactStatus = await otherEmployer.evaluate(async id =>
    (await fetch(`/api/v1/employer/candidates/${id}/contact`)).status, candidateId)
  expect(contactStatus).toBe(403)

  await candidatePage.close()
  await secondCandidatePage.close()
  await employerPage.close()
  await otherEmployer.close()
})
