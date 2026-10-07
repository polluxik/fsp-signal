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

test('candidate discovers roles, saves and hides them, then restores with undo', async ({ browser }) => {
  const newCandidate = await browser.newPage()
  await signIn(newCandidate, 'new-candidate@demo.test')
  await expect(newCandidate.getByRole('heading', { name: 'Роли с понятными условиями' })).toBeVisible()
  await expect(newCandidate.locator('.match-badge.not_assessed').first()).toBeVisible()
  const untouchedProfile = await newCandidate.evaluate(async () =>
    (await fetch('/api/v1/candidate/profile')).json())
  expect(untouchedProfile).toBeNull()
  await newCandidate.close()

  const candidate = await browser.newPage()
  await signIn(candidate, 'backend-middle-1@demo.test')
  await expect(candidate.getByRole('heading', { name: 'Роли с понятными условиями' })).toBeVisible()

  await candidate.getByRole('button', { name: 'Условия поиска' }).click()
  await candidate.getByLabel(/Минимум, ₽ в месяц/).fill('')
  await candidate.getByRole('checkbox', { name: 'Гибрид' }).check()
  await candidate.getByRole('checkbox', { name: 'Офис' }).check()
  await candidate.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(candidate.getByRole('status')).toContainText('Условия обновлены')

  const feedResponsePromise = candidate.waitForResponse(response =>
    response.url().includes('/api/v1/candidate/roles') && response.request().method() === 'GET')
  await candidate.getByRole('button', { name: 'Для меня' }).click()
  const feedResponse = await feedResponsePromise
  expect(feedResponse.ok()).toBeTruthy()
  const initialFeed = await feedResponse.json()
  expect(initialFeed.items).toHaveLength(5)
  expect(JSON.stringify(initialFeed)).not.toContain('employer_contact')
  expect(JSON.stringify(initialFeed)).not.toContain('@demo.test')
  await expect(candidate.locator('[data-testid="discovery-role"]')).toHaveCount(5)
  await expect(candidate.getByText('Нужно уточнить условия').first()).toBeVisible()
  await candidate.getByRole('button', { name: 'Показать ещё 5' }).click()
  await expect(candidate.locator('[data-testid="discovery-role"]')).toHaveCount(6)

  const savedRole = candidate.locator('[data-testid="discovery-role"]')
    .filter({ hasText: 'Frontend Middle: надёжные сценарии' })
  const bumpedPreferences = await candidate.evaluate(async () => {
    const current = await fetch('/api/v1/candidate/preferences').then(response => response.json())
    const token = decodeURIComponent(document.cookie.split('; ').find(item => item.startsWith('fsp_csrf='))?.split('=')[1] ?? '')
    const { version, ...payload } = current
    const response = await fetch('/api/v1/candidate/preferences', {
      method: 'PUT',
      headers: { 'content-type': 'application/json', 'x-csrf-token': token },
      body: JSON.stringify({ ...payload, expected_version: version }),
    })
    return { status: response.status, version: (await response.json()).version }
  })
  expect(bumpedPreferences.status).toBe(200)
  await savedRole.getByRole('button', { name: 'Сохранить' }).click()
  await expect(candidate.locator('.feed-error')).toContainText('ваши условия обновились')
  await expect(savedRole.getByRole('button', { name: 'Сохранить' })).toBeVisible()
  await savedRole.getByRole('button', { name: 'Сохранить' }).click()
  await expect(savedRole.getByRole('button', { name: 'Сохранено' })).toBeVisible()
  await candidate.reload()
  await candidate.getByLabel('Только сохранённые').check()
  await expect(candidate.locator('[data-testid="discovery-role"]')).toHaveCount(1)
  await expect(candidate.locator('[data-testid="discovery-role"]')
    .filter({ hasText: 'Frontend Middle: надёжные сценарии' })).toHaveCount(1)
  await candidate.getByLabel('Только сохранённые').uncheck()

  const hiddenRole = candidate.locator('[data-testid="discovery-role"]')
    .filter({ hasText: 'Backend Middle: платёжные события' })
  await hiddenRole.getByRole('button', { name: 'Скрыть' }).click()
  await expect(candidate.locator('.undo-notice')).toContainText('Роль скрыта из вашей ленты.')
  await expect(hiddenRole).toHaveCount(0)
  await candidate.getByRole('button', { name: 'Вернуть роль' }).click()
  await expect(candidate.locator('[data-testid="discovery-role"]')
    .filter({ hasText: 'Backend Middle: платёжные события' })).toHaveCount(1)
  await candidate.locator('[data-testid="discovery-role"]')
    .filter({ hasText: 'Backend Middle: платёжные события' })
    .getByRole('button', { name: 'Скрыть' }).click()
  await candidate.reload()
  await expect(candidate.locator('[data-testid="discovery-role"]')
    .filter({ hasText: 'Backend Middle: платёжные события' })).toHaveCount(0)

  await candidate.close()
})

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
  await candidate.getByRole('button', { name: 'Мой профиль' }).click()
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
  await candidate.getByRole('button', { name: 'Мой профиль' }).click()
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

test('seed role provenance is visible in the employer role preview', async ({ browser }) => {
  const employer = await browser.newPage()
  await signIn(employer, 'employer@demo.test')
  await employer.getByRole('button', { name: 'Роль и условия' }).click()
  await expect(employer.getByRole('heading', { name: 'Сделайте вакансию понятной до отклика' })).toBeVisible()
  await expect(employer.getByText('Синтетическая вакансия').first()).toBeVisible()
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
  const alternate = snapshot.results.find((item: { id: string }) => item.id !== candidateId)
  if (!alternate) throw new Error('Expected another candidate in the search results to exercise the evidence request race')
  const alternateAlias = alternate.alias as string
  const evidenceByCandidate = await employerPage.evaluate(async ([targetId, alternateId]) => {
    const readEvidence = async (id: string) => {
      const response = await fetch(`/api/v1/employer/candidates/${id}/evidence`)
      if (!response.ok) throw new Error(`Evidence request failed with ${response.status}`)
      return await response.json() as { id: string }[]
    }
    return { target: await readEvidence(targetId), alternate: await readEvidence(alternateId) }
  }, [candidateId, alternate.id])
  const targetEvidenceIds = new Set(evidenceByCandidate.target.map(card => card.id))
  expect(evidenceByCandidate.alternate.some(card => !targetEvidenceIds.has(card.id))).toBeTruthy()

  let releaseStaleEvidence!: () => void
  let signalEvidenceRequestStarted!: () => void
  let signalStaleRouteFinished!: () => void
  const staleEvidenceGate = new Promise<void>(resolve => { releaseStaleEvidence = resolve })
  const evidenceRequestStarted = new Promise<void>(resolve => { signalEvidenceRequestStarted = resolve })
  const staleRouteFinished = new Promise<void>(resolve => { signalStaleRouteFinished = resolve })
  await employerPage.route(`**/api/v1/employer/candidates/${alternate.id}/evidence`, async route => {
    signalEvidenceRequestStarted()
    await staleEvidenceGate
    try { await route.continue() } catch { /* closing the candidate modal may abort this request */ }
    finally { signalStaleRouteFinished() }
  })
  await employerPage.locator('.candidate-card').filter({ hasText: alternateAlias })
    .getByRole('button', { name: /Пригласить с условиями/ }).click()
  await expect(employerPage.getByRole('dialog')).toBeVisible()
  await evidenceRequestStarted
  await employerPage.getByRole('button', { name: 'Закрыть' }).click()
  await employerPage.locator('.candidate-card').filter({ hasText: targetAlias })
    .getByRole('button', { name: /Пригласить с условиями/ }).click()
  await expect(employerPage.getByRole('dialog')).toBeVisible()
  const selectedEvidence = employerPage.getByRole('checkbox', { name: 'Добавить: Ранее сохранённая категория' })
  await expect(selectedEvidence).toBeChecked()
  await expect(employerPage.getByRole('checkbox', { name: 'Добавить: Навык из профиля' }).first()).not.toBeChecked()
  const legacyEvidence = employerPage.locator('.evidence-item').filter({ hasText: 'Ранее сохранённая категория' })
  await expect(legacyEvidence).toContainText('Синтетическая демонстрация')
  await expect(legacyEvidence).not.toContainText('Действие проверено заданием')
  const declaredEvidence = employerPage.locator('.evidence-item').filter({ hasText: 'Навык из профиля' })
  await expect(declaredEvidence).toHaveCount(2)
  for (const card of await declaredEvidence.all()) {
    await expect(card).toContainText('Заявлено кандидатом')
    await expect(card).not.toContainText('Действие проверено заданием')
  }
  let submittedEvidenceIds: string[] | null = null
  await employerPage.route('**/api/v1/employer/invitations', async route => {
    if (route.request().method() === 'POST') {
      submittedEvidenceIds = route.request().postDataJSON().evidence_ids as string[]
    }
    await route.continue()
  })
  releaseStaleEvidence()
  await staleRouteFinished
  await employerPage.evaluate(() => new Promise<void>(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await employerPage.getByRole('button', { name: /Отправить с выбранным основанием/ }).click()
  await expect.poll(() => submittedEvidenceIds).not.toBeNull()
  expect(submittedEvidenceIds?.every(id => targetEvidenceIds.has(id))).toBeTruthy()
  await expect(employerPage.getByRole('status')).toContainText('Приглашение отправлено')

  await employerPage.unroute(`**/api/v1/employer/candidates/${alternate.id}/evidence`)
  await employerPage.unroute('**/api/v1/employer/invitations')
  await expect(employerPage.getByRole('dialog')).toHaveCount(0)

  await candidatePage.getByRole('button', { name: 'Приглашения' }).click()
  await candidatePage.getByRole('button', { name: 'Проверить условия' }).click()
  const acceptButton = candidatePage.getByRole('button', { name: 'Принять условия' })
  await expect(acceptButton).toBeDisabled()
  await candidatePage.getByRole('checkbox', { name: /проверил.*принимаю именно эту версию/ }).check()
  await expect(acceptButton).toBeEnabled()
  let returnStaleAcceptance = true
  await candidatePage.route('**/api/v1/invitations/*/accept', async route => {
    if (returnStaleAcceptance) {
      returnStaleAcceptance = false
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'TERMS_VERSION_CONFLICT' }) })
      return
    }
    await route.continue()
  })
  await acceptButton.click()
  await expect(candidatePage.getByRole('dialog')).toHaveCount(0)
  await expect(candidatePage.getByRole('alert')).toContainText('Условия приглашения изменились')
  await candidatePage.getByRole('button', { name: 'Проверить условия' }).click()
  await expect(candidatePage.getByRole('dialog')).toBeVisible()
  const reviewedTerms = candidatePage.getByRole('checkbox', { name: /проверил.*принимаю именно эту версию/ })
  await expect(reviewedTerms).not.toBeChecked()
  await expect(acceptButton).toBeDisabled()
  await reviewedTerms.check()
  await acceptButton.click()
  await expect(candidatePage.getByRole('status')).toContainText('Контакты доступны только этой компании')
  await candidatePage.getByRole('button', { name: 'ФСП ID и доступ' }).click()
  await expect(candidatePage.getByText(/Отзыв закроет компании дальнейший доступ.*уже увидела или сохранила/)).toBeVisible()

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
