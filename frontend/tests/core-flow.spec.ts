import { expect, test } from '@playwright/test'
import { currentUserId, signIn } from './test-support'

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
  const discoveryRoles = candidate.locator('[data-testid="discovery-role"]')
  await expect(discoveryRoles).toHaveCount(10)
  await expect(discoveryRoles.filter({ hasText: 'QA Junior: качество пользовательских сценариев' })).toBeVisible()
  await expect(discoveryRoles.filter({ hasText: 'Аналитик данных Junior: SQL и качество витрин' })).toBeVisible()

  const savedRole = discoveryRoles
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
  let releaseInitialProfileRead = () => {}
  let markInitialProfileReadReady = () => {}
  const initialProfileReadGate = new Promise<void>(resolve => { releaseInitialProfileRead = resolve })
  const initialProfileReadReady = new Promise<void>(resolve => { markInitialProfileReadReady = resolve })
  let delayedInitialProfileRead = false
  await candidate.route('**/api/v1/candidate/profile', async route => {
    if (route.request().method() === 'GET' && !delayedInitialProfileRead) {
      delayedInitialProfileRead = true
      const response = await route.fetch()
      markInitialProfileReadReady()
      await initialProfileReadGate
      await route.fulfill({ response })
    } else await route.continue()
  })
  await signIn(candidate, 'backend-middle-1@demo.test')
  await initialProfileReadReady
  await candidate.getByRole('button', { name: 'Условия поиска' }).click()
  await candidate.getByLabel(/Минимум, ₽ в месяц/).fill('175000')
  await candidate.getByLabel(/Города для гибрида и офиса/).fill('Москва')
  await expect(candidate.getByLabel(/мне исполнилось 18 лет/)).toBeChecked()
  await candidate.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(candidate.locator('.notice')).toContainText('Условия обновлены')

  releaseInitialProfileRead()
  await candidate.getByRole('button', { name: 'Мой профиль' }).click()
  await expect(candidate.getByLabel('Имя и фамилия')).not.toHaveValue('')
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
  await candidate.getByRole('button', { name: 'Условия поиска' }).click()
  await expect(candidate.getByLabel(/Минимум, ₽ в месяц/)).toHaveValue('175000')

  const employer = await browser.newPage()
  await signIn(employer, 'employer@demo.test')
  const forbidden = await employer.evaluate(async () => (await fetch('/api/v1/candidate/preferences')).status)
  expect(forbidden).toBe(403)
  await candidate.close()
  await employer.close()
})

test('a stale profile form cannot overwrite preferences changed in another session', async ({ browser }) => {
  const staleProfileTab = await browser.newPage()
  await signIn(staleProfileTab, 'backend-middle-1@demo.test')
  await staleProfileTab.getByRole('button', { name: 'Мой профиль' }).click()
  const summary = staleProfileTab.getByLabel('Опыт и задачи')
  await expect(summary).toBeVisible()

  const preferencesTab = await browser.newPage()
  await signIn(preferencesTab, 'backend-middle-1@demo.test')
  await preferencesTab.getByRole('button', { name: 'Условия поиска' }).click()
  await preferencesTab.getByLabel(/Минимум, ₽ в месяц/).fill('205000')
  await preferencesTab.getByLabel(/Города для гибрида и офиса/).fill('Казань')
  await preferencesTab.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(preferencesTab.getByRole('status')).toContainText('Условия обновлены')

  await summary.fill('Черновик, открытый до обновления условий в другой вкладке.')
  await staleProfileTab.getByRole('button', { name: 'Сохранить профиль' }).click()
  await expect(staleProfileTab.getByRole('alert')).toContainText(/изменились в другой вкладке/i)

  const currentPreferences = await staleProfileTab.evaluate(async () => {
    const response = await fetch('/api/v1/candidate/preferences')
    return await response.json()
  })
  expect(currentPreferences.salary_min_rub).toBe(205000)
  expect(currentPreferences.allowed_cities).toEqual(['Казань'])

  await staleProfileTab.getByRole('button', { name: 'Условия поиска' }).click()
  await expect(staleProfileTab.getByLabel(/Минимум, ₽ в месяц/)).toHaveValue('205000')
  await staleProfileTab.getByLabel(/Минимум, ₽ в месяц/).fill('175000')
  await staleProfileTab.getByLabel(/Города для гибрида и офиса/).fill('Москва')
  await staleProfileTab.getByRole('button', { name: 'Сохранить условия' }).click()
  await expect(staleProfileTab.getByRole('status')).toContainText('Условия обновлены')

  await staleProfileTab.close()
  await preferencesTab.close()
})

test('company setup is reachable after company-profile-required on role creation', async ({ browser }) => {
  const employer = await browser.newPage()
  await signIn(employer, 'employer@demo.test')
  await employer.getByRole('button', { name: 'Роль и условия' }).click()
  await employer.getByRole('button', { name: 'Новая потребность' }).click()
  await employer.getByLabel('Название роли').fill('QA Middle для биллинга')
  await employer.getByLabel('Чем будет заниматься специалист').fill('Проверять надёжность платёжных сценариев и интеграций.')
  await employer.getByLabel('Повторные события').check()
  await employer.route('**/api/v1/employer/needs', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'COMPANY_PROFILE_REQUIRED' }) })
    } else await route.continue()
  })
  await employer.getByRole('button', { name: 'Создать черновик роли' }).click()
  await expect(employer.getByRole('alert')).toContainText(/заполните профиль компании/i)
  const setupCompany = employer.getByRole('button', { name: 'Перейти к профилю компании' })
  await expect(setupCompany).toBeVisible({ timeout: 500 })
  await setupCompany.click()
  await expect(employer.getByRole('heading', { name: 'Кто приглашает кандидата?' })).toBeVisible()
  await expect(employer.getByRole('button', { name: 'Вернуться к роли' })).toBeVisible()
  await employer.getByRole('button', { name: 'Вернуться к роли' }).click()
  await expect(employer.getByLabel('Название роли')).toHaveValue('QA Middle для биллинга')
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
  const targetCard = employerPage.locator('.candidate-card').filter({ hasText: targetAlias })
  await expect.soft(targetCard.getByText(/Соответствие роли/)).toBeVisible({ timeout: 500 })
  await expect.soft(targetCard.getByText(/Результат теста/)).toBeVisible({ timeout: 500 })
  await expect.soft(targetCard.getByText(/Охват доказательствами/)).toBeVisible({ timeout: 500 })
  const unknownMatchComponents = Object.entries(target.match?.components ?? {})
    .filter(([, value]) => value == null)
    .map(([name]) => name)
  if (unknownMatchComponents.length > 0) {
    const unknownData = targetCard.locator('.unknown-match-data')
    await expect.soft(unknownData).toBeVisible({ timeout: 500 })
    const labels: Record<string, string> = {
      competencies: 'компетенциям', assessment: 'результату теста', text: 'содержанию роли',
    }
    for (const component of unknownMatchComponents) {
      await expect.soft(unknownData).toContainText(labels[component] ?? component, { timeout: 500 })
    }
  }
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
  const draftOffer = employerPage.getByLabel('Текст приглашения')
  const draftReason = employerPage.getByLabel(/Почему выбрали кандидата/)
  await draftOffer.fill('Приглашаем обсудить обработку платёжных событий в команде.')
  await draftReason.fill('Опыт с идемпотентной обработкой подтверждён в истории кандидата.')
  await employerPage.route('**/api/v1/employer/invitations', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'COMPANY_PROFILE_REQUIRED' }) })
    } else await route.continue()
  })
  await employerPage.getByRole('button', { name: /Отправить с выбранным основанием/ }).click()
  await expect.soft(employerPage.getByRole('alert')).toContainText(/заполните профиль компании/i, { timeout: 500 })
  const companySetupButton = employerPage.getByRole('button', { name: 'Перейти к профилю компании' })
  await expect.soft(companySetupButton).toBeVisible({ timeout: 500 })
  await expect(draftOffer).toHaveValue('Приглашаем обсудить обработку платёжных событий в команде.')
  await expect(draftReason).toHaveValue('Опыт с идемпотентной обработкой подтверждён в истории кандидата.')
  if (await companySetupButton.isVisible()) {
    await companySetupButton.click()
    await expect(employerPage.getByRole('heading', { name: 'Кто приглашает кандидата?' })).toBeVisible()
    const companyName = employerPage.getByLabel('Название компании')
    const savedCompanyName = await companyName.inputValue()
    await employerPage.route('**/api/v1/employer/company', async route => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'COMPANY_SAVE_FAILED' }) })
      } else await route.continue()
    })
    await employerPage.getByRole('button', { name: 'Сохранить компанию' }).click()
    await expect.soft(employerPage.getByRole('alert')).toContainText('Сервис временно недоступен', { timeout: 500 })
    await expect.soft(employerPage.getByRole('alert')).not.toContainText('COMPANY_SAVE_FAILED', { timeout: 500 })
    await expect(companyName).toHaveValue(savedCompanyName)
    await expect(employerPage.getByRole('button', { name: 'Вернуться к приглашению' })).toBeVisible()
    await employerPage.unroute('**/api/v1/employer/company')
    await employerPage.getByRole('button', { name: 'Вернуться к приглашению' }).click()
    await expect(employerPage.getByRole('dialog')).toBeVisible()
    await expect(draftOffer).toHaveValue('Приглашаем обсудить обработку платёжных событий в команде.')
    await expect(draftReason).toHaveValue('Опыт с идемпотентной обработкой подтверждён в истории кандидата.')
  }
  await employerPage.unroute('**/api/v1/employer/invitations')
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

  await employerPage.getByRole('button', { name: 'Приглашения' }).click()
  const firstEmployerOffer = employerPage.locator('.offer-card').filter({ hasText: candidateId.slice(0, 8) })
  const withdrawFirstOffer = firstEmployerOffer.getByRole('button', { name: 'Отозвать приглашение' })
  await expect(withdrawFirstOffer).toBeVisible()

  await candidatePage.getByRole('button', { name: 'Приглашения' }).click()
  const candidateFirstOffer = candidatePage.locator('.offer-card')
    .filter({ hasText: 'Приглашаем обсудить обработку платёжных событий в команде.' })
  await candidateFirstOffer.getByRole('button', { name: 'Проверить условия' }).click()
  await expect(candidatePage.getByRole('dialog')).toBeVisible()

  await withdrawFirstOffer.click()
  await expect(employerPage.getByRole('alert')).toContainText('Список обновлён')
  await expect(firstEmployerOffer).toContainText('Просмотрено')
  await expect(withdrawFirstOffer).toBeEnabled()
  await withdrawFirstOffer.click()
  await expect(firstEmployerOffer).toContainText('Отозвано')

  await candidatePage.reload()
  await candidatePage.getByRole('button', { name: 'Приглашения' }).click()
  const withdrawnCandidateOffer = candidatePage.locator('.offer-card')
    .filter({ hasText: 'Приглашаем обсудить обработку платёжных событий в команде.' })
  await expect(withdrawnCandidateOffer).toContainText('Отозвано')
  await expect(withdrawnCandidateOffer.getByRole('button', { name: 'Проверить условия' })).toHaveCount(0)

  await employerPage.getByRole('button', { name: 'Найти специалиста' }).click()
  await employerPage.locator('.candidate-card').filter({ hasText: targetAlias })
    .getByRole('button', { name: /Пригласить с условиями/ }).click()
  await expect(employerPage.getByRole('dialog')).toBeVisible()
  await employerPage.getByRole('button', { name: /Отправить с выбранным основанием/ }).click()
  await expect(employerPage.getByRole('status')).toContainText('Приглашение отправлено')
  await candidatePage.getByRole('button', { name: 'Мой профиль' }).click()
  await candidatePage.getByRole('button', { name: 'Приглашения' }).click()
  await expect(candidatePage.locator('.offer-card').filter({
    hasText: 'Приглашаем обсудить роль Backend Middle: события и задачи команды.',
  }).getByRole('button', { name: 'Проверить условия' })).toBeVisible()

  const rejectedCandidateOffer = candidatePage.locator('.offer-card').filter({
    hasText: 'Приглашаем обсудить роль Backend Middle: события и задачи команды.',
  })
  await rejectedCandidateOffer.getByRole('button', { name: 'Отклонить' }).click()
  await expect(candidatePage.getByRole('status')).toContainText('Ваши контакты не раскрыты')
  await expect(rejectedCandidateOffer).toContainText('Отклонено')

  await employerPage.getByRole('button', { name: 'Найти специалиста' }).click()
  await employerPage.locator('.candidate-card').filter({ hasText: targetAlias })
    .getByRole('button', { name: /Пригласить с условиями/ }).click()
  await expect(employerPage.getByRole('dialog')).toBeVisible()
  await employerPage.getByRole('button', { name: /Отправить с выбранным основанием/ }).click()
  await expect(employerPage.getByRole('status')).toContainText('Приглашение отправлено')
  await candidatePage.reload()
  await candidatePage.getByRole('button', { name: 'Приглашения' }).click()
  await expect(candidatePage.locator('.offer-card').filter({
    hasText: 'Приглашаем обсудить роль Backend Middle: события и задачи команды.',
  }).getByRole('button', { name: 'Проверить условия' })).toBeVisible()

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
  await expect(secondCandidatePage.locator('.compatibility-summary'))
    .toContainText(/Условия соответствуют сохранённым ограничениям|Часть условий не указана/)
  await secondCandidatePage.getByRole('checkbox', { name: /проверил.*принимаю именно эту версию/ }).check()
  await secondCandidatePage.getByRole('button', { name: 'Принять условия' }).click()
  await expect(secondCandidatePage.getByRole('status')).toContainText('Контакты доступны только этой компании')

  const acceptedCandidateOffer = secondCandidatePage.locator('.offer-card')
    .filter({ hasText: 'Приглашаем обсудить роль' })
  const candidateConfirmation = acceptedCandidateOffer.getByRole('button', { name: 'Подтвердить встречу' })
  await expect.soft(candidateConfirmation).toBeVisible({ timeout: 500 })
  if (await candidateConfirmation.isVisible()) {
    await candidateConfirmation.click()
    await expect(acceptedCandidateOffer).toContainText('Ждём подтверждения работодателя')
    await expect(acceptedCandidateOffer).not.toContainText('Встреча подтверждена обеими сторонами')
  }

  await employerPage.getByRole('button', { name: 'Приглашения' }).click()
  const acceptedEmployerOffer = employerPage.locator('.offer-card')
    .filter({ hasText: secondCandidateId.slice(0, 8) })
  const employerConfirmation = acceptedEmployerOffer.getByRole('button', { name: 'Подтвердить встречу' })
  await expect.soft(employerConfirmation).toBeVisible({ timeout: 500 })
  if (await employerConfirmation.isVisible()) {
    await employerConfirmation.click()
    await expect(acceptedEmployerOffer).toContainText('Встреча подтверждена обеими сторонами')
    await secondCandidatePage.reload()
    await secondCandidatePage.getByRole('button', { name: 'Приглашения' }).click()
    await expect(secondCandidatePage.locator('.offer-card').filter({ hasText: 'Приглашаем обсудить роль' }))
      .toContainText('Встреча подтверждена обеими сторонами')
  }
  await employerPage.getByRole('button', { name: new RegExp(`Показать контакты кандидата #${secondCandidateId.slice(0, 8)}`) }).click()
  const secondContactCard = employerPage.locator('.offer-card').filter({ hasText: secondCandidateId.slice(0, 8) })
  await expect(secondContactCard.getByText('backend-middle-2@demo.test')).toBeVisible()
  const firstContactCard = employerPage.locator('.offer-card').filter({ hasText: candidateId.slice(0, 8) })
  await firstContactCard.getByRole('button', { name: /Показать контакты кандидата/ }).click()
  await expect(firstContactCard.getByText('backend-middle-1@demo.test')).toBeVisible()
  await expect(secondContactCard.getByText('backend-middle-2@demo.test')).toBeVisible()

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
