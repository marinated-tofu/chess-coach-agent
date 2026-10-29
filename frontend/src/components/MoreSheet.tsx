import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { Link, useRouterState } from '@tanstack/react-router';
import { X } from 'lucide-react';
import { AccountButton } from './AccountButton';
import { NavLink, isTabPath } from './AppNav';
import type { NavBadges, NavGroup } from './AppNav';

const ENTER_MS = 240;
const FADE_MS = 150;

function exitDuration() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? FADE_MS : ENTER_MS;
}

/**
 * Phone-only bottom sheet with every route that is not in the tab bar.
 * A modal <dialog> keeps focus inside and makes the page behind it inert.
 */
export function MoreSheet({ open, onClose, groups, badges, returnFocus }: {
  open: boolean;
  onClose: () => void;
  groups: NavGroup[];
  badges: NavBadges;
  returnFocus: RefObject<HTMLElement | null>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const href = useRouterState({ select: (state) => state.location.href });
  const openedAt = useRef(href);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      openedAt.current = href;
      dialog.showModal();
      // Next frame, so the closed position is painted before the slide starts.
      const frame = requestAnimationFrame(() => dialog.classList.add('is-open'));
      return () => cancelAnimationFrame(frame);
    }
    if (!open && dialog.open) {
      dialog.classList.remove('is-open');
      const timer = window.setTimeout(() => {
        dialog.close();
        returnFocus.current?.focus();
      }, exitDuration());
      return () => window.clearTimeout(timer);
    }
  }, [open]);

  // Any navigation closes the sheet, including back/forward.
  useEffect(() => {
    if (open && href !== openedAt.current) onClose();
  }, [href]);

  return (
    <dialog
      ref={dialogRef}
      className="more-sheet"
      aria-labelledby="more-sheet-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={(event) => {
        // The browser can close the dialog itself (a repeated Esc); keep state in step.
        event.currentTarget.classList.remove('is-open');
        if (open) onClose();
      }}
      onClick={(event) => {
        // A click on the dialog box itself (not its content) is a click on the backdrop.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="more-sheet-body">
        <div className="more-sheet-head">
          <span className="more-sheet-grabber" aria-hidden="true" />
          <h2 id="more-sheet-title">More</h2>
          <button type="button" className="more-sheet-close" aria-label="Close" onClick={onClose}>
            <X size={20} aria-hidden />
          </button>
        </div>
        <nav aria-label="More pages">
          {groups.map((group) => {
            const items = group.items.filter((item) => !isTabPath(item.to));
            if (!items.length) return null;
            return (
              <div className="nav-group" key={group.label ?? 'top'} role="group" aria-label={group.label ?? undefined}>
                {group.label && <span className="nav-group-label" aria-hidden="true">{group.label}</span>}
                {items.map((item) => (
                  <NavLink key={item.label} item={item} badges={badges} onNavigate={onClose} />
                ))}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <AccountButton />
          <Link to="/quality" className="nav-dev-link" activeProps={{ className: 'active' }} onClick={onClose}>
            Developer: quality
          </Link>
        </div>
      </div>
    </dialog>
  );
}
