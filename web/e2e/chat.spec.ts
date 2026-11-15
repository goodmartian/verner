import { expect, test } from './fixtures';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test('the send button is grey until there is a question', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  await page.getByRole('textbox', { name: 'Ask about the fires' }).fill('Hello');
  await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
});
