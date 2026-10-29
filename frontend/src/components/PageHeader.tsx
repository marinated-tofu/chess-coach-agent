import type { ReactNode } from 'react';

export function PageHeader({ eyebrow, title, detail, actions }: {
  eyebrow: string;
  title: string;
  detail?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="page-eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {detail && <p>{detail}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
