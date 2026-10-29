import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import { pause, prepareDemoWorkspace, showClick, showType, smoothScrollTo } from './helpers';

const DEMO_VIDEO = join(
  dirname(fileURLToPath(import.meta.url)),
  '../../docs/demo-walkthrough.webm'
);

const LLM_TIMEOUT = 90_000;
const marks: Array<{ t: number; label: string }> = [];
let started = 0;

function mark(label: string) {
  const t = (Date.now() - started) / 1000;
  marks.push({ t, label });
  console.log(`[demo ${t.toFixed(1)}s] ${label}`);
}

async function waitForCoachAnswer(page: Page, count: number) {
  const coach = page.getByRole('region', { name: 'Chess coach' });
  await expect(coach.locator('.coach-message.coach.pending')).toBeVisible({ timeout: 10_000 }).catch(() => undefined);
  await expect(coach.locator('.coach-message.coach:not(.pending)')).toHaveCount(count, { timeout: LLM_TIMEOUT });
  await expect(coach.locator('.coach-error')).toHaveCount(0);
  const answer = coach.locator('.coach-message.coach:not(.pending)').nth(count - 1);
  // Fail loudly instead of recording the offline fallback answer.
  await expect(answer).not.toContainText('coach model is unavailable');
  return answer;
}

test.describe('Demo walkthrough', () => {
  test('record product tour', async ({ page, request }) => {
    test.setTimeout(480_000);
    started = Date.now();
    const featuredGameId = await prepareDemoWorkspace(page, request);

    try {
      // 1. Home dashboard
      mark('Home dashboard');
      await page.goto('/');
      await expect(page.getByRole('heading', { level: 1, name: 'kfctofu' })).toBeVisible();
      await expect(page.locator('.home-header p')).toContainText('rating', { timeout: 30_000 });
      await pause(page, 2600);
      await page.mouse.move(700, 500, { steps: 15 });
      await smoothScrollTo(page.locator('.focus-metrics'), 2400);

      // 2. Games library + import panel
      mark('Games library');
      await showClick(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Games' }));
      await expect(page.getByRole('heading', { name: 'Your analyzed games' })).toBeVisible();
      await expect(page.locator('.game-list button').nth(1)).toBeVisible({ timeout: 60_000 });
      await pause(page, 2000);

      mark('Import games panel');
      await showClick(page.getByRole('button', { name: 'Import games' }));
      await expect(page.getByText('Player history')).toBeVisible();
      await pause(page, 1500);
      await smoothScrollTo(page.locator('.pgn-import'), 2200);
      await showClick(page.getByRole('button', { name: 'Close import' }));
      await expect(page.locator('.game-intake')).toHaveCount(0);
      await pause(page, 1200);

      // 3. Game review
      mark('Game review: AI analysis');
      const featuredRow = page.locator('.game-list button').filter({ hasText: 'sarvesh0801' }).first();
      await showClick(featuredRow);
      await expect(page).toHaveURL(new RegExp(`/games/${featuredGameId}`));
      await expect(page.getByText('AI Analysis')).toBeVisible();
      await pause(page, 2600);

      for (const label of ['Moment 1', 'Moment 2', 'Moment 3']) {
        mark(`Switch to ${label}`);
        // Accessible name may be "Moment 1" or "Moment 1: 5. Nf3, blunder".
        await showClick(page.getByRole('button', { name: new RegExp(`^${label}(:|$)`) }));
        await pause(page, 2200);
      }

      mark('Step through moves');
      const nextMove = page.getByRole('button', { name: 'Next move' });
      const prevMove = page.getByRole('button', { name: 'Previous move' });
      await showClick(prevMove);
      await pause(page, 900);
      await showClick(prevMove);
      await pause(page, 900);
      await showClick(nextMove);
      await pause(page, 900);
      await showClick(nextMove);
      await pause(page, 1400);

      // 4. Square-control heatmap
      mark('Square-control heatmap');
      const heatmap = page.getByRole('group', { name: 'Square control heatmap' });
      // Keep the whole board plus the heatmap controls in frame.
      await page.locator('.heatmap-bar').evaluate((el) => el.scrollIntoView({ behavior: 'smooth', block: 'end' }));
      await pause(page, 1000);
      for (const label of ['You', 'Opponent', 'Both']) {
        mark(`Heatmap: ${label}`);
        const button = heatmap.getByRole('button', { name: label, exact: true });
        await showClick(button);
        await expect(button).toHaveAttribute('aria-pressed', 'true');
        await expect(page.locator('.heatmap-legend')).toContainText('Strongest');
        await pause(page, 2600);
      }

      mark('Flip board');
      await showClick(page.getByRole('button', { name: 'Flip board' }));
      await pause(page, 2400);
      await showClick(page.getByRole('button', { name: 'Flip board' }));
      await pause(page, 1200);

      mark('Heatmap: Off');
      await showClick(heatmap.getByRole('button', { name: 'Off', exact: true }));
      await pause(page, 1600);

      // 5. Coach panel on review page
      mark('Coach panel (review)');
      const coach = page.getByRole('region', { name: 'Chess coach' });
      await smoothScrollTo(coach, 1400);
      await showClick(coach.getByRole('button', { name: 'What was my biggest mistake in this game?' }));
      mark('Coach thinking (question 1)');
      const firstAnswer = await waitForCoachAnswer(page, 1);
      mark('Coach answer 1');
      await smoothScrollTo(firstAnswer.locator('p').first(), 2600);
      await smoothScrollTo(firstAnswer.locator('.coach-facts'), 2600);
      const evidence = firstAnswer.locator('details.coach-evidence');
      if (await evidence.count()) {
        mark('Expand evidence');
        await smoothScrollTo(evidence, 600);
        await showClick(evidence.locator('summary'));
        await smoothScrollTo(evidence, 2800);
      }

      mark('Follow-up question');
      const questionInput = coach.getByLabel('Question for the coach');
      await smoothScrollTo(questionInput, 600);
      await showType(questionInput, 'Give me a drill for this weakness');
      await pause(page, 500);
      await showClick(coach.getByRole('button', { name: 'Send question' }));
      const secondAnswer = await waitForCoachAnswer(page, 2);
      mark('Coach answer 2');
      await smoothScrollTo(secondAnswer.locator('p').first(), 2600);
      await smoothScrollTo(secondAnswer.locator('.coach-facts'), 2800);

      // 6. Practice from this position
      mark('Train this position');
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
      await pause(page, 900);
      await showClick(page.getByRole('button', { name: /Train this position/i }));
      await expect(page).toHaveURL(/\/practice\/.+/, { timeout: 60_000 });
      await expect(page.locator('.practice-board')).toBeVisible({ timeout: 60_000 });
      await pause(page, 2400);

      mark('Answer practice move');
      const moveChoice = page.locator('.move-choices button').first();
      if (await moveChoice.isVisible().catch(() => false)) {
        await showClick(moveChoice);
      } else {
        const entry = page.getByPlaceholder('Enter SAN or UCI');
        await showType(entry, 'e4', 120);
        await showClick(page.locator('.move-entry').getByRole('button', { name: 'Submit' }));
      }
      await expect(page.locator('.evaluation-status')).toBeVisible({ timeout: 60_000 });
      mark('Stockfish grading');
      await smoothScrollTo(page.locator('.evaluation-status'), 3200);

      mark('Coach panel (practice hint)');
      const practiceCoach = page.getByRole('region', { name: 'Chess coach' });
      await smoothScrollTo(practiceCoach, 1200);
      await showClick(practiceCoach.getByRole('button', { name: 'Give me a hint without telling me the move' }));
      const hint = await waitForCoachAnswer(page, 1);
      mark('Coach hint answer');
      await smoothScrollTo(hint.locator('p').first(), 2600);
      await smoothScrollTo(hint.locator('.coach-facts'), 2800);

      // 7. Practice home, Progress, Quality
      mark('Practice home');
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
      await pause(page, 800);
      const nav = page.getByRole('navigation', { name: 'Primary navigation' });
      await showClick(nav.getByRole('link', { name: 'Practice' }));
      await expect(page.getByRole('heading', { name: 'Train mistakes from your games' })).toBeVisible();
      await pause(page, 2400);

      mark('Progress page');
      await showClick(nav.getByRole('link', { name: 'Progress' }));
      await expect(page.getByRole('heading', { name: 'Progress', level: 1 })).toBeVisible();
      await pause(page, 2600);
      const blindspots = page.getByRole('heading', { name: 'Recurring blindspots' });
      if (await blindspots.count()) await smoothScrollTo(blindspots, 2400);

      mark('Quality monitoring');
      // No sidebar link for /quality: navigate client-side so the in-memory workspace
      // (all analyzed games) survives; fall back to a full load if the router ignores it.
      await page.evaluate(() => {
        window.history.pushState({}, '', '/quality');
        window.dispatchEvent(new PopStateEvent('popstate', { state: {} }));
      });
      const qualityHeading = page.getByRole('heading', { name: 'Quality monitoring' });
      if (!(await qualityHeading.isVisible({ timeout: 5_000 }).catch(() => false))) await page.goto('/quality');
      await expect(qualityHeading).toBeVisible();
      await pause(page, 2800);
      await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight / 2, behavior: 'smooth' }));
      await pause(page, 2400);

      // 8. Back home
      mark('Back to Home');
      await showClick(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('link', { name: 'Home' }));
      await expect(page.getByRole('heading', { level: 1, name: 'kfctofu' })).toBeVisible();
      await pause(page, 2600);
      mark('End');
    } finally {
      console.log('DEMO_MARKS ' + JSON.stringify(marks));
      const video = page.video();
      await page.close();
      if (video) {
        mkdirSync(dirname(DEMO_VIDEO), { recursive: true });
        await video.saveAs(DEMO_VIDEO);
      }
    }
  });
});
