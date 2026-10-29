import type { ReactNode } from 'react';
import './EmptyState.css';

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  /** One clear next step, usually a primary button or link. */
  action?: ReactNode;
};

export function EmptyState({ icon, title, body, action }: EmptyStateProps) {
  return (
    <section className="empty-state">
      {icon && <div className="empty-state-icon" aria-hidden="true">{icon}</div>}
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </section>
  );
}
