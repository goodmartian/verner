import { expect, test as base } from '@playwright/test';

export { expect };

/** The app opens on the calendar; this goes to the fires. */
export async function showFires(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Fires', exact: true }).click();
}

/** The app in English, whatever the browser says, with the wind of the map standing still. */
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      localStorage.setItem('senda-lang', 'en');
      // a still map: the pictures of two moments can be compared
      localStorage.setItem('senda-wind-animation', 'off');
    });
    await use(page);
  },
});
