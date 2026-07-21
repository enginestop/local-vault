import { expect, test } from '@playwright/test'

test('first-run shell is responsive and exposes the permanent LAN warning', async ({ page }) => {
  test.setTimeout(10_000)
  await page.route('**/api/v1/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ setup_required: true, application_version: '1.0.0', api_version: 'v1', schema_version: 1, recovery_enabled: false, port: 8741, http_lan_warning: true }),
  }))
  await page.goto('/')
  await expect(page.getByText(/HTTP LAN tidak terenkripsi|HTTP LAN is unencrypted/, { exact: false }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /Buat vault baru|Create new vault/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})
