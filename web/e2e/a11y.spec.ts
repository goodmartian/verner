import AxeBuilder from '@axe-core/playwright';
import { expect, showFires, test } from './fixtures';

async function violations(page: import('@playwright/test').Page) {
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    // the map is a picture of someone else's tiles
    .exclude('.maplibregl-map')
    .analyze();
  return result.violations.map(
    (item) => `${item.id}: ${item.nodes.map((node) => node.target.join(' ')).join(' | ')}`,
  );
}

test('the fires tab', async ({ page }) => {
  await page.goto('/');
  await showFires(page);
  await expect(page.getByRole('heading', { name: 'Active fires' })).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

test('an open fire with the passes', async ({ page }) => {
  await page.goto('/');
  await showFires(page);
  await page.locator('#fires .fire-row').first().click();
  await expect(page.locator('.fire-strip')).toBeVisible();
  await page.getByRole('button', { name: 'Passes', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Satellite passes' })).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

test('the calendar tab', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Statistics', exact: true }).click();
  await expect(page.getByText('Burning calendar')).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

test('the period menu', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Statistics', exact: true }).click();
  await page.locator('#pp-btn').click();
  await expect(page.getByRole('dialog', { name: 'Period' })).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

test('the region window', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Statistics', exact: true }).click();
  await page
    .getByRole('button', { name: /Argentina/ })
    .first()
    .click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

test.describe('a work plan', () => {
  test('the form and the plan', async ({ page }) => {
    await page.goto('/');
    await showFires(page);
    await page.locator('#fires .fire-row').first().click();
    await page.locator('#plus-btn').click();
    await page.getByRole('menuitemcheckbox', { name: 'Work plan' }).click();
    await expect(page.locator('#pm')).toBeVisible();
    expect(await violations(page)).toEqual([]);
    await page.locator('#send').click();
    await page.locator('.artifact').click();
    await expect(page.locator('.crew-card').first()).toBeVisible();
    expect(await violations(page)).toEqual([]);
  });
});
