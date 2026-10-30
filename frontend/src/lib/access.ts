/**
 * The server refused because the player is claimed: 401 for a visitor, 403 for another user.
 * It is a final answer, so queries do not retry it and pages show why instead of an error.
 */
export class AccessDenied extends Error {
  constructor(message: string, readonly signedIn: boolean) {
    super(message);
    this.name = 'AccessDenied';
  }
}

export function isAccessDenied(error: unknown): error is AccessDenied {
  return error instanceof AccessDenied;
}

export function isDeniedStatus(status: number) {
  return status === 401 || status === 403;
}

export async function throwIfDenied(response: Response): Promise<void> {
  if (!isDeniedStatus(response.status)) return;
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  const detail = typeof body?.detail === 'string' ? body.detail : 'This player is private.';
  throw new AccessDenied(detail, response.status === 403);
}
