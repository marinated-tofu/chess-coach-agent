import { Link } from '@tanstack/react-router';
import { Lock } from 'lucide-react';
import type { AccessDenied } from '../lib/access';
import { EmptyState } from './EmptyState';

/** Shown in place of a page section when the current player belongs to someone else. */
export function PrivatePlayerNotice({ error }: { error: AccessDenied }) {
  return (
    <EmptyState
      icon={<Lock size={22} />}
      title={error.signedIn ? 'This player is linked to another account' : "This player's practice is private"}
      body={error.signedIn
        ? 'Their practice and repertoires open only for that account. Pick one of your own players to continue.'
        : 'Sign in if this is your player. Their games stay public, and you can pick another player on the Games page.'}
      action={<Link className="primary" to="/account">{error.signedIn ? 'Your players' : 'Sign in'}</Link>}
    />
  );
}
