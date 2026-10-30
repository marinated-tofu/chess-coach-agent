import { expect, test, type Page } from '@playwright/test';
import { clearBrowserWorkspace, seedPlayerFromSample, selectPlayer } from './helpers';

// A plan is built once per player, so each run needs its own.
const PLAYER = `parity_e2e_${Date.now()}`;

/** Records uncaught page errors, so a refused request that crashes a page fails the test. */
function trackPageErrors(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

/**
 * Answers every player-specific request the way the API does for a claimed player and a
 * visitor without access. Claiming a player for real needs a signed session cookie, so the
 * refusal itself is covered by backend tests and this spec covers what the page does with it.
 */
async function refusePrivatePlayer(page: Page) {
  const refuse = (route: import('@playwright/test').Route) => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: "This player's practice data is private. Sign in to open it." })
  });
  await page.route(/\/api\/study-plan\//, refuse);
  await page.route(/\/api\/repertoire/, refuse);
  await page.route(/\/api\/training\/sessions/, refuse);
  await page.route(/\/api\/(puzzles|endgames)\?.*username=/, refuse);
}

test.describe('Parity pages', () => {
  test('Today builds the weekly plan and keeps it after a reload', async ({ page, request }) => {
    const errors = trackPageErrors(page);
    await seedPlayerFromSample(request, PLAYER);
    await selectPlayer(page, PLAYER);

    await page.goto('/');
    await page.getByRole('button', { name: 'Build my week' }).click();
    await expect(page.getByText(/\d+ of \d+ done/)).toBeVisible();

    await page.reload();
    await expect(page.getByText(/\d+ of \d+ done/)).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('a puzzle can be revealed', async ({ page }) => {
    const errors = trackPageErrors(page);
    await clearBrowserWorkspace(page);

    await page.goto('/puzzles');
    await expect(page.getByRole('heading', { name: 'Solve by theme and rating' })).toBeVisible();
    await page.getByRole('button', { name: 'Show solution' }).click();
    await expect(page.getByRole('button', { name: 'Next puzzle' })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('an endgame drill reaches a result', async ({ page }) => {
    const errors = trackPageErrors(page);
    await clearBrowserWorkspace(page);

    await page.goto('/endgames');
    await page.getByRole('button', { name: 'Start drill' }).click();
    await page.getByRole('button', { name: 'Give up' }).click();
    await page.getByRole('button', { name: /Confirm/ }).click();
    await expect(page.getByText('Not this time')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('account page invites a visitor to sign in', async ({ page }) => {
    await clearBrowserWorkspace(page);
    await page.goto('/account');
    await expect(page.getByRole('heading', { name: 'Keep your practice private' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sign in with Lichess' }).first()).toBeVisible();
    await expect(page.getByText(/coach questions? left today/)).toBeVisible();
  });
});

test.describe('A player who belongs to someone else', () => {
  test.beforeEach(async ({ page, request }) => {
    await seedPlayerFromSample(request, PLAYER);
    await selectPlayer(page, PLAYER);
    await refusePrivatePlayer(page);
  });

  test('every page explains itself instead of failing', async ({ page }) => {
    const errors = trackPageErrors(page);

    await page.goto('/');
    await expect(page.getByText("This player's plan is private.")).toBeVisible();

    await page.goto('/repertoire');
    await expect(page.getByRole('heading', { name: "This player's practice is private" })).toBeVisible();

    await page.goto('/practice/any-session');
    await expect(page.getByRole('heading', { name: "This player's practice is private" })).toBeVisible();

    await page.goto('/practice');
    await page.getByRole('button', { name: /Start practice/i }).click();
    await expect(page.getByRole('alert')).toContainText('private');

    await page.goto('/endgames');
    await expect(page.getByRole('button', { name: 'Start drill' })).toBeVisible();
    await page.getByRole('button', { name: 'Start drill' }).click();
    await page.getByRole('button', { name: 'Give up' }).click();
    await page.getByRole('button', { name: /Confirm/ }).click();
    await expect(page.getByText(/so this result isn't saved/)).toBeVisible();

    expect(errors).toEqual([]);
  });

  test('puzzles stay open without saving results', async ({ page }) => {
    const errors = trackPageErrors(page);

    await page.goto('/puzzles');
    await page.getByRole('button', { name: 'Show solution' }).click();
    await expect(page.getByRole('button', { name: 'Next puzzle' })).toBeVisible();
    await expect(page.getByText(/private/).first()).toBeVisible();
    expect(errors).toEqual([]);
  });
});
