import { expect, test, type Page } from '@playwright/test';
import { clearBrowserWorkspace, DEMO_PLATFORM, DEMO_PLAYER, seedPlayerFromSample, selectPlayer } from './helpers';

const NOTICE = {
  message: "You've used your 5 notes for today, so this one is the standard version. Your limit resets at midnight UTC.",
  resets_at: new Date(Date.now() + 3_600_000).toISOString()
};

/** The backend's real answer to a POST, with the notice a request at the limit would get. */
async function answerAtLimit(page: Page, url: RegExp) {
  await page.route(url, async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), limit_notice: NOTICE } });
  });
}

test.describe('Daily limit notices', () => {
  test.beforeEach(async ({ page, request }) => {
    await clearBrowserWorkspace(page);
    await seedPlayerFromSample(request, DEMO_PLAYER);
    await selectPlayer(page, DEMO_PLAYER, DEMO_PLATFORM);
  });

  test('a practice session at the limit says so, and the session still runs', async ({ page }) => {
    await answerAtLimit(page, /\/api\/training\/sessions$/);
    await page.goto('/practice');
    await page.getByRole('button', { name: /Start practice/i }).click();
    await expect(page.locator('.limit-notice')).toHaveText(NOTICE.message);
    await expect(page.locator('.practice-board')).toBeVisible();
  });

  test('a practice session that used no limit shows no notice', async ({ page }) => {
    await page.goto('/practice');
    await page.getByRole('button', { name: /Start practice/i }).click();
    await expect(page.locator('.practice-board')).toBeVisible();
    await expect(page.locator('.limit-notice')).toHaveCount(0);
  });

  test('a plan built at the limit keeps its notice after a reload', async ({ page }) => {
    // The demo player may already have this week's plan, so it starts out looking unbuilt.
    const planUrl = /\/api\/study-plan\/[^/]+\/[^/]+(\?.*)?$/;
    let built = false;
    await page.route(planUrl, async (route) => {
      if (built) return route.fallback();
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...await response.json(), plan: null } });
    });
    await answerAtLimit(page, planUrl);
    await page.goto('/');
    const card = page.locator('.plan-card');
    await expect(card.getByRole('button', { name: /Build my week/i })).toBeVisible();
    built = true;
    await card.getByRole('button', { name: /Build my week/i }).click();
    await expect(card.locator('.limit-notice')).toHaveText(NOTICE.message);
    await expect(card.locator('.plan-tasks')).toBeVisible();
    await page.reload();
    await expect(card.locator('.limit-notice')).toHaveText(NOTICE.message);
  });
});
