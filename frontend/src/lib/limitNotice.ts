/** Why a practice session or study plan came without the model. Only a daily limit sets it. */
export type LimitNotice = {
  message: string;
  resets_at: string;
};

// Only the POST that hit the limit returns a notice, and the page that shows it loads later with a
// GET. So it is kept here until the limit resets. Memory is the fallback when storage is blocked.
const PREFIX = 'chess-coach-limit-notice:';
const inMemory = new Map<string, LimitNotice>();

export const practiceNoticeKey = (sessionId: string) => `practice:${sessionId}`;
export const planNoticeKey = (planId: string) => `plan:${planId}`;

export function rememberLimitNotice(key: string, notice: LimitNotice | null | undefined) {
  if (!notice) return;
  inMemory.set(key, notice);
  try {
    sessionStorage.setItem(PREFIX + key, JSON.stringify(notice));
  } catch {
    // Kept in memory for this page load.
  }
}

export function readLimitNotice(key: string): LimitNotice | null {
  let notice = inMemory.get(key) ?? null;
  if (!notice) {
    try {
      notice = JSON.parse(sessionStorage.getItem(PREFIX + key) ?? 'null') as LimitNotice | null;
    } catch {
      return null;
    }
  }
  return notice && new Date(notice.resets_at).getTime() > Date.now() ? notice : null;
}
