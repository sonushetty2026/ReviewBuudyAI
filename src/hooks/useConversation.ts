'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ConversationPhase,
  ConversationState,
  AvatarExpression,
  AvatarGesture,
  DigitalHumanState,
  SentimentResult,
} from '@/types';
import {
  createInitialConversation,
  processUserInput,
} from '@/lib/conversationFlow';
import { useSpeechRecognition } from './useSpeechRecognition';
import { useSpeechSynthesis } from './useSpeechSynthesis';

interface ConversationHook {
  conversation: ConversationState;
  avatarState: DigitalHumanState;
  currentSubtitle: string;
  handleUserFinishedSpeaking: () => void;
  startListening: () => void;
  stopListening: () => void;
  isReady: boolean;
}

/**
 * Orchestrates the full conversation loop:
 * Avatar speaks → User listens → Process → Avatar responds → ...
 */
export function useConversation(): ConversationHook {
  const [conversation, setConversation] = useState<ConversationState>(
    createInitialConversation()
  );
  const [currentSubtitle, setCurrentSubtitle] = useState('');
  const [avatarState, setAvatarState] = useState<DigitalHumanState>({
    expression: AvatarExpression.SMILE,
    gesture: AvatarGesture.WAVING,
    isSpeaking: false,
    lookAtCamera: true,
  });
  const [isReady, setIsReady] = useState(false);

  const speech = useSpeechRecognition();
  const synthesis = useSpeechSynthesis();
  const hasStartedRef = useRef(false);

  // Start with greeting
  useEffect(() => {
    if (hasStartedRef.current) return;
    hasStartedRef.current = true;

    const greetingText = conversation.turns[0]?.text || '';
    setCurrentSubtitle(greetingText);
    setAvatarState((prev) => ({
      ...prev,
      gesture: AvatarGesture.WAVING,
      expression: AvatarExpression.SMILE,
      isSpeaking: true,
    }));

    synthesis.speak(greetingText).then(() => {
      setAvatarState((prev) => ({
        ...prev,
        gesture: AvatarGesture.LISTENING,
        isSpeaking: false,
      }));
      setIsReady(true);
      setConversation((prev) => ({
        ...prev,
        phase: ConversationPhase.EXPERIENCE_QUESTION,
        isSpeaking: false,
      }));
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Process speech result when user finishes
  useEffect(() => {
    if (speech.transcript && !speech.isListening) {
      handleUserInput(speech.transcript);
      speech.resetTranscript();
    }
  }, [speech.transcript, speech.isListening]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleUserInput = useCallback(
    async (userText: string) => {
      // Show what user said
      setCurrentSubtitle(userText);
      setAvatarState((prev) => ({
        ...prev,
        gesture: AvatarGesture.NODDING,
        expression: AvatarExpression.THINKING,
        isSpeaking: false,
      }));

      // Small pause for natural feel
      await new Promise((r) => setTimeout(r, 500));

      // Process through conversation flow
      const { nextState, avatarResponse } = processUserInput(
        conversation,
        userText
      );

      setConversation(nextState);
      setCurrentSubtitle(avatarResponse);

      // Update avatar expression based on sentiment
      const expression = getExpressionForPhase(
        nextState.phase,
        nextState.sentiment
      );
      setAvatarState({
        expression,
        gesture: AvatarGesture.TALKING,
        isSpeaking: true,
        lookAtCamera: true,
      });

      // Speak the response
      await synthesis.speak(avatarResponse);

      // After speaking, switch to listening mode
      setAvatarState((prev) => ({
        ...prev,
        gesture: AvatarGesture.LISTENING,
        expression: AvatarExpression.NEUTRAL,
        isSpeaking: false,
      }));

      setConversation((prev) => ({
        ...prev,
        isSpeaking: false,
        isListening: true,
      }));
    },
    [conversation, synthesis]
  );

  const handleUserFinishedSpeaking = useCallback(() => {
    speech.stopListening();
  }, [speech]);

  const startListening = useCallback(() => {
    setCurrentSubtitle('');
    speech.startListening();
    setConversation((prev) => ({ ...prev, isListening: true }));
    setAvatarState((prev) => ({
      ...prev,
      gesture: AvatarGesture.LISTENING,
      expression: AvatarExpression.NEUTRAL,
    }));
  }, [speech]);

  const stopListening = useCallback(() => {
    speech.stopListening();
    setConversation((prev) => ({ ...prev, isListening: false }));
  }, [speech]);

  return {
    conversation,
    avatarState,
    currentSubtitle:
      speech.interimTranscript || currentSubtitle,
    handleUserFinishedSpeaking,
    startListening,
    stopListening,
    isReady,
  };
}

function getExpressionForPhase(
  phase: ConversationPhase,
  sentiment: SentimentResult | null
): AvatarExpression {
  switch (phase) {
    case ConversationPhase.GREETING:
      return AvatarExpression.SMILE;
    case ConversationPhase.DETAIL_FOLLOWUP:
      return sentiment === SentimentResult.NEGATIVE
        ? AvatarExpression.EMPATHY
        : AvatarExpression.SMILE;
    case ConversationPhase.SUMMARY_CONFIRMATION:
      return AvatarExpression.THINKING;
    case ConversationPhase.ROUTING:
      return sentiment === SentimentResult.NEGATIVE
        ? AvatarExpression.EMPATHY
        : AvatarExpression.GRATEFUL;
    case ConversationPhase.REWARD:
      return AvatarExpression.SMILE;
    default:
      return AvatarExpression.NEUTRAL;
  }
}
