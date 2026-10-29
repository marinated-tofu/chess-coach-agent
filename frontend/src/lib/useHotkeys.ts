import { useEffect, useRef } from 'react';

/**
 * Global keyboard shortcuts. Keys are single characters ("?", "f") or two-key sequences
 * written with a space ("g h"). Bindings never fire while the user is typing in a field,
 * while a modifier (other than Shift) is held, or while a modal dialog is open.
 */
export type HotkeyMap = Record<string, () => void>;

const SEQUENCE_TIMEOUT_MS = 1000;

export function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'));
}

function modalOpen() {
  return Boolean(document.querySelector('dialog[open], [aria-modal="true"]'));
}

export function useHotkeys(bindings: HotkeyMap, enabled = true) {
  // Read the latest bindings without re-subscribing on every render.
  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

  useEffect(() => {
    if (!enabled) return;
    let pending = '';
    let timer = 0;

    function reset() {
      pending = '';
      window.clearTimeout(timer);
    }

    function onKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key.length !== 1) return;
      if (isTypingTarget(event.target) || modalOpen()) {
        reset();
        return;
      }
      const key = event.key.toLowerCase();
      const map = bindingsRef.current;
      const combo = pending ? `${pending} ${key}` : key;
      if (pending) {
        reset();
        const action = map[combo];
        if (action) {
          event.preventDefault();
          action();
        }
        return;
      }
      if (Object.keys(map).some((binding) => binding.startsWith(`${key} `))) {
        pending = key;
        timer = window.setTimeout(reset, SEQUENCE_TIMEOUT_MS);
        event.preventDefault();
        return;
      }
      const action = map[key];
      if (action) {
        event.preventDefault();
        action();
      }
    }

    window.addEventListener('keydown', onKey);
    return () => {
      reset();
      window.removeEventListener('keydown', onKey);
    };
  }, [enabled]);
}
