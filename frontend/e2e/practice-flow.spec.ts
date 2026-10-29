import { expect, test } from '@playwright/test';
import { clearBrowserWorkspace, seedPlayerFromSample } from './helpers';

test.describe('Practice flow', () => {
  test.beforeEach(async ({ page }) => {
    await clearBrowserWorkspace(page);
  });

  test('kfctofu can start practice with agent-generated prompt copy', async ({ page, request }) => {
    await seedPlayerFromSample(request, 'kfctofu');

    await page.goto('/practice');
    await expect(page.getByRole('heading', { name: 'Train mistakes from your games' })).toBeVisible();
    await page.getByRole('button', { name: /Start practice/i }).click();

    await expect(page).toHaveURL(/\/practice\/.+/);
    await expect(page.getByRole('heading', { level: 2, name: /what would you play|pattern in your game/i })).toBeVisible();
    await expect(page.locator('.practice-board')).toBeVisible();
  });

  test('games page shows account sync only (no PGN paste)', async ({ page }) => {
    await page.goto('/games');
    await page.getByRole('button', { name: /Import games/i }).click();
    await expect(page.getByLabel('Player username')).toBeVisible();
    await expect(page.getByRole('button', { name: /Sync full history/i })).toBeVisible();
    await expect(page.getByText('Analyze pasted PGN')).toHaveCount(0);
    await expect(page.getByText('PGN review')).toHaveCount(0);
    await expect(page.locator('textarea')).toHaveCount(0);
  });

  test('empty player shows no positions after practice start', async ({ page }) => {
    await page.goto('/games');
    await page.getByRole('button', { name: /Import games/i }).click();
    await page.getByLabel('Player username').fill('brand_new_empty_player');
    await page.getByRole('link', { name: 'Practice' }).click();
    await page.getByRole('button', { name: /Start practice/i }).click();
    await expect(page.getByRole('heading', { name: 'No positions due' })).toBeVisible();
  });
});
