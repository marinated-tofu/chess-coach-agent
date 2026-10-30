import { Info } from 'lucide-react';
import { readLimitNotice } from '../lib/limitNotice';
import './LimitNoticeLine.css';

/** A quiet line for when a daily limit, not a fault, is why the model was left out. */
export function LimitNoticeLine({ noticeKey }: { noticeKey: string }) {
  const notice = readLimitNotice(noticeKey);
  if (!notice) return null;
  return (
    <p className="limit-notice" role="status">
      <Info size={15} aria-hidden="true" />
      <span>{notice.message}</span>
    </p>
  );
}
