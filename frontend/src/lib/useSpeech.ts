import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { SETTINGS_KEY, getSettings, saveSettings, useAuth } from './authApi';

// Web Speech API wrapper: text-to-speech for coach answers and speech-to-text for
// questions. Every call is a no-op where the browser lacks support.

const STORAGE_KEY = 'chess-coach.speak-answers';

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}

interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}

interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const scope = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

function readStoredPreference(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'on';
  } catch {
    return false;
  }
}

function storePreference(enabled: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, enabled ? 'on' : 'off');
  } catch {
    // Storage can be blocked (private mode); the toggle still works for this visit.
  }
}

/** Turn the coach's light Markdown into plain sentences for reading aloud. */
export function speakableText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s*#+\s*/gm, '')
    .replace(/^\s*([-*]|\d+\.)\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function useSpeech() {
  const ttsSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;
  const Recognizer = recognitionConstructor();
  const sttSupported = Recognizer !== null;

  const [speakEnabled, setSpeakEnabledState] = useState(() => ttsSupported && readStoredPreference());
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<Recognition | null>(null);

  // Signed-in users keep this preference on their account; everyone else keeps it in the browser.
  const queryClient = useQueryClient();
  const signedIn = useAuth().data?.signed_in ?? false;
  const accountSettings = useQuery({ queryKey: SETTINGS_KEY, queryFn: getSettings, enabled: signedIn, staleTime: 5 * 60_000, retry: false });
  const accountSpeak = accountSettings.data?.speak_answers;

  useEffect(() => {
    if (accountSpeak === undefined) return;
    setSpeakEnabledState(ttsSupported && accountSpeak);
    storePreference(accountSpeak);
  }, [accountSpeak, ttsSupported]);

  const stopSpeaking = useCallback(() => {
    if (ttsSupported) window.speechSynthesis.cancel();
  }, [ttsSupported]);

  const speak = useCallback(
    (markdown: string) => {
      if (!ttsSupported) return;
      const text = speakableText(markdown);
      window.speechSynthesis.cancel();
      if (!text) return;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1;
      window.speechSynthesis.speak(utterance);
    },
    [ttsSupported]
  );

  const setSpeakEnabled = useCallback(
    (enabled: boolean) => {
      setSpeakEnabledState(enabled);
      storePreference(enabled);
      if (!enabled) stopSpeaking();
      if (signedIn) {
        queryClient.setQueryData(SETTINGS_KEY, { speak_answers: enabled });
        saveSettings({ speak_answers: enabled }).catch(() => {
          // The toggle still works for this visit; the next load shows the saved value.
        });
      }
    },
    [queryClient, signedIn, stopSpeaking]
  );

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  /** Start dictation. `onFinal` receives the final transcript once the speaker pauses. */
  const startListening = useCallback(
    (onFinal: (transcript: string) => void, onInterim?: (transcript: string) => void) => {
      if (!Recognizer || recognitionRef.current) return;
      stopSpeaking();
      const recognition = new Recognizer();
      recognition.lang = navigator.language || 'en-US';
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.maxAlternatives = 1;
      recognition.onresult = (event) => {
        let interim = '';
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result.isFinal) {
            onFinal(result[0].transcript.trim());
          } else {
            interim += result[0].transcript;
          }
        }
        if (interim && onInterim) onInterim(interim.trim());
      };
      recognition.onerror = () => setListening(false);
      recognition.onend = () => {
        recognitionRef.current = null;
        setListening(false);
      };
      recognitionRef.current = recognition;
      try {
        recognition.start();
        setListening(true);
      } catch {
        recognitionRef.current = null;
        setListening(false);
      }
    },
    [Recognizer, stopSpeaking]
  );

  // Stop talking and listening when the panel unmounts.
  useEffect(
    () => () => {
      recognitionRef.current?.abort();
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel();
    },
    []
  );

  return {
    ttsSupported,
    sttSupported,
    speakEnabled,
    setSpeakEnabled,
    speak,
    stopSpeaking,
    listening,
    startListening,
    stopListening
  };
}
