import { expect, test } from '@playwright/test';
import { clearBrowserWorkspace, seedPlayerFromSample, syncPlayerAccount } from './helpers';

const SECOND_PLAYER_CANDIDATES = [
  { username: 'DrNykterstein', platform: 'lichess' as const, label: 'DrNykterstein (Lichess)' },
  { username: 'Hikaru', platform: 'lichess' as const, label: 'Hikaru (Lichess)' },
  { username: 'MagnusCarlsen', platform: 'chess.com' as const, label: 'MagnusCarlsen (Chess.com)' }
];

async function syncSecondPlayer(request: import('@playwright/test').APIRequestContext) {
  let lastError = 'No candidate succeeded';
  for (const candidate of SECOND_PLAYER_CANDIDATES) {
    try {
      const payload = await syncPlayerAccount(request, candidate.username, candidate.platform, 1);
      if (payload.analyses.length > 0) {
        return candidate;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
  }
  test.skip(true, `Live account sync unavailable in this environment: ${lastError}`);
  return SECOND_PLAYER_CANDIDATES[0];
}

test.describe('Account sync players', () => {
  test.beforeEach(async ({ page }) => {
    await clearBrowserWorkspace(page);
  });

  test('kfctofu games load from synced account data', async ({ page, request }) => {
    await seedPlayerFromSample(request, 'kfctofu');
    await page.goto('/games');
    await expect(page.getByRole('heading', { name: 'Your analyzed games' })).toBeVisible();
    await expect(page.getByText(/games ready/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Analyze pasted PGN')).toHaveCount(0);
  });

  test('second titled account loads after kfctofu', async ({ page, request }) => {
    test.setTimeout(300_000);
    await seedPlayerFromSample(request, 'kfctofu');
    const second = await syncSecondPlayer(request);

    await page.goto('/games');
    await page.getByRole('button', { name: /Import games/i }).click();
    await page.getByLabel('Player username').fill(second.username);
    await page.getByLabel('Source').selectOption(second.platform);
    await page.getByRole('button', { name: /Sync full history/i }).click();
    await expect(page.getByText(/Synced|skipped|analyzed/i)).toBeVisible({ timeout: 120_000 });

    await page.getByRole('link', { name: 'Home' }).click();
    await expect(page.getByRole('heading', { name: second.username })).toBeVisible();

    await page.getByRole('link', { name: 'Practice' }).click();
    await page.getByRole('button', { name: /Start practice/i }).click();
    const practiceHeading = page.getByRole('heading', { level: 2, name: /what would you play|pattern in your game/i });
    const emptyState = page.getByRole('heading', { name: 'No positions due' });
    await expect(practiceHeading.or(emptyState)).toBeVisible({ timeout: 30_000 });
  });
});
