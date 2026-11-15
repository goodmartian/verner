import type { Page } from '@playwright/test';
import { expect, showFires, test } from './fixtures';

/**
 * Opens the first fire of the list. When the last three days hold none, the example fires stand
 * in: what is checked is the same.
 */
async function openFirstFire(page: Page) {
  await page.goto('/');
  await showFires(page);
  const rows = page.locator('#fires .fire-row');
  const example = page.getByRole('button', { name: 'Show an example' });
  await expect(rows.first().or(example)).toBeVisible();
  if (await example.isVisible()) await example.click();
  await rows.first().click();
  await expect(page.locator('.fire-strip')).toBeVisible();
}

/** Turns the plan form on from the "+" of the chat line. */
async function startPlan(page: Page) {
  await page.locator('#plus-btn').click();
  await page.getByRole('menuitemcheckbox', { name: 'Work plan' }).click();
  await expect(page.locator('#pm')).toBeVisible();
}

test('the list shows the fires with their number and the period', async ({ page }) => {
  await page.goto('/');
  await showFires(page);
  await expect(page.getByRole('heading', { name: 'Active fires' })).toBeVisible();
  await expect(page.getByText(/ to .* · Updated /)).toBeVisible();
  const rows = page.locator('#fires .fire-row');
  await expect(rows.first()).toBeVisible();
  await expect(page.locator('#count')).toHaveText(String(await rows.count()));
});

test('a fire opens with its numbers in the side panel, a short head over the map, and the list comes back', async ({
  page,
}) => {
  await openFirstFire(page);
  const side = page.locator('#v-fire');
  await expect(side.getByText('Area, estimate', { exact: true })).toBeVisible();
  await expect(side.getByText('Wind', { exact: true })).toBeVisible();
  await expect(side.getByText('Air', { exact: true })).toBeVisible();
  await expect(side.getByRole('heading', { name: 'Growth by pass' })).toBeVisible();
  await page.locator('.fire-strip').getByRole('button', { name: 'All fires' }).click();
  await expect(page.getByRole('heading', { name: 'Active fires' })).toBeVisible();
});

for (const width of [1280, 1440, 1920]) {
  test(`the cross of the strip of a fire is whole inside it at ${String(width)} px, the cells never reach it`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await openFirstFire(page);
    const strip = page.locator('.fire-strip');
    await expect(strip).toBeVisible();
    const box = await strip.boundingBox();
    const cross = await strip.getByRole('button', { name: 'All fires' }).boundingBox();
    if (!box || !cross) throw new Error('the strip and its cross are on the page');
    expect(cross.x).toBeGreaterThanOrEqual(box.x);
    expect(cross.x + cross.width).toBeLessThanOrEqual(box.x + box.width);
    const cells = await strip
      .locator('.fs-cells > span')
      .evaluateAll((items) => items.map((item) => item.getBoundingClientRect().right));
    for (const right of cells) expect(right).toBeLessThanOrEqual(cross.x);
  });
}

test('the passes play over the map: one is chosen, the row closes', async ({ page }) => {
  await openFirstFire(page);
  await page.getByRole('button', { name: 'Passes', exact: true }).click();
  const player = page.getByRole('region', { name: 'Satellite passes' });
  await expect(player).toBeVisible();
  // the handle of the scale moves from pass to pass with the arrows
  await player.getByRole('slider').focus();
  await page.keyboard.press('Home');
  await expect(player.locator('.tl-handle')).toHaveCount(1);
  await player.getByRole('button', { name: 'Play passes' }).click();
  await expect(player.getByRole('button', { name: 'Pause' })).toBeVisible();
  await player.getByRole('button', { name: 'Close the player' }).click();
  await expect(player).toBeHidden();
});

test('a pass chosen in the player changes the card and the detections on the map', async ({
  page,
}) => {
  await openFirstFire(page);
  await page.getByRole('button', { name: 'Passes', exact: true }).click();
  const player = page.getByRole('region', { name: 'Satellite passes' });
  await expect(player).toBeVisible();
  const slider = player.getByRole('slider');
  const detections = page
    .locator('#v-fire')
    .getByText('Detections', { exact: true })
    .locator('xpath=following-sibling::b');
  const canvas = page.locator('canvas.maplibregl-canvas');
  await slider.focus();
  await page.keyboard.press('Home');
  const first = (await detections.textContent()) ?? '';
  await page.waitForTimeout(3000);
  const early = await canvas.screenshot();
  // the fire is not on the first pass: the handle walks on until the numbers change
  for (let step = 0; step < 12 && (await detections.textContent()) === first; step += 1) {
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
  }
  await expect(detections).not.toHaveText(first);
  // on to a pass with more of the fire on it, so the map has something to show
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(3000);
  // compared as bytes: printing two pictures as a difference takes minutes
  expect((await canvas.screenshot()).equals(early)).toBe(false);
});

test.describe('a plan', () => {
  test('takes an entry mark from the map, moves it with undo and takes it off', async ({
    page,
  }) => {
    await openFirstFire(page);
    await startPlan(page);
    await page.getByRole('button', { name: 'Entry point' }).click();
    const map = page.locator('.maplibregl-canvas');
    const box = await map.boundingBox();
    if (!box) throw new Error('the map is not on the page');
    const mark = page.locator('.mark.entry');
    // the map takes clicks once it has loaded: ask again until the mark is there
    await expect(async () => {
      await page.mouse.click(box.x + box.width * 0.7, box.y + box.height * 0.4);
      await expect(mark.getByText('Entry 1')).toBeVisible({ timeout: 1000 });
    }).toPass();
    await expect(page.locator('#pm').getByText('1 entries')).toBeVisible();
    // undo takes the mark back, redo puts it again
    await page.getByRole('button', { name: 'Undo' }).click();
    await expect(mark).toHaveCount(0);
    await page.getByRole('button', { name: 'Redo' }).click();
    await expect(mark).toHaveCount(1);
    await mark.hover();
    await page.getByRole('button', { name: 'Remove Entry 1' }).click();
    await expect(mark).toHaveCount(0);
  });

  test('is kept on the server, shows in the list, opens as it was made and is deleted', async ({
    page,
  }) => {
    await openFirstFire(page);
    await startPlan(page);
    await page.getByRole('button', { name: 'Entry point' }).click();
    const map = page.locator('.maplibregl-canvas');
    const box = await map.boundingBox();
    if (!box) throw new Error('the map is not on the page');
    const mark = page.locator('.mark.entry');
    await expect(async () => {
      await page.mouse.click(box.x + box.width * 0.7, box.y + box.height * 0.4);
      await expect(mark.getByText('Entry 1')).toBeVisible({ timeout: 1000 });
    }).toPass();
    await page.getByRole('button', { name: 'Send' }).click();
    await page.locator('.artifact').click();
    await page.getByRole('button', { name: 'Save the plan' }).click();
    await expect(page.getByRole('button', { name: 'Plan saved' })).toBeVisible();
    await page.goto('/');
    await showFires(page);
    const shelf = page.locator('#saved-plans');
    await expect(shelf.locator('.hist-item')).toHaveCount(1);
    await shelf.locator('.hist-item').click();
    await expect(page.getByRole('button', { name: 'Back to the chat' })).toBeVisible();
    await page.goto('/');
    await showFires(page);
    await shelf.getByRole('button', { name: /^Delete plan/ }).click();
    await expect(shelf).toHaveCount(0);
  });
});

for (const width of [1440, 375]) {
  test(`a figure of the fire asks the assistant at ${String(width)}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openFirstFire(page);
    // the sheet scrolls to the top when a fire opens, and a scroll closes a card: let it settle first
    await page.waitForTimeout(600);
    // a press on the tile brings a pill beside it; the pill puts the figure in the question
    await page.getByRole('button', { name: /Area, estimate/ }).click();
    const pill = page.getByRole('button', { name: 'Ask SI' });
    await expect(pill).toBeVisible();
    await pill.click();
    await expect(page.locator('.att', { hasText: 'Area, estimate' })).toBeVisible();
    await expect(pill).toBeHidden();
  });
}
