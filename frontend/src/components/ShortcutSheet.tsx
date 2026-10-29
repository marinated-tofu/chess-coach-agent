import { Fragment, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { NavItem } from './AppNav';

type Shortcut = { keys: string[][]; action: string };
type Section = { title: string; shortcuts: Shortcut[] };

/** Keys the review and analysis pages already handle (GamePanel, AnalysisBoardPage). */
const MOVE_SHORTCUTS: Shortcut[] = [
  { keys: [['←'], ['→']], action: 'Previous or next move' },
  { keys: [['Home'], ['End']], action: 'Start or end of the game' }
];

function pageSection(pathname: string): Section | null {
  if (/^\/games\/[^/]+/.test(pathname)) return { title: 'Game review', shortcuts: MOVE_SHORTCUTS };
  if (pathname.startsWith('/analysis')) {
    return {
      title: 'Analysis board',
      shortcuts: [
        { keys: [['←'], ['→']], action: 'Previous or next move' },
        { keys: [['Home'], ['End']], action: 'Start or end of the line' }
      ]
    };
  }
  return null;
}

function Keys({ keys }: { keys: string[][] }) {
  return (
    <span className="shortcut-keys">
      {keys.map((combo, comboIndex) => (
        <Fragment key={comboIndex}>
          {comboIndex > 0 && <span className="shortcut-or">or</span>}
          {combo.map((key, keyIndex) => (
            <Fragment key={keyIndex}>
              {keyIndex > 0 && <span className="shortcut-then">then</span>}
              <kbd>{key}</kbd>
            </Fragment>
          ))}
        </Fragment>
      ))}
    </span>
  );
}

/** Opened with "?". Keyboard-triggered, so it appears without animation. */
export function ShortcutSheet({ open, onClose, pathname, items }: {
  open: boolean;
  onClose: () => void;
  pathname: string;
  items: NavItem[];
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const sections: Section[] = [];
  const page = pageSection(pathname);
  if (page) sections.push(page);
  sections.push({
    title: 'Go to',
    shortcuts: items.map((item) => ({ keys: [['g', item.hotkey]], action: item.label }))
  });
  sections.push({
    title: 'Anywhere',
    shortcuts: [
      { keys: [['?']], action: 'Show this list' },
      { keys: [['Esc']], action: 'Close a sheet or dialog' }
    ]
  });

  return (
    <dialog
      ref={dialogRef}
      className="shortcut-sheet"
      aria-labelledby="shortcut-sheet-title"
      onClose={() => {
        if (open) onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="shortcut-sheet-body">
        <div className="shortcut-sheet-head">
          <h2 id="shortcut-sheet-title">Keyboard shortcuts</h2>
          <button type="button" className="more-sheet-close" aria-label="Close" onClick={onClose}>
            <X size={20} aria-hidden />
          </button>
        </div>
        {sections.map((section) => (
          <section key={section.title} className="shortcut-section">
            <h3>{section.title}</h3>
            <dl>
              {section.shortcuts.map((shortcut) => (
                <div key={shortcut.action}>
                  <dt><Keys keys={shortcut.keys} /></dt>
                  <dd>{shortcut.action}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        <p className="shortcut-note">Shortcuts pause while you type in a field.</p>
      </div>
    </dialog>
  );
}
