import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import { FEATURED_GAME_ID } from './helpers';

const ASSETS = join(dirname(fileURLToPath(import.meta.url)), '../../docs/presentation-assets');

test.use({ video: 'off', viewport: { width: 1440, height: 900 } });

async function openFeaturedGame(page: Page) {
  await page.goto('/games');
  const row = page.locator('.game-list button').filter({ hasText: 'sarvesh0801' }).first();
  await expect(row).toBeVisible({ timeout: 60_000 });
  await row.click();
  await expect(page).toHaveURL(new RegExp(`/games/${FEATURED_GAME_ID}`));
  await expect(page.getByText('AI Analysis')).toBeVisible();
}

test('dashboard', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.home-header p')).toContainText('rating', { timeout: 30_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(ASSETS, 'dashboard.png') });
});

test('games', async ({ page }) => {
  await page.goto('/games');
  await expect(page.locator('.game-list button').nth(5)).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(ASSETS, 'games.png') });
});

test('practice', async ({ page }) => {
  test.setTimeout(180_000);
  await openFeaturedGame(page);
  await page.getByRole('button', { name: /Train this position/i }).click();
  await expect(page.locator('.practice-board')).toBeVisible({ timeout: 60_000 });
  const choice = page.locator('.move-choices button').first();
  if (await choice.isVisible().catch(() => false)) await choice.click();
  else {
    await page.getByPlaceholder('Enter SAN or UCI').fill('e4');
    await page.locator('.move-entry').getByRole('button', { name: 'Submit' }).click();
  }
  await expect(page.locator('.evaluation-status')).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(ASSETS, 'practice.png') });
});

test('review', async ({ page }) => {
  test.setTimeout(240_000);
  // Taller than the other shots: the full heatmap board (right) and the coach answer
  // (left, below the analysis) cannot share a 900px-high frame in this layout.
  await page.setViewportSize({ width: 1440, height: 1440 });
  await openFeaturedGame(page);
  await page.getByRole('group', { name: 'Square control heatmap' }).getByRole('button', { name: 'Both', exact: true }).click();
  const coach = page.getByRole('region', { name: 'Chess coach' });
  await coach.getByRole('button', { name: 'What was my biggest mistake in this game?' }).click();
  await expect(coach.locator('.coach-message.coach:not(.pending)')).toHaveCount(1, { timeout: 120_000 });
  await expect(coach.locator('.coach-message.coach:not(.pending)').first()).not.toContainText('unavailable');
  await coach.locator('.coach-thread').evaluate((el) => el.scrollTo({ top: 0 }));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(800);
  // Board+heatmap sit in the right column and the coach below the analysis on the left;
  // scroll so the coach panel bottom meets the viewport bottom, which keeps the lower
  // board ranks, the heatmap controls/legend and the coach answer in one 1440x900 frame.
  await coach.evaluate((el) => {
    const bottom = el.getBoundingClientRect().bottom + window.scrollY;
    window.scrollTo({ top: Math.max(0, bottom + 16 - window.innerHeight) });
  });
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(ASSETS, 'review.png') });
});
