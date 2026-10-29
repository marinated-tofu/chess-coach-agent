import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { Chess } from 'chess.js';
import {
  pause,
  playBoardMove,
  prepareDemoWorkspace,
  showClick,
  showType,
  sidebarLink,
  smoothScrollTo
} from './helpers';

const DEMO_VIDEO = join(
  dirname(fileURLToPath(import.meta.url)),
  '../../docs/demo-walkthrough.webm'
);

// The coach runs an LLM plus Stockfish tools; the CPU may be busy with background analysis.
const BACKEND = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8000';
const LLM_TIMEOUT = 150_000;
// Set DEMO_BUILD_REPERTOIRE=1 to build a repertoire from the player's games during the tour
// (this writes to the database). By default the tour only shows the page.
const BUILD_REPERTOIRE = process.env.DEMO_BUILD_REPERTOIRE === '1';
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
  await expect(answer.locator('.coach-meta')).not.toContainText('Offline answer');
  return answer;
}

/** Scrolls the window back to the top so the next sidebar click starts from a clean frame. */
async function scrollTop(page: Page, ms = 700) {
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await pause(page, ms);
}

async function goTo(page: Page, label: string, heading: string | RegExp) {
  await scrollTop(page, 500);
  await showClick(sidebarLink(page, label));
  await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible({ timeout: 30_000 });
}

/** A legal move for the side to move, preferring captures and checks so the grading has something to say. */
function pickMove(fen: string): string {
  const board = new Chess(fen);
  const moves = board.moves({ verbose: true });
  const pick = moves.find((move) => move.san.includes('+')) ?? moves.find((move) => move.captured) ?? moves[0];
  return pick.from + pick.to + (pick.promotion ?? '');
}

/** Stockfish's top move for the position (the backend engine endpoint), or null if it is unavailable. */
async function bestMove(request: APIRequestContext, fen: string): Promise<string | null> {
  const response = await request.post(`${BACKEND}/api/engine/analyze`, {
    data: { fen, multipv: 1 },
    timeout: 60_000
  }).catch(() => null);
  if (!response?.ok()) return null;
  const body = await response.json();
  return body.lines?.[0]?.move_uci ?? null;
}

async function glide(page: Page, target: Locator) {
  const box = await target.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 20 });
}

test.describe('Demo walkthrough', () => {
  test('record product tour', async ({ page, request }) => {
    test.setTimeout(600_000);
    started = Date.now();
    const featuredGameId = await prepareDemoWorkspace(page, request);

    try {
      // 1. Today
      mark('Today page');
      await page.goto('/');
      await expect(page.locator('.page-header .page-eyebrow')).toHaveText('Today');
      await expect(page.locator('.page-header p')).toContainText('games', { timeout: 60_000 });
      await expect(page.getByRole('heading', { name: 'Due reviews' })).toBeVisible();
      await expect(page.locator('.today-card-stat').first()).toBeVisible({ timeout: 60_000 });
      await pause(page, 2000);
      for (const title of ['Due reviews', 'Latest game', 'Top leak']) {
        await glide(page, page.getByRole('heading', { name: title, level: 2 }));
        await pause(page, 1300);
      }

      // 2. Games library with filters
      mark('Games library');
      await goTo(page, 'Games', 'Your analyzed games');
      await expect(page.locator('.library-row').nth(5)).toBeVisible({ timeout: 60_000 });
      await pause(page, 1800);

      mark('Library filters');
      const filters = page.getByRole('region', { name: 'Filter games' });
      await showClick(filters.getByRole('group', { name: 'Result' }).getByRole('button', { name: /^Losses/ }));
      await expect(page.locator('.page-header p')).toContainText('match', { timeout: 30_000 });
      await pause(page, 1600);
      const speeds = filters.getByRole('group', { name: 'Time control' });
      await showClick(speeds.getByRole('button', { name: /^Blitz/ }));
      await pause(page, 1600);
      await showClick(filters.getByRole('group', { name: 'Color' }).getByRole('button', { name: /^As Black/ }));
      await pause(page, 1600);
      await showClick(filters.getByRole('button', { name: 'Clear filters' }));
      await pause(page, 1200);

      mark('Search by opponent');
      await showType(filters.getByPlaceholder('Search by opponent'), 'sarvesh0801', 70);
      const featuredRow = page.locator(`a.library-row[href*="/games/${featuredGameId}"]`);
      await expect(featuredRow).toBeVisible({ timeout: 30_000 });
      await pause(page, 1400);

      // 3. Game review
      mark('Game review');
      await showClick(featuredRow);
      await expect(page).toHaveURL(new RegExp(`/games/${featuredGameId}`));
      await expect(page.getByRole('heading', { name: 'Key moments' })).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole('link', { name: 'All games' })).toBeVisible();
      await expect(page.getByRole('region', { name: 'Game review summary' })).toBeVisible();
      await pause(page, 2600);

      for (const label of ['Moment 1', 'Moment 2', 'Moment 3']) {
        const button = page.getByRole('button', { name: new RegExp(`^${label}(:|$)`) });
        if (!(await button.count())) break;
        mark(`Key moment: ${label}`);
        await showClick(button);
        await pause(page, 2000);
      }
      await smoothScrollTo(page.getByRole('heading', { name: 'What happened' }), 2200);
      await scrollTop(page, 700);

      mark('Step through moves');
      const nextMove = page.getByRole('button', { name: 'Next move' });
      const prevMove = page.getByRole('button', { name: 'Previous move' });
      for (const button of [prevMove, prevMove, nextMove, nextMove]) {
        await showClick(button, { linger: 250 });
        await pause(page, 800);
      }

      mark('Moves tab: eval graph and move list');
      await showClick(page.getByRole('tab', { name: 'Moves' }));
      await pause(page, 2200);

      mark('Square-control heatmap');
      const heatmap = page.getByRole('group', { name: 'Square control heatmap' });
      const both = heatmap.getByRole('button', { name: 'Both', exact: true });
      await showClick(both);
      await expect(both).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('.heatmap-legend')).toContainText('Strongest');
      await pause(page, 1400);
      await page.getByRole('img', { name: /square control heatmap/ }).first()
        .evaluate((el) => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), undefined, { timeout: 10_000 });
      await pause(page, 2400);
      await showClick(heatmap.getByRole('button', { name: 'Off', exact: true }));
      await pause(page, 900);

      mark('More actions menu');
      await scrollTop(page, 600);
      const more = page.getByLabel('More actions');
      await showClick(more);
      await expect(page.getByRole('menuitem', { name: 'Export PGN' })).toBeVisible();
      await pause(page, 1600);
      await showClick(more);
      await pause(page, 600);

      // 4. Coach
      mark('Coach panel');
      await showClick(page.getByRole('tab', { name: 'Coach' }));
      const coach = page.getByRole('region', { name: 'Chess coach' });
      await expect(coach).toBeVisible();
      await pause(page, 1000);
      await showClick(coach.getByRole('button', { name: 'What was my biggest mistake in this game?' }));
      mark('Coach thinking');
      const answer = await waitForCoachAnswer(page, 1);
      mark('Coach answer');
      await smoothScrollTo(answer.locator('p').first(), 2800);
      await smoothScrollTo(answer.locator('.coach-facts'), 2600);
      const evidence = answer.locator('details.coach-evidence');
      if (await evidence.count()) {
        mark('Coach evidence');
        await smoothScrollTo(evidence, 500);
        await showClick(evidence.locator('summary'));
        await smoothScrollTo(evidence, 3000);
      }

      // 5. Practice: home, start, answer, Stockfish grading
      mark('Practice home');
      await goTo(page, 'Practice', 'Train mistakes from your games');
      await expect(page.locator('.practice-queue-counts strong').first()).not.toHaveText('–', { timeout: 60_000 });
      await pause(page, 2400);
      await glide(page, page.getByRole('button', { name: 'Themed puzzles' }));
      await pause(page, 1000);

      mark('Start practice');
      const sessionResponse = page.waitForResponse(
        (response) => /\/api\/training\/sessions\/[^/]+$/.test(new URL(response.url()).pathname)
          && response.request().method() === 'GET',
        { timeout: 60_000 }
      );
      await showClick(page.getByRole('button', { name: 'Start practice' }));
      await expect(page).toHaveURL(/\/practice\/.+/, { timeout: 60_000 });
      const session = await (await sessionResponse).json();
      await expect(page.getByRole('heading', { name: 'What would you play?' })).toBeVisible({ timeout: 60_000 });
      await pause(page, 2200);

      mark('Answer practice move');
      const choices = page.getByRole('group', { name: 'Candidate moves' });
      if (await choices.isVisible().catch(() => false)) {
        await showClick(choices.getByRole('button').first());
      } else {
        const fen: string = session.positions[0].fen;
        await playBoardMove(page, (await bestMove(request, fen)) ?? pickMove(fen), page.locator('.practice-board'));
      }
      await expect(page.locator('.evaluation-status')).toBeVisible({ timeout: 90_000 });
      mark('Stockfish grading');
      await smoothScrollTo(page.locator('.evaluation-status'), 3600);

      // 6. Progress
      mark('Progress');
      await goTo(page, 'Progress', 'Progress');
      await pause(page, 1500);
      const ratingChart = page.getByRole('heading', { name: 'Rating over time' });
      await expect(page.locator('.progress-chart .recharts-surface').first()).toBeVisible({ timeout: 90_000 });
      await smoothScrollTo(ratingChart, 1800);
      const toggle = page.getByRole('group', { name: 'Time control' });
      if (await toggle.count()) {
        const buttons = toggle.getByRole('button');
        // End on the first (busiest) time control so the chart finishes on a real rating curve.
        const n = await buttons.count();
        for (const i of n > 1 ? [1, 0] : []) {
          await showClick(buttons.nth(i));
          await pause(page, 1800);
        }
      }
      const blindspots = page.getByRole('heading', { name: 'Recurring blindspots' });
      if (await blindspots.count()) await smoothScrollTo(blindspots, 2200);

      // 7. Insights
      mark('Insights');
      await goTo(page, 'Insights', 'Where you lose points');
      await expect(page.getByRole('heading', { name: 'Biggest leaks' })).toBeVisible({ timeout: 90_000 });
      await pause(page, 2600);
      await smoothScrollTo(page.getByRole('heading', { name: 'By game phase' }), 2400);
      const byTime = page.getByRole('heading', { name: 'By time control' });
      if (await byTime.count()) await smoothScrollTo(byTime, 2200);
      const byRating = page.getByRole('heading', { name: 'By opponent rating' });
      if (await byRating.count()) await smoothScrollTo(byRating, 2200);

      // 8. Play a bot
      mark('Play bots');
      await goTo(page, 'Play bots', 'Play a bot');
      const bots = page.getByRole('region', { name: 'Choose a bot' });
      await expect(bots.locator('.play-bot-card:not(.skeleton)').first()).toBeVisible({ timeout: 30_000 });
      await pause(page, 1800);
      const sparring = bots.locator('.play-bot-card').filter({ hasText: 'Your opponents' }).first();
      if (await sparring.count()) {
        mark('Sparring partner');
        await showClick(sparring);
        await expect(page.locator('.play-sparring-hint')).toBeVisible();
        await pause(page, 2200);
      }
      const mara = bots.getByRole('button', { name: /Mara/ });
      await showClick(mara);
      await pause(page, 900);
      mark('Start game vs Mara');
      await showClick(page.getByRole('button', { name: 'Play Mara' }));
      const playBoard = page.locator('.play-board');
      await expect(playBoard).toBeVisible();
      await pause(page, 1200);
      await playBoardMove(page, 'e2e4', playBoard);
      await expect(page.locator('.play-moves li')).toHaveCount(1, { timeout: 30_000 });
      // Wait for the bot's reply (row 1 holds both moves).
      await expect(page.locator('.play-moves li').first().locator('span').nth(2)).not.toHaveText('', { timeout: 60_000 });
      await pause(page, 1500);
      await playBoardMove(page, 'g1f3', playBoard);
      await expect(page.locator('.play-moves li').nth(1).locator('span').nth(2)).not.toHaveText('', { timeout: 60_000 });
      mark('Bot replied');
      await pause(page, 2400);

      // 9. Analysis board and opening explorer
      mark('Analysis board');
      await goTo(page, 'Analysis board', 'Explore any position');
      const analysisBoard = page.locator('.analysis-board-column');
      await pause(page, 1600);
      await playBoardMove(page, 'e2e4', analysisBoard);
      await pause(page, 1200);
      await playBoardMove(page, 'c7c5', analysisBoard);
      await expect(page.getByRole('region', { name: 'Engine' })).toBeVisible();
      await pause(page, 2600);

      mark('Opening explorer');
      const explorer = page.getByRole('region', { name: 'Opening explorer' });
      await smoothScrollTo(explorer, 1400);
      await expect(explorer.locator('.explorer-opening')).toContainText(/Sicilian/i, { timeout: 30_000 });
      await pause(page, 2200);
      // Masters and Lichess tabs need a Lichess API token on the backend, so stay on "Your games".
      const asWhite = explorer.getByRole('radiogroup', { name: 'Games where you played' }).getByRole('radio', { name: 'White' });
      if (await asWhite.count()) {
        await showClick(asWhite);
        await pause(page, 2400);
      }
      await glide(page, explorer.locator('.explorer-table button').first());
      await pause(page, 1800);

      // 10. Repertoire
      mark('Repertoire');
      await goTo(page, 'Repertoire', 'Repertoire');
      await pause(page, 2400);
      const buildButton = page.getByRole('button', { name: 'Build from my games' });
      if (BUILD_REPERTOIRE && await buildButton.isVisible().catch(() => false)) {
        mark('Build repertoire');
        await showClick(buildButton);
        await expect(page.getByRole('region', { name: 'Repertoire lines' })).toBeVisible({ timeout: 120_000 });
        await pause(page, 3000);
      } else {
        await showClick(page.getByRole('group', { name: 'Repertoire color' }).getByRole('button', { name: 'Black' }));
        await pause(page, 2000);
      }

      // 11. Quality monitoring
      mark('Quality monitoring');
      await scrollTop(page, 400);
      await showClick(page.locator('.app-sidebar').getByRole('link', { name: 'Developer: quality' }));
      await expect(page.getByRole('heading', { level: 1, name: 'Quality monitoring' })).toBeVisible();
      await pause(page, 2800);
      await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight / 2, behavior: 'smooth' }));
      await pause(page, 2000);

      // 12. Back to Today
      mark('Back to Today');
      await goTo(page, 'Today', /.+/);
      await expect(page.locator('.page-header .page-eyebrow')).toHaveText('Today');
      await pause(page, 2800);
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
