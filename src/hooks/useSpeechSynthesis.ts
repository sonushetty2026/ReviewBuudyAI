'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface SpeechSynthesisHook {
  isSpeaking: boolean;
  isSupported: boolean;
  speak: (text: string) => Promise<void>;
  cancel: () => void;
}

/**
 * Hook for Web Speech API text-to-speech synthesis.
 * Selects a natural-sounding voice and provides speaking state.
 */
export function useSpeechSynthesis(): SpeechSynthesisHook {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);
  const resolveRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      setIsSupported(true);

      const loadVoices = () => {
        const voices = speechSynthesis.getVoices();
        // Prefer a natural-sounding English voice
        const preferred = voices.find(
          (v) =>
            v.lang.startsWith('en') &&
            (v.name.includes('Natural') ||
              v.name.includes('Premium') ||
              v.name.includes('Enhanced'))
        );
        voiceRef.current =
          preferred ||
          voices.find((v) => v.lang.startsWith('en') && v.default) ||
          voices.find((v) => v.lang.startsWith('en')) ||
          voices[0] ||
          null;
      };

      loadVoices();
      speechSynthesis.addEventListener('voiceschanged', loadVoices);
      return () => {
        speechSynthesis.removeEventListener('voiceschanged', loadVoices);
      };
    }
  }, []);

  const speak = useCallback((text: string): Promise<void> => {
    return new Promise<void>((resolve) => {
      if (!isSupported) {
        resolve();
        return;
      }

      // Cancel any ongoing speech
      speechSynthesis.cancel();

      // Clean text for speech (remove quotes used in confirmation)
      const cleanText = text.replace(/[""]/g, '').replace(/\n+/g, '. ');

      const utterance = new SpeechSynthesisUtterance(cleanText);
      if (voiceRef.current) {
        utterance.voice = voiceRef.current;
      }
      utterance.rate = 0.95;
      utterance.pitch = 1.0;
      utterance.volume = 1.0;

      utterance.onstart = () => setIsSpeaking(true);
      utterance.onend = () => {
        setIsSpeaking(false);
        resolve();
      };
      utterance.onerror = () => {
        setIsSpeaking(false);
        resolve();
      };

      resolveRef.current = resolve;
      speechSynthesis.speak(utterance);
    });
  }, [isSupported]);

  const cancel = useCallback(() => {
    speechSynthesis.cancel();
    setIsSpeaking(false);
    if (resolveRef.current) {
      resolveRef.current();
      resolveRef.current = null;
    }
  }, []);

  return { isSpeaking, isSupported, speak, cancel };
}
