import { expect, test } from './fixtures';

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Statistics', exact: true }).click();
});

test('the month in four figures and the burning calendar', async ({ page }) => {
  for (const label of ['Detections', /^Usual/, 'Against usual', 'Among other years']) {
    await expect(
      page.getByText(label, typeof label === 'string' ? { exact: true } : undefined).first(),
    ).toBeVisible();
  }
  await expect(page.getByText('Burning calendar')).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/NaN|Infinity|undefined/);
});

test('a month of the grid is picked and the figures follow it', async ({ page }) => {
  const cell = page.getByRole('button', { name: /January 2024:/ });
  await cell.click();
  await expect(cell).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: /^January is / })).toBeVisible();
});

test('a press on a cell shows the «Ask SI» pill and it puts the month in the question', async ({
  page,
}) => {
  const cell = page.getByRole('button', { name: /January 2024:/ });
  // the board scrolls to the cell first: a pill goes when the board scrolls under it
  await cell.scrollIntoViewIfNeeded();
  const pill = page.locator('button[aria-describedby]', { hasText: 'Ask SI' });
  // a rest of the pointer shows nothing
  await cell.hover();
  await page.waitForTimeout(500);
  await expect(pill).toBeHidden();
  await cell.click();
  await expect(cell).toHaveAttribute('aria-pressed', 'true');
  await expect(pill).toBeVisible();
  await pill.click();
  await expect(pill).toBeHidden();
  await expect(page.getByRole('textbox').last()).toBeFocused();
  await expect(page.locator('.composer')).toContainText('January 2024');
});

test('an unused pill goes by itself', async ({ page }) => {
  const cell = page.getByRole('button', { name: /January 2024:/ });
  await cell.scrollIntoViewIfNeeded();
  await cell.click();
  const pill = page.locator('button[aria-describedby]', { hasText: 'Ask SI' });
  await expect(pill).toBeVisible();
  await page.mouse.move(5, 5);
  await expect(pill).toBeHidden({ timeout: 7000 });
});

test('the month head on the map is only on the enlarged map, with «Ask SI»', async ({ page }) => {
  // the small map beside the board has no head, and no button of it
  await expect(page.locator('.month-strip')).toHaveCount(0);
  await page.locator('#cal-map-max').click();
  const head = page.locator('.month-strip');
  await expect(head).toBeVisible();
  await expect(head.getByRole('button', { name: 'Ask SI' })).toBeVisible();
});

test('a new month asks only for what depends on the month, and no skeleton shows', async ({
  page,
}) => {
  await expect(page.getByRole('button', { name: /January 2024:/ })).toBeVisible();
  const asked: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/'))
      asked.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  await page.getByRole('button', { name: /February 2024:/ }).click();
  await expect(page.getByRole('button', { name: /February 2024:/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.waitForTimeout(500);
  expect(asked.filter((call) => call === 'POST /api/calendar')).toHaveLength(0);
  expect(asked.filter((call) => call === 'GET /api/meta')).toHaveLength(0);
  await expect(page.locator('.skel')).toHaveCount(0);
});

test('the bar of sections takes the board to the section', async ({ page }) => {
  await page.getByRole('button', { name: 'Accuracy', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Accuracy' })).toBeInViewport();
});

test('a cue says there is more below, and goes at the end of the board', async ({ page }) => {
  const more = page.getByRole('button', { name: 'More below' });
  await expect(more).toBeVisible();
  await page.locator('.cal-body').evaluate((box) => {
    box.scrollTop = box.scrollHeight;
  });
  await expect(more).toBeHidden();
});

test('the whole world is a board of its own', async ({ page }) => {
  await page.locator('#cal-area').click();
  await page
    .getByRole('dialog')
    .getByRole('option', { name: /^World/ })
    .click();
  await expect(page.locator('#cal-area')).toContainText('World');
  await expect(page.getByText('Detections', { exact: true }).first()).toBeVisible();
});

test('a server that is down is said so, and the button asks again', async ({ page }) => {
  let down = true;
  await page.route('**/api/calendar', (route) => {
    if (route.request().method() !== 'POST' || !down) return route.continue();
    return route.abort('failed');
  });
  await page.locator('#cal-area').click();
  await page
    .getByRole('dialog')
    .getByRole('option', { name: /^World/ })
    .click();
  const retry = page.getByRole('button', { name: 'Retry' });
  await expect(retry).toBeVisible();
  // the board may ask twice by itself; the server comes back only after the button asked and was refused
  await retry.click();
  await expect(retry).toBeEnabled();
  down = false;
  await retry.click();
  await expect(page.getByText('Burning calendar')).toBeVisible();
});
