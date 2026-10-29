import { useEffect, useRef, useState, type DragEvent } from 'react';
import { AlertCircle, CheckCircle2, ImageUp, Loader2, X } from 'lucide-react';
import { IMAGE_TYPES, MAX_IMAGE_BYTES, readBoardImage, type VisionResult } from '../lib/visionApi';
import './ImageToBoard.css';

type Status =
  | { kind: 'idle' }
  | { kind: 'reading' }
  | { kind: 'done'; result: VisionResult }
  | { kind: 'error'; message: string };

function fileProblem(file: Blob): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return 'Use a PNG, JPEG or WebP image.';
  if (file.size > MAX_IMAGE_BYTES) return 'That image is over 5 MB. Crop it to the board and try again.';
  return null;
}

export function ImageToBoard({ onResult }: { onResult: (result: VisionResult) => void }) {
  const [preview, setPreview] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  useEffect(() => () => {
    abortRef.current?.abort();
  }, []);
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  async function read(file: Blob) {
    const problem = fileProblem(file);
    if (problem) {
      setStatus({ kind: 'error', message: problem });
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPreview(URL.createObjectURL(file));
    setStatus({ kind: 'reading' });
    try {
      const result = await readBoardImage(file, controller.signal);
      if (controller.signal.aborted) return;
      setStatus({ kind: 'done', result });
      onResultRef.current(result);
    } catch (error) {
      if (controller.signal.aborted) return;
      setStatus({ kind: 'error', message: error instanceof Error ? error.message : 'Could not read the board.' });
    }
  }
  const readRef = useRef(read);
  readRef.current = read;

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const item = [...(event.clipboardData?.items ?? [])].find((entry) => entry.kind === 'file' && entry.type.startsWith('image/'));
      const file = item?.getAsFile();
      if (!file) return;
      // Text pastes (into the FEN field, say) never reach here: only image files are ours.
      event.preventDefault();
      void readRef.current(file);
    }
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, []);

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void read(file);
  }

  function cancel() {
    abortRef.current?.abort();
    setStatus({ kind: 'idle' });
  }

  const reading = status.kind === 'reading';

  return (
    <section className="itb" aria-label="Read a board from an image">
      <div
        className="itb-drop"
        data-dragging={dragging || undefined}
        data-busy={reading || undefined}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {preview ? (
          <img className="itb-preview" src={preview} alt="Uploaded board" />
        ) : (
          <ImageUp className="itb-icon" size={28} aria-hidden />
        )}
        <div className="itb-copy">
          <strong>Screenshot or photo of a board</strong>
          <span>Drop it here, paste it (⌘V / Ctrl+V), or choose a file. PNG, JPEG or WebP, up to 5 MB.</span>
          <div className="itb-buttons">
            <button type="button" className="secondary" disabled={reading} onClick={() => inputRef.current?.click()}>
              <ImageUp size={16} aria-hidden /> Choose image
            </button>
            {reading && (
              <button type="button" className="secondary" onClick={cancel}>
                <X size={16} aria-hidden /> Cancel
              </button>
            )}
          </div>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={IMAGE_TYPES.join(',')}
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void read(file);
          }}
        />
      </div>

      <div className="itb-status" aria-live="polite">
        {reading && (
          <p className="itb-line"><Loader2 className="spin" size={16} aria-hidden /> Reading board… this takes about 10 seconds.</p>
        )}
        {status.kind === 'error' && (
          <p className="itb-line itb-error"><AlertCircle size={16} aria-hidden /> {status.message}</p>
        )}
        {status.kind === 'done' && (
          <>
            <p className={status.result.valid ? 'itb-line itb-ok' : 'itb-line itb-warn'}>
              {status.result.valid ? <CheckCircle2 size={16} aria-hidden /> : <AlertCircle size={16} aria-hidden />}
              {status.result.valid
                ? 'Board loaded into the editor. Check it against your image and fix any square.'
                : 'Loaded a best guess, but it is not a legal position yet. Fix it in the editor.'}
            </p>
            {status.result.warnings.length > 0 && (
              <ul className="itb-warnings">
                {status.result.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            )}
          </>
        )}
      </div>
    </section>
  );
}
