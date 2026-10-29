# UX plan

Audit date: 2026-10-29. Walked every route at 1440x900 and 390x844 against a local backend
(port 8014, Vite 5194) as `kfctofu` on Chess.com (2,777 stored games) and as a new username with
no games. Nine feature branches were landing during the audit, so `PlayPage.tsx`,
`RepertoirePage.tsx`, `OpeningExplorer.tsx`, `AccountButton.tsx` and PGN export existed as files
but Play, Repertoire and Setup had no routes yet. The plan assumes they land with the route names
below. Execute this after the feature work merges.

Reference flows used for structure only (no code copied): Lichess top nav (Play, Puzzles, Learn,
Watch, Community, Tools; Tools = Analysis board, Openings, Board editor, Import game) and its
analysis keyboard map (`ui/analyse/src/keyboard.ts`: arrows/j/k to step, `f` flip, `?` help);
Chess.com Game Review (summary, then key moments, then retry).

---

## 1. Top problems, ranked

| # | Problem | Where | Impact |
| --- | --- | --- | --- |
| P0 | The games library downloads every analysis in full: `GET /api/games/chess.com/kfctofu` returned 74.5 MB in 3.9 s and renders 2,777 buttons inside a 235 px tall scroll box | `/games` | Slowest screen in the app; on a phone it is a 300 px box inside a scrolling page |
| P0 | A new visitor lands on someone else's profile: Home shows `kfctofu` (the sample player) with "Continue training". There is no way to set your own username from Home | `/` | First run never asks who you are |
| P0 | `/games` shows "No games yet" plus an "Import games" button while the header says "Loading your game library..." | `/games` | Tells a user with 2,777 games they have none |
| P1 | Review page puts the board below the fold (board top at y=530 on desktop, y=650 on mobile). The coach answer is ~3,000 px below the board on mobile, so its board arrows are never seen with the text | `/games/$id` | Breaks the core review loop |
| P1 | Two labels for one move: move list says Nf3 "Miss", the moment card says "Blunder" | `/games/$id` | Users stop trusting the labels |
| P1 | Rating on Home changes on every load (771, 764, 528, 723 in one session; API `current_rating` returned 458, 439, 426 on three calls). Rating chart mixes time controls and zig-zags | `/`, `/progress` | Looks broken |
| P1 | Mobile tab bar has 6 equal items at 11 px; Sign in with Lichess is hidden on mobile entirely; new Play / Repertoire / Setup pages have no slot | shell | Nav does not scale |
| P2 | Several views have two or three green primary buttons doing similar things (Home: "Continue training" and "Start practice" call the same function; Insights: three "Practice..." primaries) | `/`, `/insights`, `/games/$id` | No clear next step |
| P2 | Sync progress is only visible on `/games?import=true`; leave the page and you lose it. No completion signal | sync | Users re-click sync |
| P2 | Six local palettes (`--rv-*`, `--insights-*`, `--openings-*`, plus 169 raw hex values in `styles.css`), no dark mode, 14 different font sizes | all | Drift between pages |

---

## 2. Information architecture

### Routes and labels

| Group | Label | Route | Notes |
| --- | --- | --- | --- |
| (top) | Today | `/` | Dashboard for returning users, connect flow for new ones |
| Review | Games | `/games`, `/games/$gameId` | Import moves into a sheet on this page (`?import=1`) |
| Review | Insights | `/insights` | |
| Review | Progress | `/progress` | Rating chart split by time control |
| Train | Practice | `/practice`, `/practice/$sessionId` | Own-mistake drills |
| Train | Puzzles | `/puzzles` | Themed Lichess puzzles; today a button on Practice ("Themed puzzles"). Route can reuse `PracticePage` with `mode=puzzles` |
| Train | Repertoire | `/repertoire` | Builder and drill |
| Play | Play bots | `/play` | Human-like bots |
| Tools | Analysis board | `/analysis?fen=` | |
| Tools | Opening explorer | `/analysis?tab=explorer` | Explorer lives inside the analysis page; the nav item deep-links to its tab |
| Tools | Set up position | `/setup` | Screenshot import and editor |
| Footer | Account | (button) | `AccountButton`: Sign in with Lichess, or current username + switch |
| Footer | Quality | `/quality` | Small text link "Developer: quality", not a nav item |

Keep the existing redirects (`/analyze` to `/games?import=1`, `/coach*` to `/practice`).

### Desktop sidebar (>= 1024 px)

Sidebar stays 214 px, dark. Order: brand, Today, then four labelled groups with 11 px uppercase
group headings (Review, Train, Play, Tools). Footer: account block, then the "Developer: quality"
link. Games keeps its count badge; Practice gets a "due" count badge (from `due_positions`) instead
of Games' raw total. Badge counts use `tabular-nums`. The sidebar scrolls on its own if it ever
exceeds the viewport (`overflow-y: auto; height: 100dvh`).

Between 721 and 1023 px collapse the sidebar to a 64 px icon rail with tooltips (labels via
`aria-label`), group headings become 1 px dividers.

### Mobile (<= 720 px): bottom tab bar + More sheet

Five tabs, 49 px tall plus `env(safe-area-inset-bottom)`, labels 11 px, icons 22 px:

1. Today `/`
2. Games `/games`
3. Train `/practice` (badge = due count)
4. Play `/play`
5. More: opens a bottom sheet with the remaining items grouped exactly like the desktop groups
   (Insights, Progress, Puzzles, Repertoire, Analysis board, Opening explorer, Set up position),
   then the account block and the Quality link.

The More tab shows as active when the current route lives inside the sheet. The sheet: max-height
`85dvh`, `overscroll-behavior: contain`, padding-bottom `calc(16px + env(safe-area-inset-bottom))`,
closes on Escape, backdrop tap and route change; focus moves into it on open and back to the More
button on close. Enter/exit: `transform: translateY(100%)` to `0`, 240 ms
`cubic-bezier(0.32, 0.72, 0, 1)`; reduced motion swaps to a 150 ms opacity fade. Requires
`viewport-fit=cover` in `index.html` or the insets are 0.

---

## 3. First run and Today dashboard

### New user (no stored identity, or identity with 0 games)

Stop defaulting `player` to `kfctofu` / the sample player in `WorkspaceContext`. Without an
identity, `/` renders one card and nothing else:

- Heading: "Review your own games"
- One line: "Enter your Chess.com or Lichess username. We import your games and find the moves
  that cost you the most."
- Segmented control Chess.com | Lichess, username input (`autocapitalize="none"`,
  `autocorrect="off"`, `spellcheck=false`, `enterkeyhint="go"`, 16 px font), one primary button
  "Import my games". Error text renders under the input.
- Secondary text links under the card: "Sign in with Lichess", "Paste a PGN instead", "Try with a
  sample player" (sets the sample player and is the only path to `kfctofu`-style demo data).

After submit, the same card turns into a progress view driven by the sync job: a determinate bar
(`analyzed + skipped` of `total`), "Checking game 214 of 1,904", and a note that you can leave the
page. As soon as the first 10 games are analyzed, show "Open your latest game" (secondary) so the
user gets value before the full sync ends. On completion, Today replaces the card.

Other routes with no identity show the shared empty state with one action, "Import my games",
linking to `/`.

### Returning user: Today

Header: username, platform, rating per time control from the latest game of each (for example
"Blitz 723 · Rapid 840"), and a small "Sync new games" text button showing last sync time.

Cards, in this order; each has exactly one button:

1. Due reviews: "22 positions due" with theme chips. Button (the only primary on the page):
   "Start review", goes to `/practice`. When 0 are due: "Nothing due. Next review tomorrow" and the
   primary moves to card 2.
2. Latest game: opponent, result, date, accuracy and blunder count, mini board of the first
   critical moment. Button "Review game" to `/games/$id?moment=<first>`.
3. Top leak: first leak from the insights API ("Missed tactics, 3.0 points per 10 games").
   Button "Practice this" (same handler Insights uses).
4. Repertoire: "Continue Italian (White), 6 of 14 lines learned". Button "Continue drill". Hidden
   until the user has a repertoire.

Each card loads independently with its own skeleton; a failed card shows a one-line error and
"Retry" inside that card. Remove the "Bring in recent games / Ready" strip.

---

## 4. Cross-links: one flow instead of separate tools

| From | Action label | Goes to | Detail |
| --- | --- | --- | --- |
| Review, moment card | Retry this move | inline `RetryMistake` | Already exists; make it the moment card's primary |
| Review, moment card | Practice this theme | `createTrainingSession(theme, momentId)` | Rename "Train this position" in the header; move it into the moment card |
| Review, move toolbar | Open in analysis | `/analysis?fen=&from=game:<id>:<ply>` | Analysis shows "Back to game" when `from` is set |
| Review, moment card | Ask coach | focuses coach input, prefilled "Why is {best} better than {played}?" | On mobile, opens coach as a bottom sheet over the board (see bug R3) |
| Review, header overflow | Export PGN | download | Secondary, inside a "More" menu with "Open on Chess.com/Lichess" |
| Insights, leak card | Practice these positions | practice session by leak | Keep; only leak #1 is primary, the others secondary |
| Insights, leak card | See examples | `/games?theme=<leak>` | Filtered library |
| Explorer, your move row with low score | "You go wrong here" chip then "Add to repertoire" | `/repertoire?fen=&color=` | Pre-selects the line |
| Repertoire drill, failed line | Open in explorer | `/analysis?tab=explorer&fen=` | |
| Play, game over | Review with coach | stores game, then `/games/$id` | Primary in the result dialog; secondary "Rematch" |
| Set up position, done | Analyze | `/analysis?fen=` | Primary; secondary "Play from here" to `/play?fen=` |
| Practice, after grading | Open in analysis | `/analysis?fen=` | Exists as text link; keep |
| Practice, session end | Back to Today | `/` | Replace "View progress" |
| Progress, blindspot row | Practice | practice session by theme | Rows become links |
| Opening stats row (Progress) | Open in explorer | `/analysis?tab=explorer&fen=` | |

Every cross-link that creates a session shows a pending state on the clicked button only (spinner
replaces the icon, label stays), and an error under that button if it fails.

---

## 5. Consistency rules

Header. Every page uses `PageHeader` (eyebrow optional, h1, one-line detail, actions on the
right). Today, Practice, Progress and Analysis build their own headers now. Eyebrows stay sentence
case in markup and are uppercased by CSS only. Game review eyebrow becomes
"Win · 22 Jun 2026 · Blitz 3+0" instead of "2026.06.22 · WIN".

Buttons. One `.primary` per view (per sheet or dialog when one is open). Variants: `.primary`,
`.secondary`, `.ghost` (text action), `.danger`. All share height 40 px desktop, 44 px under
`(pointer: coarse)`. Add `:active { transform: scale(0.97) }` with 120 ms ease-out, gated hover
under `@media (hover: hover) and (pointer: fine)`. Drop the green glow shadow on `.primary`.

Loading. Skeletons for anything that replaces page content (library, Today cards, review, Progress
charts); spinners only inside buttons and for under-a-second inline checks ("Checking Nf3...").
Show the skeleton only after 150 ms to avoid flashes.

Empty states. Shared `EmptyState` (icon, title, one sentence, one button). Never render an empty
state while a query is fetching.

Errors. Inline, under the control that failed, with `role="alert"`. Page-level errors only when
the whole page cannot render, with "Try again".

Background work. Sync and long analyses report through a toast region (bottom-right desktop,
above the tab bar on mobile, respecting the safe area): "Syncing games 214/1,904", then
"Imported 37 new games. Review latest". The toast survives navigation because it reads workspace
state. `aria-live="polite"`. No toast library needed; one small component.

Focus. Global `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px }` on
buttons, links, inputs, move cells, board squares. Remove one-off focus rules once global exists.

Keyboard shortcuts (desktop only; ignored while typing in inputs):

| Key | Action | Pages |
| --- | --- | --- |
| Left / Right (also k / j) | previous / next move | review, analysis |
| Home / End (also Up / Down) | start / end | review, analysis |
| f | flip board | review, analysis, practice |
| n / p | next / previous critical moment | review |
| r | retry current mistake | review |
| / | focus coach input | review, analysis |
| e | toggle engine | analysis |
| g then t / g / p / a | go to Today / Games / Practice / Analysis | all |
| ? | open shortcut sheet | all |
| Esc | close sheet or dialog | all |

The `?` sheet is a modal dialog listing the table for the current page. No open/close animation
(keyboard-triggered).

Numbers. `font-variant-numeric: tabular-nums` on `body` utilities: `.num` class plus all stat
tiles, tables, move lists, eval labels, clocks, badges. Format counts with `toLocaleString()`
(2,777) and dates with `Intl.DateTimeFormat` ("22 Jun 2026"); never show raw `2026.06.22` or
`????.??.??`.

Tokens. New `src/styles/tokens.css`, imported first in `main.tsx`:

```css
:root {
  /* surface */
  --bg: #eef3f7; --surface: #ffffff; --surface-2: #f8fafb; --line: #dce4df; --line-strong: #cfd9e4;
  /* text */
  --ink: #17201b; --ink-2: #3c4856; --muted: #5d6a75; /* was #81909c, 3.3:1 on white */
  /* brand + state */
  --accent: #198754; --accent-strong: #146c43; --accent-soft: #eef7f1;
  --danger: #b4232d; --warning: #94650a; --info: #2b66a3; --focus: #1f8fe5;
  /* chrome */
  --nav-bg: #18231d; --nav-ink: #aebdb5; --nav-active: #2e7c52;
  /* board + eval */
  --eval-white: #f3f2ee; --eval-black: #33383c;
  /* move labels (from moveLabels.tsx) */
  --mv-brilliant: #12817c; --mv-great: #2b66a3; --mv-best: #3b7f2b; --mv-excellent: #557a2e;
  --mv-good: #5f6e66; --mv-book: #86643d; --mv-inaccuracy: #94650a; --mv-mistake: #b4520f;
  --mv-miss: #b2375a; --mv-blunder: #a8202b;
  /* results */
  --win: #397c57; --draw: #a9b4ae; --loss: #c4574f;
  /* type scale */
  --fs-12: 0.75rem; --fs-13: 0.8125rem; --fs-14: 0.875rem; --fs-16: 1rem;
  --fs-20: 1.25rem; --fs-24: 1.5rem; --fs-32: 2rem;
  /* spacing (4 px base) */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px; --sp-6: 32px; --sp-7: 48px;
  --radius: 8px;
  --z-sticky: 10; --z-nav: 20; --z-sheet: 40; --z-toast: 50; --z-dialog: 60;
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1); --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
}
```

`MOVE_LABELS[*].color` becomes `var(--mv-*)`. Local palettes (`--rv-*`, `--insights-*`,
`--openings-*`) alias the global tokens instead of redefining hex. Dark mode is out of scope for
this pass, but tokens make it a single `@media (prefers-color-scheme: dark)` block later.

Typography. Seven sizes only (the `--fs-*` list). h1 32 px desktop / 24 px mobile, line-height
1.15, `text-wrap: balance`; body 14 px, line-height 1.5, `text-wrap: pretty`. Weights 400 / 600 /
750 (current CSS uses 700, 750, 800, 850).

Motion. Keep transitions to `transform` and `opacity`, under 250 ms. Add one global
`@media (prefers-reduced-motion: reduce)` block in `styles.css` that removes transforms and the
spinner rotation speed-up; seven local blocks exist, the shell has none.

Mobile baseline (in `index.html` and `styles.css`): `viewport-fit=cover`, `theme-color` matching
`--bg`, `-webkit-tap-highlight-color: transparent`, `touch-action: manipulation` on controls,
`100dvh` instead of `100vh` (`.app-frame`, `.app-sidebar`), hit targets at least 44 px under
`(pointer: coarse)` (board nav buttons and move cells are 32 to 34 px now).

---

## 6. Bug list from the walkthrough

| ID | Route / width | What you see | What is wrong | Fix |
| --- | --- | --- | --- | --- |
| G1 | `/games` 1440 | 3.9 s blank, then a grid | Endpoint returns full analyses (74.5 MB for 2,777 games) | New paginated summary endpoint (`id, date, white, black, result, elo, time_control, opening, moment_count, top_themes, accuracy`), 50 per page, infinite scroll or "Load more" |
| G2 | `/games` 1440 / 390 | 2,777 cards in a 235 px (desktop) / 300 px (mobile) scroll box | Nested scroll, page below is empty | Remove `max-height` on `.game-list`; let the page scroll. Virtualize or paginate (G1) |
| G3 | `/games` | "No games yet" + "Import games" under "Loading your game library..." | `showImport`/empty state ignore `isLoading` | Render skeleton rows while `isFetching && !analyses.length` |
| G4 | `/games` | First card "? vs ?", "????.??.?? · Unknown · vs ?", "PGN · 0 moments", highlighted as active | Junk PGN row stored; active index defaults to 0 | Hide games with no moves or no players server-side; no "active" highlight in the library |
| G5 | `/games` | No search, filter or sort for 2,777 games | | Filter chips: result, time control, color, theme; search by opponent; sort by date / blunders |
| G6 | sidebar | Games badge reads 2777 on `/games`, 25 on other pages | Badge uses `analyses.length`, which is the 25-item sessionStorage slice after reload | Badge from the summary endpoint's `total`, or drop it and badge Practice "due" instead |
| G7 | `/games?import=true` new user | PGN box pre-filled with `kfctofu`'s sample game | Sample seeding runs for every user | Empty textarea with placeholder; sample only via "Try with a sample player" |
| H1 | `/` new user | Profile "brandnewplayer42 · Profile ready", focus "Candidate Move Discipline", Start practice | No onboarding; actions lead to empty sessions | Section 3 connect card |
| H2 | `/` | Rating changes each load (771, 764, 528, 723) | `current_rating` not tied to latest game per time control (API gave 458, 439, 426 in 3 s) | Backend: rating per time control from the most recent game; UI shows the per-control list |
| H3 | `/` | "Continue training" and "Start practice" both primary, same handler | Duplicate action | Today layout in section 3 |
| H4 | `/` | Strip "Bring in recent games / Ready" | `workspace.status` "Ready" says nothing | Remove; sync lives in the header + toast |
| R1 | `/games/$id` 1440 | Accuracy + 10-row label table fill the first screen; board starts at y=530 | Summary before board | Chess.com order: board + eval bar left, right column = summary (collapsed to accuracy pair + counts of mistake/miss/blunder only, "Show all labels" toggle), key moments, coach |
| R2 | `/games/$id` 1440 | Board panel is `sticky` but 1,434 px tall, so it scrolls away | Eval graph, move list and square-control sit inside the sticky panel | Sticky container holds only board + nav (max 100dvh - 48 px); move list and graph go to the right column |
| R3 | `/games/$id` 390 | Board at y=650, coach input at ~y=3,300; page 4,144 px tall | Desktop stacking order | Mobile order: compact header, board, nav buttons, current-move strip (label + Retry), then tabs [Moments, Moves, Coach, Summary]. Coach answer arrows are visible because the board stays above the tabs |
| R4 | `/games/$id` | Nf3 shows "Miss" in move list and "Blunder" in the moment card | Moment severity and move classification are two systems | Moment card shows `MoveBadge` for the move's classification; keep severity only as sort order |
| R5 | `/games/$id` | "19 plies", "win as white", "Move accuracy 34.9% · Selected for training" | Jargon, lowercase | "10 moves", "Won as White", "Move accuracy 35%" |
| R6 | `/games/$id` | Opening name truncated without tooltip on 390 ("Mieses-Kotro...") | | `title` attribute, or wrap to 2 lines |
| R7 | `/games/$id` | Move cell aria-label "1... d5, Book, eval " (empty eval) | Missing eval for black plies | Omit "eval" when undefined |
| R8 | `/games/$id` | Two primaries visible: "Retry this move" and coach suggestion chip (filled green) | | Coach chips become `.secondary` chips |
| R9 | `/games/$id` | No h2s; headings jump h1 to h3 | | Section headings h2 |
| P1 | `/practice` 1440 | 600 px card on an empty canvas | | Show the queue: due count, theme chips, preview of first position; Puzzles moves to its own route |
| P2 | `/practice` session end | "View progress" | Breaks the loop | "Back to Today" primary, "Practice more" secondary |
| PR1 | `/progress` | Rating line zig-zags between ~400 and ~700 | Mixes blitz and rapid | One line per time control with toggle; x-axis ticks by month (labels overlap now) |
| PR2 | `/progress` | "Recurring blindspots: Missed Tactic 9098" | Count of moments, larger than games; unlabeled | Show "% of games" with count as secondary text |
| PR3 | `/progress` | "Transfer score 25%" | Unexplained | Rename "Fixed in real games" with an info tooltip, or move to Quality |
| I1 | `/insights` | Three primary "Practice ..." buttons | | Only leak #1 primary |
| I2 | `/insights` | Range toggle "Last 500" while header says "last 499" | | Header reads "Last 500 games (499 with engine data)" |
| I3 | `/insights` empty | Range toggle shown above "Not enough games yet" | | Hide toggle when empty |
| A1 | `/analysis` 390 | Engine lines and "Moves" start below the fold; header takes 120 px | | Hide page header on mobile analysis; engine line strip directly under board |
| S1 | shell 390 | 6 tabs, 11 px labels, Sign in hidden | | Section 2 tab bar + More sheet |
| S2 | shell | `100vh` on `.app-frame` and `.app-sidebar`; no `viewport-fit=cover`; default tap highlight `rgba(51,181,229,.4)` | | Mobile baseline (section 5) |
| S3 | shell | Hover rules on `.app-sidebar nav a`, `.move-choices button` not gated | Sticky hover on touch | Wrap in `(hover: hover) and (pointer: fine)` |
| S4 | all | `.intake-divider` and others use `#81909c` on white (about 3.3:1) for 12 px text | Fails AA | `--muted` token |
| S5 | `/games?import=true` | "Sync full history" stays on the page; leaving loses progress feedback | | Toast (section 5) |

---

## 7. Execution plan

Do chunk 0 first (one engineer, about half a day). Then A to D run in parallel; their file lists
do not overlap. Each chunk ends with `npm run build`, `npm run lint` (if configured), and a
walkthrough at 1440 and 390.

### Chunk 0: shared primitives and extraction (blocking, small)

Files: `src/router.tsx` (move `GamesPage` and `GameIntake` out, unchanged), new
`src/pages/GamesPage.tsx`, new `src/components/EmptyState.tsx`, new
`src/components/Skeleton.tsx` + `Skeleton.css`, new `src/styles/tokens.css`, `src/main.tsx` (import
tokens).

Accept: app behaves exactly as before; `EmptyState({icon,title,body,action})` and
`Skeleton({lines|variant})` exist; tokens file imported; build passes.

### Chunk A: shell, navigation, global styles, shortcuts, toasts

Files: `src/router.tsx` (AppShell + route entries for `/puzzles`, `/play`, `/repertoire`,
`/setup` if not already added), new `src/components/AppNav.tsx` + `AppNav.css`, new
`src/components/MoreSheet.tsx`, new `src/components/ShortcutSheet.tsx`, new
`src/lib/useHotkeys.ts`, new `src/components/SyncToast.tsx`, `src/styles.css` (shell, buttons,
focus, type scale, reduced motion, mobile baseline; replace hex with tokens),
`src/components/AccountButton.tsx` + `.css` (placement only), `index.html`.

Accept:
- Desktop shows Today + four groups + footer account + "Developer: quality"; 721 to 1023 px shows
  the icon rail; 390 shows 5 tabs and a More sheet containing every other route.
- Sheet traps focus, closes on Esc / backdrop / navigation, pads for the home indicator.
- `?` opens the shortcut sheet; `g` sequences navigate; keys do nothing while an input has focus.
- Sync started anywhere shows a toast that survives navigation and ends with a link to the newest
  game.
- No `100vh`, no ungated `:hover`, global `:focus-visible` ring visible on every control in a tab
  walk; buttons 44 px under `(pointer: coarse)`.
- `styles.css` raw hex count drops from 169 to under 20 (board/chart specifics only).

### Chunk B: first run and Today

Files: `src/pages/HomePage.tsx`, new `src/pages/HomePage.css`, new
`src/components/ConnectAccount.tsx`, new `src/components/TodayCards.tsx`,
`src/workspace/WorkspaceContext.tsx` (no default player, `hasIdentity`, expose `syncJob`
`{status,total,done,analyzed}` and `startSync(player, platform)`; drop sample PGN seeding),
`src/lib/api.ts` (only if a new client call for latest game or rating per time control is needed;
prefer a new `src/lib/todayApi.ts`). Backend: `current_rating` per time control (new field,
optional, in a new `today_api.py`).

Accept:
- Cleared storage at `/` shows only the connect card; nothing references `kfctofu`.
- Submitting shows determinate progress; "Open your latest game" appears after 10 analyzed games.
- Returning user sees the four cards with exactly one primary; each card has its own skeleton and
  error retry; rating text is stable across reloads.
- Other routes without identity show `EmptyState` linking to `/`.

### Chunk C: review layout and cross-links

Files: `src/pages/GameReviewPage.tsx`, `src/components/GameReview.css`,
`src/components/GamePanel.tsx`, `src/components/AnalysisPanel.tsx`,
`src/components/ReviewSummary.tsx`, `src/components/RetryMistake.tsx`,
`src/components/CoachPanel.tsx` + `.css` (prefill prop, chip styling, mobile sheet),
`src/components/moveLabels.tsx` (token colors), `src/pages/InsightsPage.tsx` + `.css`,
`src/pages/AnalysisBoardPage.tsx` + `.css` ("Back to game", `tab=explorer`),
`src/components/OpeningExplorer.tsx` + `.css`, `src/pages/PlayPage.tsx`,
`src/pages/RepertoirePage.tsx`, the Setup page file, `src/components/EvalBar.tsx`,
`src/components/EvalGraph.tsx`, `src/components/MoveList.tsx`.

Accept:
- At 1440x900 the full board is visible without scrolling on `/games/$id`; it stays in view while
  the right column scrolls.
- At 390 the order is board, nav, current-move strip, tabs; asking the coach keeps the board
  visible.
- One label per move everywhere (R4). Every link in the section 4 table works and round-trips
  (analysis "Back to game" returns to the same ply).
- One primary per view on review, insights, analysis, play result, setup.

### Chunk D: library, practice, progress, copy and states

Files: `src/pages/GamesPage.tsx`, `src/components/GameList.tsx`, new
`src/lib/libraryApi.ts`, backend new `library_api.py` (paginated summaries + filters),
`src/pages/PracticePage.tsx`, `src/components/PuzzleModeButton.tsx`, `src/pages/ProgressPage.tsx`,
`src/components/OpeningsPanel.tsx` + `.css`, `src/components/MonitoringDashboard.tsx`.

Accept:
- `/games` first page under 200 KB and under 500 ms locally; page scrolls normally; filters and
  search work; junk "? vs ?" rows hidden; skeleton rows while loading, never "No games yet" during
  a fetch.
- Practice start shows the queue; session end returns to Today.
- Progress chart split by time control with readable monthly ticks; blindspots as % of games;
  opening and blindspot rows link to explorer / practice.
- Copy sweep on these files: no raw dates, no "plies", sentence case labels, counts with
  thousands separators.

### Out of scope here

Dark mode (tokens make it possible later), real-device testing of safe areas and tap behavior
(must be checked on an iPhone before calling S1/S2 done; emulation cannot show them), and the Play,
Repertoire and Setup internals beyond their cross-links and states.
