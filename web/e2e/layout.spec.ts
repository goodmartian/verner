import { expect, test } from './fixtures';

const SIZES = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
];

for (const size of SIZES) {
  test.describe(`${String(size.width)}x${String(size.height)}`, () => {
    test.use({ viewport: size });

    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'Statistics', exact: true }).click();
      await expect(page.getByText('Burning calendar')).toBeVisible();
    });

    test('the app bar is not clipped in any layout', async ({ page }) => {
      for (const tab of ['Fires', 'Statistics']) {
        await page.getByRole('button', { name: tab, exact: true }).click();
        for (const chat of ['Show chat', 'Hide chat']) {
          const toggle = page.getByRole('button', { name: chat }).first();
          if (await toggle.count()) await toggle.click();
          const clipped = await page.evaluate(() => {
            const header = document.querySelector('header');
            if (!header) return ['no header'];
            const box = header.getBoundingClientRect();
            return [...header.querySelectorAll('button, [role=tab]')]
              .filter((item) => {
                const rect = item.getBoundingClientRect();
                return rect.width > 0 && (rect.right > box.right + 0.5 || rect.right > innerWidth);
              })
              .map((item) => item.getAttribute('aria-label') ?? item.textContent);
          });
          expect(clipped).toEqual([]);
        }
      }
    });
  });
}

test.describe('a narrow screen', () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test('the app bar wraps instead of being clipped', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Statistics', exact: true }).click();
    const clipped = await page.evaluate(() => {
      const header = document.querySelector('header');
      const box = header?.getBoundingClientRect();
      return box ? box.width > innerWidth + 0.5 : true;
    });
    expect(clipped).toBe(false);
  });
});
