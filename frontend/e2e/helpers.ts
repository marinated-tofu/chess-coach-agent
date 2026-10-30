import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

export const DEMO_PLAYER = 'kfctofu';
export const DEMO_PLATFORM = 'chess.com';
export const FEATURED_GAME_ID = process.env.DEMO_GAME_ID || '82c1948f61d6';

const BACKEND = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8000';

/**
 * Checks that the backend is up and already holds the demo player's analyzed games
 * (no import or sync is started), signs the browser in as the demo player, then installs
 * a visible fake cursor so clicks are easy to follow in the recording. Returns the
 * featured game id.
 */
export async function prepareDemoWorkspace(page: Page, request: APIRequestContext): Promise<string> {
  const health = await request.get(`${BACKEND}/api/health`);
  expect(health.ok(), 'backend /api/health').toBeTruthy();

  const today = await request.get(
    `${BACKEND}/api/today/${DEMO_PLATFORM}/${encodeURIComponent(DEMO_PLAYER)}`,
    { timeout: 60_000 }
  );
  expect(today.ok(), 'backend /api/today').toBeTruthy();
  const summary = await today.json();
  expect(summary.total_games, `${DEMO_PLAYER} has analyzed games`).toBeGreaterThan(0);

  // Warm the slower read-only endpoints so the recording does not sit on loading skeletons.
  const who = `${DEMO_PLATFORM}/${encodeURIComponent(DEMO_PLAYER)}`;
  await Promise.all([
    `${BACKEND}/api/library/${who}/progress`,
    `${BACKEND}/api/progress/${who}`
  ].map((url) => request.get(url, { timeout: 120_000 }).catch(() => null)));

  // The app keeps the player identity in localStorage; a fresh browser context has none and
  // would show the "connect your account" card instead of the Today page.
  await page.addInitScript(([player, platform]) => {
    try {
      localStorage.setItem('chess-coach-player', JSON.stringify({ player, platform }));
    } catch {
      // Storage unavailable: the Today page will show the connect card and the spec fails loudly.
    }
  }, [DEMO_PLAYER, DEMO_PLATFORM] as const);

  await page.addInitScript(() => {
    const install = () => {
      if (document.getElementById('demo-cursor')) return;
      const dot = document.createElement('div');
      dot.id = 'demo-cursor';
      Object.assign(dot.style, {
        position: 'fixed', left: '0px', top: '0px', width: '22px', height: '22px',
        marginLeft: '-11px', marginTop: '-11px', borderRadius: '50%',
        background: 'rgba(255, 196, 0, 0.45)', border: '2px solid rgba(40, 40, 40, 0.85)',
        boxShadow: '0 0 0 3px rgba(255,255,255,0.6)', pointerEvents: 'none',
        zIndex: '2147483647', transition: 'transform 120ms ease', transform: 'scale(1)'
      });
      document.body.appendChild(dot);
      document.addEventListener('mousemove', (event) => {
        dot.style.left = `${event.clientX}px`;
        dot.style.top = `${event.clientY}px`;
      }, true);
      document.addEventListener('mousedown', () => { dot.style.transform = 'scale(0.7)'; }, true);
      document.addEventListener('mouseup', () => { dot.style.transform = 'scale(1)'; }, true);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
    else install();
  });

  return FEATURED_GAME_ID;
}

export async function pause(page: Page, ms = 1400) {
  await page.waitForTimeout(ms);
}

/** Smoothly scrolls the element to the middle of the viewport (or its scroll container). */
export async function smoothScrollTo(locator: Locator, waitMs = 900) {
  // Short timeout so a missing/re-rendered element can't stall the whole recording.
  await locator.evaluate(
    (element) => element.scrollIntoView({ behavior: 'smooth', block: 'center' }),
    undefined,
    { timeout: 10_000 }
  );
  await locator.page().waitForTimeout(waitMs);
}

/** Glides the fake cursor to an element, lingers briefly, then clicks it. */
export async function showClick(locator: Locator, { linger = 450 }: { linger?: number } = {}) {
  const page = locator.page();
  // Smooth-scroll to the target first when it is off screen, so the viewer sees the move.
  const offscreen = await locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return r.top < 0 || r.bottom > window.innerHeight;
  });
  if (offscreen) {
    await locator.evaluate((el) => el.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    await page.waitForTimeout(800);
  }
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
    await page.waitForTimeout(linger);
  }
  await locator.click();
}

/** Types into an input character by character so viewers can read along. */
export async function showType(locator: Locator, text: string, delay = 55) {
  await showClick(locator, { linger: 250 });
  await locator.pressSequentially(text, { delay });
}

/** Clicks a board square by name (works for either orientation). */
export async function clickSquare(page: Page, square: string, scope?: Locator) {
  const root = scope ?? page;
  await showClick(root.locator(`[data-square="${square}"]`).first(), { linger: 250 });
}

/** Plays a move on an interactive board by clicking the from and to squares. */
export async function playBoardMove(page: Page, uci: string, scope?: Locator) {
  await clickSquare(page, uci.slice(0, 2), scope);
  await page.waitForTimeout(350);
  await clickSquare(page, uci.slice(2, 4), scope);
}

/** Desktop sidebar link by its visible label (the label excludes the count badge). */
export function sidebarLink(page: Page, label: string) {
  return page.locator(`.app-sidebar a.nav-link[data-label="${label}"]`);
}

const API_BASE = process.env.PLAYWRIGHT_API_BASE || 'http://127.0.0.1:8000/api';

export async function seedPlayerFromSample(request: APIRequestContext, player = 'kfctofu') {
  const sampleResponse = await request.get(`${API_BASE}/sample`);
  if (!sampleResponse.ok()) throw new Error('Could not load sample PGN');
  const sample = await sampleResponse.json();
  const analyzeResponse = await request.post(`${API_BASE}/analyze`, {
    data: {
      pgn: sample.pgn,
      player,
      platform: 'chess.com',
      max_games: 1
    }
  });
  if (!analyzeResponse.ok()) throw new Error('Could not analyze sample PGN for tests');
  return analyzeResponse.json();
}

export async function syncPlayerAccount(
  request: APIRequestContext,
  username: string,
  platform: 'chess.com' | 'lichess',
  maxGames = 2
) {
  const started = await request.post(`${API_BASE}/games/sync`, {
    data: { username, platform, max_games: maxGames }
  });
  if (!started.ok()) {
    const body = await started.text();
    throw new Error(`Could not start sync for ${username}: ${body}`);
  }
  const job = await started.json();
  const deadline = Date.now() + 240_000;
  let current = job;
  while (!['complete', 'failed'].includes(current.status)) {
    if (Date.now() > deadline) throw new Error(`Sync timed out for ${username}`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const polled = await request.get(`${API_BASE}/games/sync/${current.id}`);
    if (!polled.ok()) throw new Error(`Could not poll sync for ${username}`);
    current = await polled.json();
  }
  if (current.status === 'failed') {
    throw new Error(current.error || `Sync failed for ${username}`);
  }
  const games = await request.get(`${API_BASE}/games/${platform}/${encodeURIComponent(username)}`);
  if (!games.ok()) throw new Error(`Could not load analyzed games for ${username}`);
  return games.json();
}

/** Starts the page with no selected player. The app keeps that choice in localStorage. */
export async function clearBrowserWorkspace(page: Page) {
  await page.addInitScript(() => {
    localStorage.removeItem('chess-coach-player');
  });
}

/** Opens the app with this player already selected. */
export async function selectPlayer(page: Page, player: string, platform: 'chess.com' | 'lichess' = 'chess.com') {
  await page.addInitScript(([name, source]) => {
    localStorage.setItem('chess-coach-player', JSON.stringify({ player: name, platform: source }));
  }, [player, platform] as const);
}
