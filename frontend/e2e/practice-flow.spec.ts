import { expect, test } from '@playwright/test';
import { clearBrowserWorkspace, seedPlayerFromSample, selectPlayer } from './helpers';

test.describe('Practice flow', () => {
  test.beforeEach(async ({ page }) => {
    await clearBrowserWorkspace(page);
  });

  test('kfctofu can start practice with agent-generated prompt copy', async ({ page, request }) => {
    await seedPlayerFromSample(request, 'kfctofu');
    await selectPlayer(page, 'kfctofu');

    await page.goto('/practice');
    await expect(page.getByRole('heading', { name: 'Train mistakes from your games' })).toBeVisible();
    await page.getByRole('button', { name: /Start practice/i }).click();

    await expect(page).toHaveURL(/\/practice\/.+/);
    await expect(page.getByRole('heading', { level: 2, name: /what would you play|pattern in your game/i })).toBeVisible();
    await expect(page.locator('.practice-board')).toBeVisible();
  });

  test('games page offers account sync and PGN import', async ({ page }) => {
    await page.goto('/games?import=true');
    await expect(page.getByLabel('Player username')).toBeVisible();
    await expect(page.getByRole('button', { name: /Sync full history/i })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Analyze pasted PGN' })).toBeVisible();
  });

  test('a player with no games gets library puzzles to practice', async ({ page }) => {
    await selectPlayer(page, 'brand_new_empty_player');
    await page.goto('/practice');
    await page.getByRole('button', { name: /Start practice/i }).click();
    await expect(page).toHaveURL(/\/practice\/.+/);
    await expect(page.getByRole('heading', { level: 2, name: /Lichess puzzle/i })).toBeVisible();
    await expect(page.locator('.practice-board')).toBeVisible();
  });
});
