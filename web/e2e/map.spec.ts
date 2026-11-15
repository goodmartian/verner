import { createRequire } from 'node:module';
import type { Page } from '@playwright/test';
import { expect, showFires, test } from './fixtures';

test.use({ viewport: { width: 1440, height: 900 } });

// in dev the first map of the double mount goes a tick later: the live one is the last
const require = createRequire(import.meta.url);
const { PNG } = require('playwright-core/lib/utilsBundle') as {
  PNG: { sync: { read: (png: Buffer) => { data: Uint8Array } } };
};

/** The share of the points of two pictures of one size that differ. */
function share(a: Buffer, b: Buffer): number {
  const x = PNG.sync.read(a).data;
  const y = PNG.sync.read(b).data;
  if (x.length !== y.length) return 1;
  let different = 0;
  for (let i = 0; i < x.length; i += 4) {
    if (x[i] !== y[i] || x[i + 1] !== y[i + 1] || x[i + 2] !== y[i + 2]) different += 1;
  }
  return different / (x.length / 4);
}

const canvas = (page: Page) => page.locator('canvas.maplibregl-canvas').last();

async function mapBox(page: Page) {
  const box = await canvas(page).boundingBox();
  if (!box) throw new Error('no map');
  return box;
}

/** Draws a rectangle by dragging; the tools wake up when the map's style has loaded, so it asks again until the button beside the area is there. */
async function drawRectangle(page: Page, from: [number, number], to: [number, number]) {
  const box = await mapBox(page);
  const ask = page.getByRole('button', { name: 'Ask about this area' });
  const count = await ask.count();
  await expect(async () => {
    await page.keyboard.press('r');
    await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps: 6 });
    await page.mouse.up();
    // the button is there once the pointer has moved near the area
    await page.mouse.move(box.x + box.width * to[0] + 3, box.y + box.height * to[1] + 3);
    await expect(ask).toHaveCount(1, { timeout: 1500 });
  }).toPass({ timeout: 20_000 });
  expect(count).toBeLessThanOrEqual(1);
}

test.describe('the tools of the map', () => {
  test('sit a small gap above the chat line, and inside the calendar window', async ({ page }) => {
    const gaps = () =>
      page.evaluate(() => {
        const tools = document.querySelector('[role=toolbar]')?.getBoundingClientRect();
        const form = document.querySelector('form')?.getBoundingClientRect();
        const frame = document.querySelector('main.stage')?.getBoundingClientRect();
        if (!tools || !form || !frame) throw new Error('missing box');
        return { chat: form.top - tools.bottom, window: frame.bottom - tools.bottom };
      });
    await page.goto('/');
    await showFires(page);
    await expect(page.locator('[role=toolbar]')).toBeVisible();
    // the toolbar stands 7 px over the line of the chat (once the chat has taken its place)
    await expect.poll(async () => Math.abs((await gaps()).chat - 7)).toBeLessThanOrEqual(2);
    await page.getByRole('button', { name: 'Statistics', exact: true }).click();
    await expect(page.getByText('Burning calendar')).toBeVisible();
    const calendar = await gaps();
    expect(calendar.window).toBeGreaterThan(0);
  });

  test('keep north up: a drag of the right button does not turn the map', async ({ page }) => {
    // the moving wind would change the picture by itself
    await page.addInitScript(() => {
      localStorage.setItem('senda-wind-animation', 'off');
    });
    await page.goto('/');
    await expect(canvas(page)).toBeVisible();
    // the tiles come in and the map settles
    await page.waitForTimeout(4000);
    const box = await mapBox(page);
    // both pictures are taken with the pointer in the same place outside the map: a tip or a hover would differ otherwise
    const away = () => page.mouse.move(box.x + 5, box.y + 5);
    await away();
    await expect(page.locator('.wx-tip')).toHaveCount(0);
    const before = await canvas(page).screenshot();
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
    await page.mouse.down({ button: 'right' });
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.3, { steps: 8 });
    await page.mouse.up({ button: 'right' });
    await away();
    await expect(page.locator('.wx-tip')).toHaveCount(0);
    await page.waitForTimeout(500);
    // a turned map would change most of the picture; a blinking caret or a late tile changes a few points
    const after = await canvas(page).screenshot();
    expect(share(before, after)).toBeLessThan(0.002);
  });
});

test.describe('drawn areas', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Statistics', exact: true }).click();
    await expect(page.getByText('Burning calendar')).toBeVisible();
  });

  test('can be many; only the one just drawn has the button to ask, until the eraser', async ({
    page,
  }) => {
    await drawRectangle(page, [0.15, 0.2], [0.35, 0.45]);
    await drawRectangle(page, [0.15, 0.5], [0.3, 0.62]);
    await expect(page.getByRole('button', { name: 'Ask about this area' })).toHaveCount(1);
    await page.getByRole('button', { name: 'Clear drawings' }).click();
    await expect(page.getByRole('button', { name: 'Ask about this area' })).toHaveCount(0);
  });

  test('are looked at in the calendar from the region window, one at a time', async ({ page }) => {
    await drawRectangle(page, [0.15, 0.2], [0.35, 0.45]);
    await drawRectangle(page, [0.15, 0.5], [0.3, 0.62]);
    await page.locator('#cal-area').click();
    const asked = page.waitForRequest((request) => request.url().includes('/api/calendar'));
    await page.getByRole('option', { name: 'Map area 2' }).click();
    expect(((await asked).postDataJSON() as { area: object }).area).toHaveProperty('polygon');
    await expect(page.getByRole('button', { name: 'Map area 2' }).first()).toBeVisible();
  });
});

for (const width of [375, 768]) {
  test(`the button to ask about a drawn area shows at once at ${String(width)}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await expect(canvas(page)).toBeVisible();
    await drawRectangle(page, [0.2, 0.2], [0.5, 0.5]);
    await expect(page.getByRole('button', { name: 'Ask about this area' })).toHaveCSS(
      'opacity',
      '1',
    );
  });
}
