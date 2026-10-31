import { Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  ArrowUp,
  Check,
  GraduationCap,
  Loader2,
  Mic,
  MoveUpRight,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
  Volume2,
  VolumeX
} from 'lucide-react';
import { askCoach } from '../lib/api';
import { AUTH_KEY, useAuth } from '../lib/authApi';
import {
  sendCoachFeedback,
  type BoardArrow,
  type CoachAnnotations,
  type CoachRating,
  type SquareHighlight
} from '../lib/coachApi';
import type { CoachAskResponse, CoachingOutput } from '../lib/types';
import { useSpeech } from '../lib/useSpeech';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './CoachPanel.css';

type FeedbackState = 'idle' | 'sending' | 'sent' | 'error';
// The count only shows when it is about to matter.
const LOW_QUOTA = 3;

type CoachMessage = {
  role: 'coach';
  question: string;
  fen?: string;
  coaching: CoachingOutput;
  usedLlm: boolean;
  tools: string[];
  arrows: BoardArrow[];
  highlights: SquareHighlight[];
  feedback: FeedbackState;
  rating?: CoachRating;
};

type Message = { role: 'user'; text: string } | CoachMessage;

const ARROW_LABEL: Record<BoardArrow['kind'], string> = {
  best: 'best move',
  played: 'played',
  threat: 'threat',
  idea: 'idea'
};

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

// The coach answers in light Markdown: paragraphs, bullet lists, bold and code.
function CoachMarkdown({ text }: { text: string }) {
  return (
    <>
      {text.trim().split(/\n{2,}/).map((block, index) => {
        const lines = block.split('\n').map((line) => line.trim()).filter(Boolean);
        if (lines.length && lines.every((line) => /^([-*]|\d+\.)\s/.test(line))) {
          return (
            <ul key={index}>
              {lines.map((line, item) => <li key={item}>{inline(line.replace(/^([-*]|\d+\.)\s+/, ''))}</li>)}
            </ul>
          );
        }
        return <p key={index}>{inline(lines.join(' ').replace(/^#+\s*/, ''))}</p>;
      })}
    </>
  );
}

function BoardNotes({ arrows, highlights }: { arrows: BoardArrow[]; highlights: SquareHighlight[] }) {
  if (!arrows.length && !highlights.length) return null;
  return (
    <ul className="coach-board-notes" aria-label="Board annotations">
      {arrows.map((arrow) => (
        <li key={`${arrow.from_square}-${arrow.to_square}`} data-kind={arrow.kind}>
          {arrow.from_square}–{arrow.to_square} <span>{ARROW_LABEL[arrow.kind]}</span>
        </li>
      ))}
      {highlights.map((highlight) => (
        <li key={highlight.square} data-kind={highlight.kind}>
          {highlight.square} <span>{highlight.kind}</span>
        </li>
      ))}
    </ul>
  );
}

export function CoachPanel({
  gameId,
  fen,
  suggestions,
  onAnnotations,
  prefill,
  autoFocus = false
}: {
  gameId?: string;
  fen?: string;
  suggestions: string[];
  /** Puts `text` in the input and focuses it; a new `nonce` repeats the same text. */
  prefill?: { text: string; nonce: number } | null;
  /** Focus the question input on mount, e.g. when a link asked for the coach. */
  autoFocus?: boolean;
  /** Receives the verified arrows and highlights of the latest answer; called with empty lists on reset. */
  onAnnotations?: (arrows: BoardArrow[], highlights: SquareHighlight[]) => void;
}) {
  const workspace = useWorkspace();
  const speech = useSpeech();
  const queryClient = useQueryClient();
  const quota = useAuth().data?.coach_quota;
  const [messages, setMessages] = useState<Message[]>([]);
  const [history, setHistory] = useState<unknown[]>([]);
  const [question, setQuestion] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!prefill) return;
    setQuestion(prefill.text);
    const input = inputRef.current;
    if (!input) return;
    input.focus({ preventScroll: true });
    input.setSelectionRange(prefill.text.length, prefill.text.length);
  }, [prefill?.nonce]);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus({ preventScroll: true });
  }, [autoFocus]);
  // Speech recognition calls back after the render that started it, so it needs the latest ask().
  const askRef = useRef<(text: string) => Promise<void>>(async () => {});

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    speech.stopSpeaking();
    setMessages((current) => [...current, { role: 'user', text: trimmed }]);
    setQuestion('');
    setError('');
    setPending(true);
    requestAnimationFrame(() => threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight }));
    try {
      const response = (await askCoach({
        question: trimmed,
        username: workspace.player,
        platform: workspace.platform,
        gameId,
        fen,
        messageHistory: history
      })) as CoachAskResponse & CoachAnnotations;
      const arrows = response.arrows ?? [];
      const highlights = response.highlights ?? [];
      setMessages((current) => [
        ...current,
        {
          role: 'coach',
          question: trimmed,
          fen,
          coaching: response.coaching,
          usedLlm: response.used_llm,
          tools: response.tools_used,
          arrows,
          highlights,
          feedback: 'idle'
        }
      ]);
      if (response.used_llm) setHistory(response.message_history);
      onAnnotations?.(arrows, highlights);
      if (speech.speakEnabled) speech.speak(response.coaching.answer);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The coach could not answer. Try again.');
    } finally {
      setPending(false);
      void queryClient.invalidateQueries({ queryKey: AUTH_KEY });
      requestAnimationFrame(() => threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight }));
    }
  }
  askRef.current = ask;

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question);
  }

  function reset() {
    speech.stopSpeaking();
    speech.stopListening();
    setMessages([]);
    setHistory([]);
    setError('');
    onAnnotations?.([], []);
  }

  function toggleListening() {
    if (speech.listening) {
      speech.stopListening();
      return;
    }
    speech.startListening(
      (transcript) => {
        setQuestion(transcript);
        void askRef.current(transcript);
      },
      (interim) => setQuestion(interim)
    );
  }

  function updateMessage(index: number, patch: Partial<CoachMessage>) {
    setMessages((current) =>
      current.map((message, position) => (position === index && message.role === 'coach' ? { ...message, ...patch } : message))
    );
  }

  async function rate(index: number, message: CoachMessage, rating: CoachRating) {
    if (message.feedback === 'sending' || message.feedback === 'sent') return;
    updateMessage(index, { feedback: 'sending', rating });
    try {
      await sendCoachFeedback({
        question: message.question,
        answer: message.coaching.answer,
        rating,
        gameId,
        fen: message.fen,
        toolsUsed: message.tools
      });
      updateMessage(index, { feedback: 'sent' });
    } catch {
      updateMessage(index, { feedback: 'error' });
    }
  }

  return (
    <section className="panel coach-panel" aria-label="Chess coach">
      <div className="coach-head">
        <div className="panel-title"><GraduationCap size={18} /> Coach</div>
        <div className="coach-head-actions">
          {speech.ttsSupported && (
            <button
              className="icon-button"
              type="button"
              aria-label={speech.speakEnabled ? 'Stop reading answers aloud' : 'Read answers aloud'}
              aria-pressed={speech.speakEnabled}
              title={speech.speakEnabled ? 'Reading answers aloud' : 'Read answers aloud'}
              onClick={() => speech.setSpeakEnabled(!speech.speakEnabled)}
            >
              {speech.speakEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
            </button>
          )}
          {messages.length > 0 && (
            <button className="icon-button" type="button" aria-label="Start a new conversation" title="New conversation" onClick={reset}>
              <RotateCcw size={16} />
            </button>
          )}
        </div>
      </div>

      {messages.length === 0 ? (
        <div className="coach-empty">
          <p>Ask about this position or your play. The coach checks claims with Stockfish and your saved games.</p>
          <div className="coach-suggestions">
            {suggestions.map((suggestion) => (
              <button key={suggestion} type="button" disabled={pending} onClick={() => ask(suggestion)}>{suggestion}</button>
            ))}
          </div>
        </div>
      ) : (
        <div className="coach-thread" ref={threadRef} aria-live="polite">
          {messages.map((message, index) =>
            message.role === 'user' ? (
              <div className="coach-message user" key={index}>{message.text}</div>
            ) : (
              <div className="coach-message coach" key={index}>
                <CoachMarkdown text={message.coaching.answer} />
                {message.coaching.recommended_move && (
                  <p className="coach-move">Suggested move <strong>{message.coaching.recommended_move}</strong></p>
                )}
                <dl className="coach-facts">
                  <dt>Principle</dt>
                  <dd>{message.coaching.principle}</dd>
                  <dt>Drill</dt>
                  <dd>{message.coaching.drill}</dd>
                </dl>
                {message.coaching.evidence.length > 0 && (
                  <details className="coach-evidence">
                    <summary>Evidence ({message.coaching.evidence.length})</summary>
                    <ul>{message.coaching.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                  </details>
                )}
                <BoardNotes arrows={message.arrows} highlights={message.highlights} />
                <small className="coach-meta">
                  {message.usedLlm ? `Confidence ${Math.round(message.coaching.confidence * 100)}%` : 'Offline answer from engine analysis'}
                  {message.tools.length > 0 && ` · used ${message.tools.map((tool) => tool.replace(/_/g, ' ')).join(', ')}`}
                </small>
                <div className="coach-actions">
                  {onAnnotations && (message.arrows.length > 0 || message.highlights.length > 0) && (
                    <button
                      className="coach-chip"
                      type="button"
                      onClick={() => onAnnotations(message.arrows, message.highlights)}
                    >
                      <MoveUpRight size={14} aria-hidden="true" /> Show on board
                    </button>
                  )}
                  <div className="coach-rating" role="group" aria-label="Rate this answer">
                    {message.feedback === 'sent' ? (
                      <span className="coach-thanks"><Check size={14} aria-hidden="true" /> Thanks</span>
                    ) : (
                      <>
                        <button
                          className="coach-rate"
                          type="button"
                          aria-label="Helpful answer"
                          title="Helpful"
                          disabled={message.feedback === 'sending'}
                          onClick={() => rate(index, message, 'helpful')}
                        >
                          <ThumbsUp size={14} />
                        </button>
                        <button
                          className="coach-rate"
                          type="button"
                          aria-label="Not helpful answer"
                          title="Not helpful"
                          disabled={message.feedback === 'sending'}
                          onClick={() => rate(index, message, 'not_helpful')}
                        >
                          <ThumbsDown size={14} />
                        </button>
                        {message.feedback === 'error' && <span className="coach-rate-error" role="alert">Not sent. Try again.</span>}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )
          )}
          {pending && (
            <div className="coach-message coach pending"><Loader2 className="spin" size={16} /> Checking the position…</div>
          )}
        </div>
      )}

      <form className="coach-input" onSubmit={submit}>
        <input
          ref={inputRef}
          id="coach-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={speech.listening ? 'Listening…' : 'Ask the coach…'}
          aria-label="Question for the coach"
          maxLength={2000}
        />
        {speech.sttSupported && (
          <button
            className={`icon-button coach-mic${speech.listening ? ' listening' : ''}`}
            type="button"
            aria-label={speech.listening ? 'Stop listening' : 'Ask by voice'}
            aria-pressed={speech.listening}
            title={speech.listening ? 'Stop listening' : 'Ask by voice'}
            disabled={pending}
            onClick={toggleListening}
          >
            <Mic size={17} />
          </button>
        )}
        <button className="primary icon-only" type="submit" disabled={!question.trim() || pending} aria-label="Send question">
          {pending ? <Loader2 className="spin" size={17} /> : <ArrowUp size={17} />}
        </button>
      </form>
      {speech.listening && <p className="coach-listening" role="status">Listening. Speak your question.</p>}
      {error && <p className="coach-error" role="alert">{error}</p>}
      {quota && quota.remaining <= LOW_QUOTA && !error && (
        <p className="coach-quota num">
          {quota.limit === 0
            ? "Coach questions aren't available on this plan."
            : quota.remaining === 0
            ? 'No coach questions left today.'
            : `${quota.remaining} coach ${quota.remaining === 1 ? 'question' : 'questions'} left today.`}
        </p>
      )}
    </section>
  );
}
