import { expect, type Page } from '@playwright/test'

export async function signIn(page: Page, email: string) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Вход' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Пароль').fill('DemoPass123!')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('button', { name: 'Выйти' })).toBeVisible()
}

export async function currentUserId(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/me')
    const user = await response.json()
    return user.id as string
  })
}
