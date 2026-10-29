export interface PgnExportOptions {
  evals?: boolean;
  clocks?: boolean;
  variations?: boolean;
}

export function pgnDownloadUrl(
  platform: string,
  username: string,
  gameId: string,
  opts: PgnExportOptions = {},
): string {
  const params = new URLSearchParams({
    evals: opts.evals === false ? '0' : '1',
    clocks: opts.clocks === false ? '0' : '1',
    variations: opts.variations === false ? '0' : '1',
  });
  return `/api/games/${encodeURIComponent(platform)}/${encodeURIComponent(username)}/${encodeURIComponent(gameId)}/pgn?${params}`;
}
